"""Campaign execution: expands the trial matrix, persists evidence, and computes metrics from it."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import threading
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from modellab_adapters import get_adapter
from modellab_api.db import (
    CampaignConfigRow, EvaluationResult, Experiment, GeneratedPayload, GuardrailDecisionRow, InferenceEvent, Model,
    ModelRevision, Run, ScenarioSuite, ScenarioVersion, ToolEventRow, Trial, now,
)
from modellab_evaluation import aggregate_trials
from modellab_experiments.adversarial import generate_candidates
from modellab_experiments.agent import Cancelled, run_trial
from modellab_experiments.scenarios import load_model_configs, load_scenarios, manifest_hash, repo_root
from modellab_guardrails import build_guardrails
from modellab_observability import redact, redact_obj, withhold
from modellab_schemas import Backend, CampaignConfig, ModelEntry, Scenario, ScenarioKind

TERMINAL = {"completed", "cancelled", "failed", "interrupted"}


def git_commit() -> str:
    try:
        root = repo_root()
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip()
        return f"{commit}{'+dirty' if dirty else ''}"
    except (subprocess.CalledProcessError, FileNotFoundError, RuntimeError):
        return "unknown"


def hardware_details() -> dict:
    details = {"system": platform.system(), "machine": platform.machine(), "python": platform.python_version()}
    if platform.system() == "Darwin":
        for key, name in (("machdep.cpu.brand_string", "cpu"), ("hw.memsize", "memory_bytes")):
            try:
                details[name] = subprocess.check_output(["sysctl", "-n", key], text=True).strip()
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass
    return details


def sync_registry(session: Session) -> list[Model]:
    """Adds configs/models entries that aren't in the database. Existing rows are left alone."""
    known = {m.id for m in session.scalars(select(Model))}
    for entry in load_model_configs():
        if entry.id not in known:
            session.add(Model(id=entry.id, entry=entry.model_dump(mode="json"),
                              download_status="not_applicable" if entry.backend == Backend.mock else "unknown"))
    session.commit()
    return list(session.scalars(select(Model).order_by(Model.id)))


def _ensure_suite(session: Session) -> ScenarioSuite:
    mhash = manifest_hash()
    suite = session.scalar(select(ScenarioSuite).where(ScenarioSuite.manifest_hash == mhash))
    if suite:
        return suite
    scenarios = load_scenarios()
    suite = ScenarioSuite(manifest_hash=mhash, scenario_count=len(scenarios))
    session.add(suite)
    session.flush()
    for s in scenarios.values():
        session.add(ScenarioVersion(suite_id=suite.id, scenario_id=s.id, version=s.version, spec=s.model_dump(mode="json")))
    return suite


def select_scenarios(config: CampaignConfig) -> list[Scenario]:
    all_scenarios = load_scenarios()
    if config.scenarios:
        missing = set(config.scenarios) - set(all_scenarios)
        if missing:
            raise ValueError(f"unknown scenarios: {sorted(missing)}")
        return [all_scenarios[i] for i in config.scenarios]
    chosen = [s for s in all_scenarios.values() if s.kind in config.kinds]
    return [s for s in chosen if not config.family or config.family in ("G", "H", "I", "J") or s.family == config.family]


def create_experiment(session: Session, config: CampaignConfig) -> Experiment:
    sync_registry(session)
    known = {m.id for m in session.scalars(select(Model))}
    wanted = set(config.defenders) | ({config.attacker} if config.attacker else set())
    if wanted - known:
        raise ValueError(f"unregistered models: {sorted(wanted - known)}")
    for preset in config.guardrails:
        if preset != "trained_classifier":
            build_guardrails(preset)
    select_scenarios(config)
    experiment = Experiment(name=config.name, family=config.family)
    session.add(experiment)
    session.flush()
    data = config.model_dump(mode="json")
    session.add(CampaignConfigRow(experiment_id=experiment.id, config=data,
                                  config_hash=hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]))
    session.commit()
    return experiment


def create_run(session: Session, experiment_id: str) -> Run:
    cfg = session.scalar(select(CampaignConfigRow).where(CampaignConfigRow.experiment_id == experiment_id))
    if cfg is None:
        raise KeyError(experiment_id)
    suite = _ensure_suite(session)
    run = Run(experiment_id=experiment_id, campaign_config_id=cfg.id, suite_id=suite.id)
    session.add(run)
    session.commit()
    return run


def load_trained_classifier():
    from modellab_guardrails import TrainedInjectionClassifier
    from modellab_training import load_scorer, latest_classifier_path

    path = latest_classifier_path()
    if path is None:
        raise ValueError("no trained classifier found; run: modellab train classifier")
    return TrainedInjectionClassifier(load_scorer(path), version=path.stem)


def _guardrails(preset: str):
    if preset == "trained_classifier":
        return build_guardrails(preset, trained=load_trained_classifier())
    return build_guardrails(preset)


def _provenance(session: Session, config: CampaignConfig, run: Run) -> dict:
    models = {}
    for mid in dict.fromkeys(config.defenders + ([config.attacker] if config.attacker else [])):
        entry = ModelEntry.model_validate(session.get(Model, mid).entry)
        adapter = get_adapter(entry)
        health = adapter.health_check()
        digest = health.get("digest")
        models[mid] = {"repo": entry.hf_repo, "revision": entry.revision, "quantization": entry.quantization,
                       "backend": entry.backend.value, "backend_model": entry.backend_model,
                       "backend_version": health.get("version"), "artifact_digest": digest, "variant": entry.variant.value}
        if digest and not session.scalar(select(ModelRevision).where(
                ModelRevision.model_id == mid, ModelRevision.artifact_hash == digest)):
            session.add(ModelRevision(model_id=mid, revision=entry.revision, artifact_hash=digest))
    return {
        "git_commit": git_commit(), "models": models, "scenario_manifest_hash": manifest_hash(),
        "guardrail_config_hashes": {p: _guardrails(p).config_hash() for p in config.guardrails},
        "decoding": config.generation.model_dump(mode="json"), "base_seed": config.base_seed,
        "hardware": hardware_details(), "trial_count_per_cell": config.trials, "dataset_version": None,
    }


def _record_trial(session: Session, trial: Trial, outcome, scenario: Scenario) -> None:
    g = outcome.grade
    label = scenario.request_label
    trial.status = "error" if outcome.error else "completed"
    trial.error = redact(outcome.error)
    trial.objective_achieved, trial.legit_success, trial.refused = g.objective_achieved, g.legit_success, g.refused
    trial.unauthorized_attempts = g.unauthorized_attempts
    trial.unauthorized_executions = g.unauthorized_executions
    trial.blocked_attempts = g.blocked_attempts
    trial.false_positive_denials = g.false_positive_denials
    trial.guardrail_intervened = outcome.guardrail_intervened
    trial.timed_out = outcome.timed_out
    trial.answer = withhold(outcome.answer, label)
    trial.evidence = [redact(e) for e in g.evidence]
    trial.transcript = [
        {"role": m.role, "content": withhold(m.content, label) if m.role == "assistant" else redact(m.content)}
        for m in outcome.transcript
    ]
    trial.wall_ms = outcome.wall_ms
    done = [i for i in outcome.inferences if not i.error]
    trial.total_tokens = sum((i.prompt_tokens or 0) + (i.completion_tokens or 0) for i in done) or None
    rates = [i.tokens_per_s for i in done if i.tokens_per_s]
    trial.tokens_per_s = sum(rates) / len(rates) if rates else None
    gpu = [i.gpu_memory_mb for i in done if i.gpu_memory_mb]
    trial.gpu_memory_mb = max(gpu) if gpu else None
    trial.finished_at = now()
    for step, result in enumerate(outcome.inferences):
        data = result.model_dump(mode="json", exclude={"text"})
        data["error"] = redact(data["error"])
        session.add(InferenceEvent(trial_id=trial.id, model_id=trial.model_id, step=step, data=data))
    for e in outcome.events:
        session.add(ToolEventRow(trial_id=trial.id, seq=e.seq, tool=e.tool, args=redact_obj(e.args), executed=e.executed,
                                 denied_by=e.denied_by, ok=e.ok, result=redact(e.result)))
    for d in outcome.decisions:
        session.add(GuardrailDecisionRow(trial_id=trial.id, data=redact_obj(d.model_dump(mode="json"))))


def trial_dict(t: Trial) -> dict:
    return {c.name: getattr(t, c.name) for c in Trial.__table__.columns
            if c.name not in ("transcript", "evidence", "answer", "finished_at")}


def compute_evaluations(session: Session, run_id: str) -> list[EvaluationResult]:
    """Metrics come only from persisted trial records, so they can be recomputed at any time."""
    for old in session.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run_id)):
        session.delete(old)
    session.flush()
    trials = [trial_dict(t) for t in session.scalars(select(Trial).where(Trial.run_id == run_id))]
    groups = {(t["model_id"], t["guardrail_preset"]) for t in trials}
    out = []
    for model_id, preset in sorted(groups):
        rows = [t for t in trials if t["model_id"] == model_id and t["guardrail_preset"] == preset]
        out.append(EvaluationResult(run_id=run_id, model_id=model_id, guardrail_preset=preset, metrics=aggregate_trials(rows)))
    session.add_all(out)
    session.commit()
    return out


def execute_run(factory: sessionmaker, run_id: str) -> None:
    """Restart-safe: finished trials are skipped by their stable key, so this also resumes interrupted runs."""
    with factory() as session:
        run = session.get(Run, run_id)
        config = CampaignConfig.model_validate(session.get(CampaignConfigRow, run.campaign_config_id).config)
        run.status, run.started_at, run.error = "running", run.started_at or now(), None
        try:
            run.provenance = _provenance(session, config, run)
            session.commit()
            _execute(session, run, config)
        except Exception as exc:  # noqa: BLE001 - a run's failure is data, stored on the run
            session.rollback()
            run = session.get(Run, run_id)
            run.status, run.error, run.finished_at = "failed", redact(f"{type(exc).__name__}: {exc}"), now()
            session.commit()
            raise


def _payloads(session: Session, run: Run, config: CampaignConfig, scenario: Scenario) -> list[GeneratedPayload | None]:
    if config.attack_strategy == "scenario" or scenario.kind != ScenarioKind.attack:
        return [None]
    existing = list(session.scalars(select(GeneratedPayload).where(
        GeneratedPayload.run_id == run.id, GeneratedPayload.scenario_id == scenario.id)))
    if not existing:
        attacker = None
        if config.attacker:
            attacker = get_adapter(ModelEntry.model_validate(session.get(Model, config.attacker).entry))
        for c in generate_candidates(scenario, config.attack_strategy, config.attack_budget, attacker):
            row = GeneratedPayload(run_id=run.id, scenario_id=scenario.id, strategy=c.strategy, payload=c.payload,
                                   valid=c.valid, fingerprint=c.fingerprint, trace_ref=c.trace_ref)
            session.add(row)
            existing.append(row)
        session.commit()
    return [p for p in existing if p.valid]


def _execute(session: Session, run: Run, config: CampaignConfig) -> None:
    scenarios = select_scenarios(config)
    adapters = {m: get_adapter(ModelEntry.model_validate(session.get(Model, m).entry)) for m in config.defenders}
    finished = {t.key: t for t in session.scalars(select(Trial).where(Trial.run_id == run.id))}
    matrix = []
    for scenario in scenarios:
        for payload in _payloads(session, run, config, scenario):
            for model in config.defenders:
                # Guardrails don't change refusal measurement, so refusal scenarios run once per model.
                presets = config.guardrails[:1] if scenario.kind == ScenarioKind.refusal else config.guardrails
                for preset in presets:
                    for i in range(config.trials):
                        matrix.append((scenario, payload, model, preset, i))
    run.total_trials = len(matrix)
    session.commit()

    def cancelled() -> bool:
        session.refresh(run, ["cancel_requested"])
        return run.cancel_requested

    for scenario, payload, model, preset, i in matrix:
        key = f"{scenario.id}@{scenario.version}|{model}|{preset}|{i}|{payload.id if payload else '-'}"
        prior = finished.get(key)
        if prior and prior.status == "completed":
            continue
        if cancelled():
            run.status, run.finished_at = "cancelled", now()
            session.commit()
            compute_evaluations(session, run.id)
            return
        seed = config.base_seed + i
        trial = prior or Trial(run_id=run.id, key=key, scenario_id=scenario.id, scenario_version=scenario.version,
                               category=scenario.category, kind=scenario.kind.value, request_label=scenario.request_label,
                               model_id=model, guardrail_preset=preset, trial_index=i, seed=seed,
                               payload_id=payload.id if payload else None)
        trial.status = "running"
        session.add(trial)
        session.commit()
        gen = config.generation.model_copy(update={"seed": seed})
        try:
            outcome = run_trial(scenario, adapters[model], _guardrails(preset), gen,
                                payload=payload.payload if payload else None, should_cancel=cancelled)
        except Cancelled:
            session.delete(trial)
            run.status, run.finished_at = "cancelled", now()
            session.commit()
            compute_evaluations(session, run.id)
            return
        _record_trial(session, trial, outcome, scenario)
        session.commit()
    compute_evaluations(session, run.id)
    run.status, run.finished_at = "completed", now()
    session.commit()


_threads: dict[str, threading.Thread] = {}


def submit_run(factory: sessionmaker, run_id: str) -> None:
    """In-process thread by default. With REDIS_URL set and the queue extra installed, uses Dramatiq."""
    from modellab_api.worker import enqueue

    if enqueue(run_id):
        return

    def work() -> None:
        try:
            execute_run(factory, run_id)
        except Exception:  # noqa: BLE001 - already recorded on the run row
            pass

    thread = threading.Thread(target=work, name=f"run-{run_id}", daemon=True)
    _threads[run_id] = thread
    thread.start()


def mark_interrupted(factory: sessionmaker) -> int:
    """A run left 'running' at startup has no worker. Mark it, so it can be resumed rather than appear live."""
    with factory() as session:
        stale = list(session.scalars(select(Run).where(Run.status == "running")))
        stale = [r for r in stale if r.id not in _threads or not _threads[r.id].is_alive()]
        for r in stale:
            r.status = "interrupted"
        session.commit()
        return len(stale)


def write_report_files(body: dict, markdown: str, out_dir: Path) -> list[Path]:
    from modellab_evaluation.report import to_csv

    out_dir.mkdir(parents=True, exist_ok=True)
    name = body["run"]["id"]
    files = {f"{name}.json": json.dumps(body, indent=2, default=str), f"{name}.md": markdown, f"{name}.csv": to_csv(body)}
    paths = []
    for filename, text in files.items():
        path = out_dir / filename
        path.write_text(text)
        paths.append(path)
    return paths


def build_report(session: Session, run_id: str):
    from modellab_api.db import ResearchReport
    from modellab_evaluation.report import build_markdown

    run = session.get(Run, run_id)
    if run is None:
        raise KeyError(run_id)
    experiment = session.get(Experiment, run.experiment_id)
    config = session.get(CampaignConfigRow, run.campaign_config_id)
    evaluations = compute_evaluations(session, run_id)
    fixture_only = all(info.get("variant") == "fixture" for info in (run.provenance.get("models") or {}).values())
    samples = []
    seen: set = set()
    for t in session.scalars(select(Trial).where(Trial.run_id == run_id, Trial.kind == "attack", Trial.status == "completed").order_by(Trial.key)):
        pair = (t.objective_achieved, t.guardrail_preset)
        if pair in seen or len(samples) >= 4:
            continue
        seen.add(pair)
        events = session.scalars(select(ToolEventRow).where(ToolEventRow.trial_id == t.id).order_by(ToolEventRow.seq))
        samples.append({"scenario_id": t.scenario_id, "model_id": t.model_id, "guardrail_preset": t.guardrail_preset,
                        "objective_achieved": t.objective_achieved, "legit_success": t.legit_success, "evidence": t.evidence,
                        "tool_events": [{"tool": e.tool, "executed": e.executed, "denied_by": e.denied_by, "ok": e.ok} for e in events]})
    body = {
        "experiment": {"id": experiment.id, "name": experiment.name, "family": experiment.family},
        "run": {"id": run.id, "status": run.status, "total_trials": run.total_trials,
                "started_at": str(run.started_at), "finished_at": str(run.finished_at)},
        "config": config.config, "config_hash": config.config_hash, "provenance": run.provenance, "fixture_only": fixture_only,
        "evaluations": [{"model_id": e.model_id, "guardrail_preset": e.guardrail_preset, "metrics": e.metrics} for e in evaluations],
        "sample_traces": samples,
    }
    markdown = build_markdown(body)
    report = ResearchReport(run_id=run_id, body=body, markdown=markdown)
    session.add(report)
    session.commit()
    return report
