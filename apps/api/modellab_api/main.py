"""REST API. Reads are open on loopback, and anything that runs a model or changes state needs the admin token."""
from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Any, Generic, TypeVar

import yaml
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse, StreamingResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from modellab_adapters import get_adapter
from modellab_api.auth import require_admin
from modellab_api.campaigns import (
    TERMINAL, build_report, create_experiment, create_run, hardware_details, mark_interrupted,
    submit_run, sync_registry,
)
from modellab_api.db import (
    Artifact, CampaignConfigRow, EvaluationResult, Experiment, GuardrailDecisionRow, InferenceEvent, Model, ModelRevision,
    ResearchReport, Run, ToolEventRow, TrainingJob, Trial, get_factory, now,
)
from modellab_experiments.scenarios import load_scenarios, manifest_hash
from modellab_guardrails import GUARDRAIL_PRESETS, build_guardrails
from modellab_inference import run_inference
from modellab_observability import redact
from modellab_schemas import Backend, CampaignConfig, GenerationConfig, Message, ModelEntry, Scenario

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


def session_dep() -> Iterator[Session]:
    with get_factory()() as session:
        yield session


def paginate(session: Session, stmt, serialize, limit: int, offset: int) -> dict:
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = session.scalars(stmt.limit(limit).offset(offset)).all()
    return {"items": [serialize(r) for r in rows], "total": total, "limit": limit, "offset": offset}


Limit = Query(50, ge=1, le=500)
Offset = Query(0, ge=0)


def columns(row, exclude: tuple[str, ...] = ()) -> dict:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name not in exclude}


@asynccontextmanager
async def lifespan(_: FastAPI):
    factory = get_factory()
    mark_interrupted(factory)
    with factory() as session:
        sync_registry(session)
    yield


app = FastAPI(title="ModelLab", version="0.1.0", lifespan=lifespan,
              description="Local-first AI security research API. Bind to loopback. See docs/threat-model.md.")
Admin = Depends(require_admin)
# Stops DNS rebinding: a hostile website can't reach this loopback API under its own hostname.
_hosts = ["127.0.0.1", "localhost", "[::1]", "testserver", *filter(None, os.environ.get("MODELLAB_ALLOWED_HOSTS", "").split(","))]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_hosts)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/system")
def system() -> dict:
    disk = shutil.disk_usage("/")
    return {"hardware": hardware_details(), "disk_free_gb": round(disk.free / 1e9, 1), "platform": platform.platform()}


# Models ---------------------------------------------------------------------------------------------------------
def model_view(m: Model) -> dict:
    return {"id": m.id, "entry": m.entry, "download_status": m.download_status, "runtime_status": m.runtime_status,
            "created_at": m.created_at, "revisions": [{"revision": r.revision, "artifact_hash": r.artifact_hash, "recorded_at": r.recorded_at} for r in m.revisions]}


@app.get("/api/models")
def list_models(limit: int = Limit, offset: int = Offset, session: Session = Depends(session_dep)) -> dict:
    return paginate(session, select(Model).order_by(Model.id), model_view, limit, offset)


@app.post("/api/models", status_code=201, dependencies=[Admin])
def register_model(entry: ModelEntry, session: Session = Depends(session_dep)) -> dict:
    if session.get(Model, entry.id):
        raise HTTPException(409, f"model {entry.id} already exists")
    row = Model(id=entry.id, entry=entry.model_dump(mode="json"), download_status="not_applicable" if entry.backend == Backend.mock else "unknown")
    session.add(row)
    session.commit()
    return model_view(row)


def _model(session: Session, model_id: str) -> Model:
    row = session.get(Model, model_id)
    if row is None:
        raise HTTPException(404, f"no model {model_id}")
    return row


@app.get("/api/models/{model_id}")
def get_model(model_id: str, session: Session = Depends(session_dep)) -> dict:
    return model_view(_model(session, model_id))


@app.get("/api/models/{model_id}/health")
def model_health(model_id: str, session: Session = Depends(session_dep)) -> dict:
    row = _model(session, model_id)
    result = get_adapter(ModelEntry.model_validate(row.entry)).health_check()
    digest = result.get("digest")
    if row.entry["backend"] != "mock":
        row.download_status = "ready" if digest or result.get("ok") else row.download_status
    if digest and not session.scalar(select(ModelRevision).where(ModelRevision.model_id == row.id, ModelRevision.artifact_hash == digest)):
        session.add(ModelRevision(model_id=row.id, revision=row.entry.get("revision"), artifact_hash=digest))
    session.commit()
    return result


@app.post("/api/models/{model_id}/pull", dependencies=[Admin])
def model_pull(model_id: str, session: Session = Depends(session_dep)) -> StreamingResponse:
    entry = ModelEntry.model_validate(_model(session, model_id).entry)
    if entry.backend != Backend.ollama:
        raise HTTPException(400, "use `modellab models pull` for this backend")

    def stream() -> Iterator[str]:
        for status in get_adapter(entry).pull():
            yield json.dumps(status) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.post("/api/models/{model_id}/start", dependencies=[Admin])
def model_start(model_id: str, session: Session = Depends(session_dep)) -> dict:
    row = _model(session, model_id)
    get_adapter(ModelEntry.model_validate(row.entry)).load_model()
    row.runtime_status = "running"
    session.commit()
    return model_view(row)


@app.post("/api/models/{model_id}/stop", dependencies=[Admin])
def model_stop(model_id: str, session: Session = Depends(session_dep)) -> dict:
    row = _model(session, model_id)
    get_adapter(ModelEntry.model_validate(row.entry)).unload_model()
    row.runtime_status = "stopped"
    session.commit()
    return model_view(row)


@app.get("/api/models/{model_id}/history")
def model_history(model_id: str, limit: int = Limit, offset: int = Offset, session: Session = Depends(session_dep)) -> dict:
    _model(session, model_id)
    stmt = select(InferenceEvent).where(InferenceEvent.model_id == model_id).order_by(InferenceEvent.created_at.desc())
    return paginate(session, stmt, columns, limit, offset)


# Inference ------------------------------------------------------------------------------------------------------
class InferenceRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_id: str
    messages: list[Message] = Field(min_length=1)
    config: GenerationConfig = GenerationConfig()


@app.post("/api/inference", dependencies=[Admin])
def inference(req: InferenceRequest, session: Session = Depends(session_dep)) -> dict:
    entry = ModelEntry.model_validate(_model(session, req.model_id).entry)
    result = run_inference(get_adapter(entry), req.messages, req.config)
    data = result.model_dump(mode="json", exclude={"text"})
    session.add(InferenceEvent(model_id=req.model_id, data=data))
    session.commit()
    return result.model_dump(mode="json")


# Scenarios and guardrails ---------------------------------------------------------------------------------------
@app.get("/api/scenarios")
def scenarios(kind: str | None = None, family: str | None = None, limit: int = Query(200, ge=1, le=500), offset: int = Offset) -> dict:
    items = [s for s in load_scenarios().values() if (not kind or s.kind == kind) and (not family or s.family == family)]
    return {"items": [s.model_dump(mode="json") for s in items[offset:offset + limit]], "total": len(items), "limit": limit,
            "offset": offset, "manifest_hash": manifest_hash()}


class ScenarioDraft(BaseModel):
    yaml_text: str = Field(max_length=100_000)


@app.post("/api/scenarios/validate")
def validate_scenario(draft: ScenarioDraft) -> dict:
    """Checks a draft against the schema. Nothing is saved: scenarios live in versioned YAML in the repository."""
    try:
        data = yaml.safe_load(draft.yaml_text)
        scenario = Scenario.model_validate(data)
    except yaml.YAMLError as exc:
        return {"valid": False, "errors": [f"YAML: {exc}"]}
    except ValidationError as exc:
        return {"valid": False, "errors": [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]}
    return {"valid": True, "errors": [], "scenario": scenario.model_dump(mode="json")}


@app.get("/api/guardrails")
def guardrails() -> dict:
    items = []
    for preset in GUARDRAIL_PRESETS:
        built = build_guardrails(preset)
        items.append({"preset": preset, "config_hash": built.config_hash(), "prompt_defense": built.prompt_defense, "enforce_retrieval_acl": built.enforce_retrieval_acl,
                      "guardrails": [{"name": g.name, "version": g.version, "stages": list(g.stages), "deterministic": g.deterministic} for g in built.guardrails]})
    return {"items": items, "total": len(items)}


# Experiments and runs -------------------------------------------------------------------------------------------
def run_view(session: Session, r: Run) -> dict:
    counts = dict(session.execute(select(Trial.status, func.count()).where(Trial.run_id == r.id).group_by(Trial.status)).all())
    exp = session.get(Experiment, r.experiment_id)
    return {**columns(r), "experiment_name": exp.name, "trial_counts": counts}


@app.get("/api/experiments")
def list_experiments(limit: int = Limit, offset: int = Offset, session: Session = Depends(session_dep)) -> dict:
    return paginate(session, select(Experiment).order_by(Experiment.created_at.desc()), columns, limit, offset)


@app.post("/api/experiments", status_code=201, dependencies=[Admin])
def new_experiment(config: CampaignConfig, session: Session = Depends(session_dep)) -> dict:
    try:
        return columns(create_experiment(session, config))
    except (ValueError, KeyError, ValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/experiments/{experiment_id}")
def get_experiment(experiment_id: str, session: Session = Depends(session_dep)) -> dict:
    exp = session.get(Experiment, experiment_id)
    if exp is None:
        raise HTTPException(404, "no such experiment")
    cfg = session.scalar(select(CampaignConfigRow).where(CampaignConfigRow.experiment_id == exp.id))
    runs = session.scalars(select(Run).where(Run.experiment_id == exp.id).order_by(Run.created_at.desc())).all()
    return {**columns(exp), "config": cfg.config if cfg else None, "config_hash": cfg.config_hash if cfg else None, "runs": [run_view(session, r) for r in runs]}


@app.post("/api/experiments/{experiment_id}/run", status_code=202, dependencies=[Admin])
def start_run(experiment_id: str, session: Session = Depends(session_dep)) -> dict:
    if session.get(Experiment, experiment_id) is None:
        raise HTTPException(404, "no such experiment")
    run = create_run(session, experiment_id)
    submit_run(get_factory(), run.id)
    return run_view(session, run)


@app.get("/api/runs")
def list_runs(status: str | None = None, limit: int = Limit, offset: int = Offset, session: Session = Depends(session_dep)) -> dict:
    stmt = select(Run).order_by(Run.created_at.desc())
    if status:
        stmt = stmt.where(Run.status == status)
    return paginate(session, stmt, lambda r: run_view(session, r), limit, offset)


def _run(session: Session, run_id: str) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "no such run")
    return run


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, session: Session = Depends(session_dep)) -> dict:
    return run_view(session, _run(session, run_id))


@app.post("/api/runs/{run_id}/cancel", dependencies=[Admin])
def cancel_run(run_id: str, session: Session = Depends(session_dep)) -> dict:
    run = _run(session, run_id)
    if run.status in TERMINAL:
        raise HTTPException(409, f"run already {run.status}")
    run.cancel_requested = True
    session.commit()
    return run_view(session, run)


@app.post("/api/runs/{run_id}/resume", status_code=202, dependencies=[Admin])
def resume_run(run_id: str, session: Session = Depends(session_dep)) -> dict:
    run = _run(session, run_id)
    if run.status not in ("interrupted", "cancelled", "failed"):
        raise HTTPException(409, f"cannot resume a {run.status} run")
    run.cancel_requested = False
    run.status = "queued"
    session.commit()
    submit_run(get_factory(), run.id)
    return run_view(session, run)


@app.get("/api/runs/{run_id}/trials")
def run_trials(run_id: str, limit: int = Limit, offset: int = Offset, session: Session = Depends(session_dep)) -> dict:
    _run(session, run_id)
    stmt = select(Trial).where(Trial.run_id == run_id).order_by(Trial.key)
    return paginate(session, stmt, lambda t: columns(t, ("transcript",)), limit, offset)


def trace_view(session: Session, t: Trial) -> dict:
    tools = session.scalars(select(ToolEventRow).where(ToolEventRow.trial_id == t.id).order_by(ToolEventRow.seq)).all()
    decisions = session.scalars(select(GuardrailDecisionRow).where(GuardrailDecisionRow.trial_id == t.id)).all()
    infer = session.scalars(select(InferenceEvent).where(InferenceEvent.trial_id == t.id).order_by(InferenceEvent.step)).all()
    return {**columns(t), "tool_events": [columns(e) for e in tools], "guardrail_decisions": [d.data for d in decisions], "inference_events": [i.data for i in infer]}


@app.get("/api/runs/{run_id}/traces")
def run_traces(run_id: str, scenario: str | None = None, model: str | None = None, guardrail: str | None = None, outcome: str | None = None,
               limit: int = Query(25, ge=1, le=200), offset: int = Offset, session: Session = Depends(session_dep)) -> dict:
    _run(session, run_id)
    stmt = select(Trial).where(Trial.run_id == run_id).order_by(Trial.key)
    if scenario:
        stmt = stmt.where(Trial.scenario_id.contains(scenario))
    if model:
        stmt = stmt.where(Trial.model_id == model)
    if guardrail:
        stmt = stmt.where(Trial.guardrail_preset == guardrail)
    if outcome == "compromised":
        stmt = stmt.where(Trial.objective_achieved.is_(True))
    elif outcome == "blocked":
        stmt = stmt.where(Trial.blocked_attempts > 0)
    elif outcome == "error":
        stmt = stmt.where(Trial.status == "error")
    return paginate(session, stmt, lambda t: trace_view(session, t), limit, offset)


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str) -> StreamingResponse:
    """Server-sent events. Each message is a persisted fact from the database, never a simulated one."""
    factory = get_factory()
    with factory() as session:
        _run(session, run_id)

    async def stream():
        seen: set[str] = set()
        while True:
            with factory() as session:
                run = session.get(Run, run_id)
                trials = session.scalars(select(Trial).where(Trial.run_id == run_id, Trial.finished_at.is_not(None))).all()
                for t in trials:
                    if t.id not in seen:
                        seen.add(t.id)
                        event = {"type": "trial", "scenario_id": t.scenario_id, "model_id": t.model_id, "guardrail_preset": t.guardrail_preset,
                                 "status": t.status, "objective_achieved": t.objective_achieved, "legit_success": t.legit_success, "wall_ms": t.wall_ms, "id": t.id}
                        yield f"data: {json.dumps(event)}\n\n"
                yield f"data: {json.dumps({'type': 'run', 'status': run.status, 'done': len(seen), 'total': run.total_trials})}\n\n"
                if run.status in TERMINAL:
                    return
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# Evaluations ----------------------------------------------------------------------------------------------------
@app.get("/api/evaluations")
def evaluations(run_id: str | None = None, limit: int = Query(200, ge=1, le=500), offset: int = Offset, session: Session = Depends(session_dep)) -> dict:
    stmt = select(EvaluationResult).order_by(EvaluationResult.created_at.desc())
    if run_id:
        stmt = stmt.where(EvaluationResult.run_id == run_id)

    def view(e: EvaluationResult) -> dict:
        run = session.get(Run, e.run_id)
        exp = session.get(Experiment, run.experiment_id)
        variant = ((run.provenance or {}).get("models") or {}).get(e.model_id, {}).get("variant")
        return {**columns(e), "experiment_name": exp.name, "run_status": run.status, "variant": variant}

    return paginate(session, stmt, view, limit, offset)


def _report_for(session: Session, ref: str) -> ResearchReport:
    """Accepts an evaluation ID or run ID, and rebuilds so a report always reflects stored records."""
    evaluation = session.get(EvaluationResult, ref)
    run_id = evaluation.run_id if evaluation else ref
    if session.get(Run, run_id) is None:
        raise HTTPException(404, "no such evaluation or run")
    return build_report(session, run_id)


@app.get("/api/evaluations/{ref}/report", response_model=None)
def report(ref: str, format: str = Query("json", pattern="^(json|markdown|csv)$"), session: Session = Depends(session_dep)) -> Any:
    from modellab_evaluation.report import to_csv

    row = _report_for(session, ref)
    if format == "markdown":
        return PlainTextResponse(row.markdown, media_type="text/markdown")
    if format == "csv":
        return PlainTextResponse(to_csv(row.body), media_type="text/csv")
    return row.body


@app.get("/api/reports")
def reports(limit: int = Limit, offset: int = Offset, session: Session = Depends(session_dep)) -> dict:
    """The latest report per run is what readers want, so this lists runs that finished."""
    stmt = select(Run).where(Run.status.in_(["completed", "cancelled"])).order_by(Run.created_at.desc())
    return paginate(session, stmt, lambda r: run_view(session, r), limit, offset)


@app.get("/api/overview")
def overview(session: Session = Depends(session_dep)) -> dict:
    active = session.scalars(select(Run).where(Run.status.in_(["queued", "running"])).order_by(Run.created_at.desc())).all()
    latest = session.scalars(select(Run).where(Run.status == "completed").order_by(Run.finished_at.desc()).limit(8)).all()
    trend = []
    for run in reversed(latest):
        for e in session.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run.id)):
            variant = ((run.provenance or {}).get("models") or {}).get(e.model_id, {}).get("variant")
            trend.append({"run_id": run.id, "experiment": session.get(Experiment, run.experiment_id).name, "finished_at": run.finished_at, "model_id": e.model_id,
                          "guardrail_preset": e.guardrail_preset, "variant": variant, "attack_success": e.metrics["attack_success"]})
    return {"models": [model_view(m) for m in session.scalars(select(Model).order_by(Model.id))], "active_runs": [run_view(session, r) for r in active],
            "latest_runs": [run_view(session, r) for r in latest], "trend": trend, "system": system()}


# Training -------------------------------------------------------------------------------------------------------
class TrainingRequest(BaseModel):
    kind: str = Field(default="tfidf-logreg", pattern="^(tfidf-logreg|encoder-logreg)$")
    epochs: int = Field(default=50, gt=0, le=500)
    seed: int = 7


def run_training(job_id: str, req: TrainingRequest) -> None:
    from modellab_training import train_baseline, train_encoder

    factory = get_factory()
    with factory() as session:
        job = session.get(TrainingJob, job_id)
        job.status = "running"
        session.commit()
        try:
            metrics = train_baseline(epochs=req.epochs, seed=req.seed) if req.kind == "tfidf-logreg" else train_encoder(seed=req.seed)
            if path := metrics.get("artifact_path"):
                artifact = Artifact(kind="classifier", path=path, sha256=metrics["artifact_sha256"], meta={"dataset": metrics["dataset"]["version"]})
                session.add(artifact)
                session.flush()
                job.artifact_id = artifact.id
            job.metrics, job.status = metrics, "completed"
        except Exception as exc:  # noqa: BLE001 - stored on the job
            job.status, job.error = "failed", redact(f"{type(exc).__name__}: {exc}")
        job.finished_at = now()
        session.commit()


@app.get("/api/training/jobs")
def training_jobs(limit: int = Limit, offset: int = Offset, session: Session = Depends(session_dep)) -> dict:
    return paginate(session, select(TrainingJob).order_by(TrainingJob.created_at.desc()), columns, limit, offset)


@app.post("/api/training/jobs", status_code=202, dependencies=[Admin])
def create_training_job(req: TrainingRequest, session: Session = Depends(session_dep)) -> dict:
    import threading

    job = TrainingJob(kind=req.kind, config=req.model_dump())
    session.add(job)
    session.commit()
    threading.Thread(target=run_training, args=(job.id, req), daemon=True).start()
    return columns(job)


@app.get("/api/training/jobs/{job_id}")
def training_job(job_id: str, session: Session = Depends(session_dep)) -> dict:
    job = session.get(TrainingJob, job_id)
    if job is None:
        raise HTTPException(404, "no such job")
    return columns(job)


