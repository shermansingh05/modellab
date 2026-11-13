"""The CLI is the first thing people run, so it's tested through its real entry points."""
import json

import pytest
from typer.testing import CliRunner

from modellab_api.cli import app

runner = CliRunner()


def run(*args):
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_doctor_reports_machine_and_models():
    data = json.loads(run("doctor", "--json"))
    assert data["tools"]["git"] is True and data["models"]["mock-obedient"]["ok"] is True
    assert "test-token" not in json.dumps(data)


def test_models_list_and_inspect():
    assert {"mock-obedient", "qwen3-8b-ollama"} <= {m["id"] for m in json.loads(run("models", "list", "--json"))}
    assert json.loads(run("models", "inspect", "mock-cautious"))["health"]["ok"] is True
    assert runner.invoke(app, ["models", "inspect", "ghost"]).exit_code == 1


def test_scenarios_list():
    assert len(json.loads(run("scenarios", "list", "--json"))) >= 40
    assert "manifest" in run("scenarios", "list")


def test_infer_records_metrics():
    data = json.loads(run("infer", "mock-cautious", "hello there", "--json"))
    assert data["prompt_tokens"] == 2 and data["error"] is None


def test_infer_reports_a_backend_failure_cleanly(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9")
    result = runner.invoke(app, ["infer", "qwen3-8b-ollama", "hi"])
    assert result.exit_code == 1 and "Traceback" not in result.output


def test_remote_inference_host_is_refused_without_a_traceback(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "https://example.test")
    result = runner.invoke(app, ["infer", "qwen3-8b-ollama", "hi"])
    assert result.exit_code != 0 and isinstance(result.exception, (ValueError, SystemExit))


def test_demo_explains_itself():
    output = " ".join(run("demo").split())  # Rich wraps long lines.
    assert "What this shows" in output and "attacks won 0/20" in output and "say nothing about any real model" in output


def test_eval_run_report_and_compare(tmp_path):
    config = tmp_path / "c.yaml"
    config.write_text("name: cli\ndefenders: [mock-cautious]\nguardrails: [none]\nscenarios: [ctl-doc-summary]\n")
    output = run("eval", "run", str(config))
    run_id = next(w for w in output.split() if w.startswith("run_"))
    assert "modellab eval report" in " ".join(output.split())  # Rich wraps long lines.
    assert json.loads(run("eval", "compare", run_id, "--json"))[0]["guardrails"] == "none"
    report_dir = tmp_path / "out"
    run("eval", "report", run_id, "--out", str(report_dir))
    assert sorted(p.suffix for p in report_dir.iterdir()) == [".csv", ".json", ".md"]


def test_eval_run_rejects_unknown_model(tmp_path):
    config = tmp_path / "c.yaml"
    config.write_text("name: bad\ndefenders: [ghost]\n")
    assert runner.invoke(app, ["eval", "run", str(config)]).exit_code != 0


def test_train_classifier():
    data = json.loads(run("train", "classifier", "--epochs", "3", "--json"))
    assert data["test_confusion"]["tp"] >= 0 and not data["artifact_path"].startswith("/")


@pytest.mark.parametrize("command", [["--help"], ["models", "--help"], ["eval", "--help"], ["train", "--help"]])
def test_help(command):
    assert "Usage" in run(*command)
