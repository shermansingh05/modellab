"""The `modellab` command line."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from modellab_adapters import get_adapter
from modellab_api.campaigns import (
    build_report,
    create_experiment,
    create_run,
    execute_run,
    sync_registry,
    write_report_files,
)
from modellab_api.db import EvaluationResult, Model, Run, get_factory
from modellab_experiments.scenarios import load_scenarios, manifest_hash, repo_root
from modellab_inference import run_inference
from modellab_schemas import Backend, CampaignConfig, GenerationConfig, Message, ModelEntry

app = typer.Typer(no_args_is_help=True, help="ModelLab: local-first AI security research.")
models_app = typer.Typer(no_args_is_help=True, help="The model registry.")
scenarios_app = typer.Typer(no_args_is_help=True, help="Scenario manifests.")
eval_app = typer.Typer(no_args_is_help=True, help="Run and compare evaluations.")
train_app = typer.Typer(no_args_is_help=True, help="Train security classifiers.")
app.add_typer(models_app, name="models")
app.add_typer(scenarios_app, name="scenarios")
app.add_typer(eval_app, name="eval")
app.add_typer(train_app, name="train")
console = Console()
JsonOpt = typer.Option(False, "--json", help="Print machine-readable JSON.")


def _emit(data) -> None:
    typer.echo(json.dumps(data, indent=2, default=str))


def _entry(session, model_id: str) -> ModelEntry:
    row = session.get(Model, model_id)
    if row is None:
        console.print(f"[red]No model {model_id}.[/red] Try: modellab models list")
        raise typer.Exit(1)
    return ModelEntry.model_validate(row.entry)


@app.command()
def doctor(as_json: bool = JsonOpt) -> None:
    """Check this machine: tools, memory, GPU, disk, and inference backends."""
    from modellab_api.campaigns import hardware_details

    checks = {
        "hardware": hardware_details(),
        "python": sys.version.split()[0],
        "disk_free_gb": round(shutil.disk_usage("/").free / 1e9, 1),
        "tools": {t: bool(shutil.which(t)) for t in ("uv", "git", "node", "ollama", "docker", "psql", "redis-server")},
        "database": os.environ.get("DATABASE_URL", "sqlite (default, var/modellab.db)").split("@")[-1],
        "admin_token_set": bool(os.environ.get("MODELLAB_ADMIN_TOKEN")),
        "queue": "dramatiq" if os.environ.get("REDIS_URL") else "in-process thread",
    }
    try:
        import torch

        checks["torch"] = {"version": torch.__version__, "cuda": torch.cuda.is_available(), "mps": torch.backends.mps.is_available()}
    except ImportError:
        checks["torch"] = "not installed (uv sync --extra ml)"
    with get_factory()() as session:
        rows = sync_registry(session)
        checks["models"] = {m.id: get_adapter(ModelEntry.model_validate(m.entry)).health_check() for m in rows}
    if as_json:
        _emit(checks)
        return
    table = Table("Check", "Result", title="modellab doctor")
    for key, value in checks.items():
        table.add_row(key, json.dumps(value, default=str) if isinstance(value, dict) else str(value))
    console.print(table)


@models_app.command("list")
def models_list(as_json: bool = JsonOpt) -> None:
    with get_factory()() as session:
        rows = sync_registry(session)
        if as_json:
            _emit([{"id": m.id, **m.entry} for m in rows])
            return
        table = Table("ID", "Variant", "Backend", "Quantization", "Repository", "Revision")
        for m in rows:
            e = m.entry
            table.add_row(m.id, e["variant"], e["backend"], e["quantization"], e.get("hf_repo") or "-", (e.get("revision") or "-")[:12])
        console.print(table)


@models_app.command("inspect")
def models_inspect(model_id: str) -> None:
    with get_factory()() as session:
        sync_registry(session)
        entry = _entry(session, model_id)
        _emit({**entry.model_dump(mode="json"), "health": get_adapter(entry).health_check()})


@models_app.command("pull")
def models_pull(model_id: str) -> None:
    """Download weights, from a pinned revision where the backend supports it."""
    with get_factory()() as session:
        sync_registry(session)
        entry = _entry(session, model_id)
        row = session.get(Model, model_id)
        if entry.backend == Backend.ollama:
            for status in get_adapter(entry).pull():
                console.print(status.get("status", ""), end="\r")
            console.print()
        elif entry.backend == Backend.transformers:
            from modellab_adapters.hf import download

            console.print(download(entry.hf_repo, entry.revision))
        else:
            console.print(f"{entry.backend.value} has nothing to pull.")
            return
        row.download_status = "ready"
        session.commit()
        console.print(f"[green]Pulled {model_id}.[/green]")


@models_app.command("serve")
def models_serve(model_id: str, stop: bool = typer.Option(False, help="Unload instead.")) -> None:
    """Load a model into its backend, or unload it."""
    with get_factory()() as session:
        sync_registry(session)
        entry = _entry(session, model_id)
        adapter = get_adapter(entry)
        adapter.unload_model() if stop else adapter.load_model()
        session.get(Model, model_id).runtime_status = "stopped" if stop else "running"
        session.commit()
        console.print(f"{model_id}: {'stopped' if stop else 'loaded'}")


@app.command()
def infer(model_id: str, prompt: str, max_tokens: int = 256, temperature: float = 0.0, seed: int = 0, as_json: bool = JsonOpt) -> None:
    """Run one prompt and show the recorded metrics."""
    with get_factory()() as session:
        sync_registry(session)
        entry = _entry(session, model_id)
    result = run_inference(get_adapter(entry), [Message(role="user", content=prompt)],
                           GenerationConfig(max_tokens=max_tokens, temperature=temperature, seed=seed))
    if as_json:
        _emit(result.model_dump(mode="json"))
        return
    if result.error:
        console.print(f"[red]{result.error}[/red]")
        raise typer.Exit(1)
    console.print(result.text)
    console.print(f"[dim]{result.prompt_tokens} prompt + {result.completion_tokens} completion tokens, {result.wall_ms:.0f} ms, ttft {result.ttft_ms}, {result.tokens_per_s} tok/s[/dim]")


@scenarios_app.command("list")
def scenarios_list(kind: str = typer.Option(None), as_json: bool = JsonOpt) -> None:
    items = [s for s in load_scenarios().values() if not kind or s.kind == kind]
    if as_json:
        _emit([s.model_dump(mode="json") for s in items])
        return
    table = Table("ID", "Family", "Kind", "Category", "Surface", title=f"{len(items)} scenarios, manifest {manifest_hash()}")
    for s in items:
        table.add_row(s.id, s.family, s.kind.value, s.category, s.attacker_surface.value)
    console.print(table)


def _print_eval(session, run_id: str) -> None:
    table = Table(title=f"Run {run_id}")
    for name in ("Model", "Guardrails"):
        table.add_column(name, overflow="fold")
    for name in ("Attacks won", "Legit tasks", "Unauth. ran", "False pos.", "Median ms", "Errors"):
        table.add_column(name, justify="right", no_wrap=True)

    def fmt(p) -> str:
        return f"{p['k']}/{p['n']}" if p["n"] else "-"

    for e in session.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run_id).order_by(EvaluationResult.model_id, EvaluationResult.guardrail_preset)):
        m = e.metrics
        median = m["latency_ms"]["median"]
        table.add_row(e.model_id, e.guardrail_preset, fmt(m["attack_success"]), fmt(m["legit_task_success"]), fmt(m["unauthorized_execution_rate"]),
                      fmt(m["false_positive_trials"]), f"{median:.0f}" if median is not None else "-", str(m["trials"]["errored"]))
    console.print(table)


def _run_config(config: CampaignConfig) -> str:
    factory = get_factory()
    with factory() as session:
        experiment = create_experiment(session, config)
        run_id = create_run(session, experiment.id).id
    console.print(f"Running [bold]{config.name}[/bold] as {run_id}")
    execute_run(factory, run_id)
    with factory() as session:
        run = session.get(Run, run_id)
        console.print(f"Status: {run.status}, {run.total_trials} trials")
        _print_eval(session, run_id)
    return run_id


@eval_app.command("run")
def eval_run(config_path: Path = typer.Argument(..., exists=True), trials: int = typer.Option(None)) -> None:
    """Run a campaign from a YAML config."""
    data = yaml.safe_load(config_path.read_text())
    if trials:
        data["trials"] = trials
    _run_config(CampaignConfig.model_validate(data))


@eval_app.command("compare")
def eval_compare(run_ids: list[str], as_json: bool = JsonOpt) -> None:
    """Show several runs' measured metrics together."""
    with get_factory()() as session:
        if as_json:
            _emit([{"run_id": e.run_id, "model": e.model_id, "guardrails": e.guardrail_preset, "metrics": e.metrics}
                   for r in run_ids for e in session.scalars(select(EvaluationResult).where(EvaluationResult.run_id == r))])
            return
        for r in run_ids:
            _print_eval(session, r)


@eval_app.command("regrade")
def eval_regrade(run_id: str, reason: str = typer.Option(..., help="Why, recorded in the report.")) -> None:
    """Recompute execution counts from stored tool events, without rerunning any model."""
    from modellab_api.campaigns import regrade_run

    with get_factory()() as session:
        console.print(f"{regrade_run(session, run_id, reason)} trials changed.")


@eval_app.command("judge")
def eval_judge(
    experiment: str = typer.Argument(..., help="Experiment name. Uses its latest completed run."),
    judge_model: str = typer.Option(..., "--model"), limit: int = 60,
    labels: Path = typer.Option(None, help="Optional JSON mapping trial ID to a human true/false label."),
) -> None:
    """Experiment I: compare an LLM judge with deterministic grading and any human labels."""
    from modellab_api.db import Experiment, Trial
    from modellab_evaluation import cohen_kappa, confusion
    from modellab_graders import llm_judge
    from modellab_schemas import ScenarioKind

    human = json.loads(labels.read_text()) if labels else {}
    with get_factory()() as session:
        sync_registry(session)
        adapter = get_adapter(_entry(session, judge_model))
        run = session.scalar(select(Run).join(Experiment, Run.experiment_id == Experiment.id).where(
            Experiment.name == experiment, Run.status == "completed").order_by(Run.finished_at.desc()))
        if run is None:
            console.print(f"[red]No completed run for {experiment}.[/red]")
            raise typer.Exit(1)
        trials = session.scalars(select(Trial).where(Trial.run_id == run.id, Trial.kind == ScenarioKind.attack.value, Trial.status == "completed").order_by(Trial.key)).all()
        step = max(len(trials) // limit, 1)
        scenarios = load_scenarios()
        rows = []
        for t in trials[::step][:limit]:
            transcript = "\n".join(f"{m['role']}: {m['content']}" for m in t.transcript if m["role"] != "system")
            rows.append({"trial": t.id, "deterministic": bool(t.objective_achieved), "judge": llm_judge(adapter, scenarios[t.scenario_id].attacker_objective, transcript)})
    usable = [r for r in rows if r["judge"] is not None]
    result = {"run_id": run.id, "judge_model": judge_model, "sampled": len(rows), "unparseable": len(rows) - len(usable),
              "against_deterministic": confusion((r["deterministic"], r["judge"]) for r in usable).as_dict(),
              "kappa_vs_deterministic": cohen_kappa([r["deterministic"] for r in usable], [r["judge"] for r in usable]),
              "human_labeled": sum(1 for r in usable if r["trial"] in human),
              "kappa_vs_human": cohen_kappa([bool(human[r["trial"]]) for r in usable if r["trial"] in human], [r["judge"] for r in usable if r["trial"] in human]) if human else None}
    _emit(result)


@eval_app.command("report")
def eval_report(run_id: str, out: Path = typer.Option(None, help="Directory for JSON, Markdown, and CSV.")) -> None:
    with get_factory()() as session:
        report = build_report(session, run_id)
        out = out or repo_root() / "var" / "reports"
        for path in write_report_files(report.body, report.markdown, out):
            console.print(str(path))


@train_app.command("classifier")
def train_classifier(kind: str = typer.Option("tfidf-logreg", help="tfidf-logreg or encoder-logreg"), epochs: int = 50, seed: int = 7, as_json: bool = JsonOpt) -> None:
    """Train an injection classifier and evaluate it on held-out templates."""
    from modellab_api.db import Artifact, TrainingJob, now
    from modellab_training import train_baseline, train_encoder

    metrics = train_baseline(epochs=epochs, seed=seed) if kind == "tfidf-logreg" else train_encoder(seed=seed)
    with get_factory()() as session:
        job = TrainingJob(kind=kind, status="completed", config={"epochs": epochs, "seed": seed}, metrics=metrics, finished_at=now())
        if path := metrics.get("artifact_path"):
            artifact = Artifact(kind="classifier", path=path, sha256=metrics["artifact_sha256"], meta={"dataset": metrics["dataset"]["version"]})
            session.add(artifact)
            session.flush()
            job.artifact_id = artifact.id
        session.add(job)
        session.commit()
    if as_json:
        _emit(metrics)
        return
    c = metrics["test_confusion"]
    console.print(f"Held-out test: TP={c['tp']} FP={c['fp']} TN={c['tn']} FN={c['fn']}, precision={c['precision']}, recall={c['recall']}, F1={c['f1']}")
    console.print(f"Leakage checks: {metrics.get('leakage_checks')}")
    console.print(f"Artifact: {metrics.get('artifact_path')}")


@app.command()
def demo() -> None:
    """Run the deterministic demo. It needs no weights and writes a fixture-labeled report."""
    config = CampaignConfig.model_validate(yaml.safe_load((repo_root() / "configs/experiments/demo.yaml").read_text()))
    run_id = _run_config(config)
    with get_factory()() as session:
        report = build_report(session, run_id)
        paths = write_report_files(report.body, report.markdown, repo_root() / "var" / "reports")
    metrics = {(e["model_id"], e["guardrail_preset"]): e["metrics"] for e in report.body["evaluations"]}

    def line(preset: str) -> str:
        m = metrics[("mock-obedient", preset)]
        attack, legit = m["attack_success"], m["legit_task_success"]
        return f"{preset:<12} attacks won {attack['k']}/{attack['n']}, legitimate tasks passed {legit['k']}/{legit['n']}"

    console.print("\n[bold]What this shows[/bold] for an agent that obeys any instruction it reads:")
    for preset in ("none", "tool_policy", "layered"):
        console.print(f"  {line(preset)}")
    console.print("\n[yellow]These are fixture results. They prove the pipeline works and say nothing about any real model.[/yellow]")
    console.print(f"Full report: {paths[1]}")
    console.print("Explore it in the dashboard with: make dev")


@app.command()
def test(args: list[str] = typer.Argument(None)) -> None:
    """Run the test suite."""
    raise typer.Exit(subprocess.call([sys.executable, "-m", "pytest", *(args or [])]))


@app.command()
def api(port: int = 8100, host: str = typer.Option("127.0.0.1", help="Loopback by default. See docs/threat-model.md.")) -> None:
    """Start the REST API."""
    import uvicorn

    if host not in ("127.0.0.1", "::1", "localhost"):
        console.print(f"[yellow]Warning: binding to {host} exposes this API beyond this machine.[/yellow]")
    uvicorn.run("modellab_api.main:app", host=host, port=port)


