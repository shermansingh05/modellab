import os
import time

import pytest
from sqlalchemy import inspect, select

from modellab_api.campaigns import build_report, compute_evaluations, create_experiment, create_run, execute_run
from modellab_api.db import Run, ToolEventRow, Trial, get_factory, make_engine
from modellab_schemas import CampaignConfig

SMALL = {"defenders": ["mock-obedient"], "guardrails": ["none", "tool_policy"], "scenarios": ["pi-doc-exfil-slack", "ctl-doc-summary"]}


def wait(client, run_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/runs/{run_id}").json()
        if body["status"] in ("completed", "failed", "cancelled"):
            return body
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_migrations_create_required_tables(factory):
    names = set(inspect(factory.kw["bind"]).get_table_names())
    assert names >= {"models", "model_revisions", "experiments", "scenario_suites", "scenario_versions", "campaign_configs", "runs", "trials",
                     "generated_payloads", "inference_events", "tool_events", "guardrail_decisions", "evaluation_results", "training_jobs", "artifacts",
                     "research_reports"}


def test_privileged_routes_require_token(client):
    assert client.post("/api/experiments", json={}).status_code == 401
    assert client.post("/api/inference", json={}, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_privileged_routes_close_without_configured_token(client, monkeypatch):
    monkeypatch.delenv("MODELLAB_ADMIN_TOKEN")
    assert client.post("/api/experiments", json={}).status_code == 503


def test_registry_routes(client, auth):
    listed = client.get("/api/models").json()
    assert {"mock-obedient", "qwen3-8b-ollama"} <= {m["id"] for m in listed["items"]}
    assert client.get("/api/models?limit=1").json()["limit"] == 1 and len(client.get("/api/models?limit=1").json()["items"]) == 1
    assert client.get("/api/models?limit=99999").status_code == 422
    assert client.get("/api/models/nope").status_code == 404
    assert client.get("/api/models/mock-obedient/health").json()["ok"] is True
    entry = {"id": "mock-extra", "display_name": "E", "family": "fixture", "backend": "mock", "variant": "fixture", "backend_model": "mock-cautious"}
    assert client.post("/api/models", json=entry, headers=auth).status_code == 201
    assert client.post("/api/models", json=entry, headers=auth).status_code == 409
    assert client.post("/api/models", json={**entry, "id": "x2", "trust_remote_code": True}, headers=auth).status_code == 422


def test_inference_route_records_history(client, auth):
    r = client.post("/api/inference", json={"model_id": "mock-cautious", "messages": [{"role": "user", "content": "hello"}]}, headers=auth)
    assert r.status_code == 200 and r.json()["prompt_tokens"] == 1
    assert client.get("/api/models/mock-cautious/history").json()["total"] >= 1


def test_catalog_routes(client):
    assert client.get("/api/scenarios").json()["total"] >= 40
    assert client.get("/api/scenarios?kind=refusal").json()["total"] == 12
    presets = {g["preset"]: g for g in client.get("/api/guardrails").json()["items"]}
    assert "layered" in presets and any(g["deterministic"] for g in presets["layered"]["guardrails"])


def test_bad_experiment_is_rejected(client, auth):
    bad = {"name": "x", "defenders": ["ghost"]}
    assert client.post("/api/experiments", json=bad, headers=auth).status_code == 422
    assert client.post("/api/experiments", json={"name": "x", "defenders": ["mock-obedient"], "guardrails": ["nope"]}, headers=auth).status_code == 422
    assert client.post("/api/experiments", json={"name": "x", "defenders": []}, headers=auth).status_code == 422


def test_async_job_lifecycle_and_traces(client, auth):
    exp = client.post("/api/experiments", json={"name": "life", **SMALL}, headers=auth).json()
    started = client.post(f"/api/experiments/{exp['id']}/run", headers=auth)
    assert started.status_code == 202
    run = wait(client, started.json()["id"])
    assert run["status"] == "completed" and run["total_trials"] == 4
    assert run["provenance"]["scenario_manifest_hash"] and run["provenance"]["hardware"]
    traces = client.get(f"/api/runs/{run['id']}/traces?guardrail=tool_policy&scenario=pi-doc").json()["items"]
    assert len(traces) == 1
    denied = [e for e in traces[0]["tool_events"] if e["denied_by"]]
    assert denied and denied[0]["tool"] == "slack.send" and denied[0]["executed"] is False
    assert any(d["reason_code"] == "prohibited_operation" for d in traces[0]["guardrail_decisions"])
    assert traces[0]["inference_events"]
    assert client.get(f"/api/runs/{run['id']}/traces?outcome=compromised").json()["total"] == 1
    assert client.post(f"/api/runs/{run['id']}/cancel", headers=auth).status_code == 409


def test_sse_stream_reports_persisted_trials(client, auth):
    exp = client.post("/api/experiments", json={"name": "sse", **SMALL}, headers=auth).json()
    run = client.post(f"/api/experiments/{exp['id']}/run", headers=auth).json()
    wait(client, run["id"])
    with client.stream("GET", f"/api/runs/{run['id']}/events") as stream:
        text = "".join(stream.iter_text())
    assert text.count('"type": "trial"') == 4 and '"status": "completed"' in text


def test_cancel_and_resume_skip_finished_trials():
    factory = get_factory()
    config = CampaignConfig(name="resume", defenders=["mock-obedient"], guardrails=["none"], scenarios=["pi-doc-exfil-slack", "ctl-doc-summary", "ctl-sql-count"])
    with factory() as s:
        run_id = create_run(s, create_experiment(s, config).id).id
        s.get(Run, run_id).cancel_requested = True
        s.commit()
    execute_run(factory, run_id)
    with factory() as s:
        assert s.get(Run, run_id).status == "cancelled"
        s.get(Run, run_id).cancel_requested = False
        s.commit()
    execute_run(factory, run_id)
    with factory() as s:
        assert s.get(Run, run_id).status == "completed"
        first = {t.key: t.id for t in s.scalars(select(Trial).where(Trial.run_id == run_id))}
        assert len(first) == 3
    execute_run(factory, run_id)  # A third pass has nothing left to do, so trial rows stay the same.
    with factory() as s:
        assert {t.key: t.id for t in s.scalars(select(Trial).where(Trial.run_id == run_id))} == first


def test_traces_store_no_raw_credentials():
    factory = get_factory()
    config = CampaignConfig(name="redact", defenders=["mock-obedient"], guardrails=["none"], scenarios=["pi-doc-steal-creds", "tm-write-credential", "rag-acl-restricted"])
    with factory() as s:
        run_id = create_run(s, create_experiment(s, config).id).id
    execute_run(factory, run_id)
    with factory() as s:
        for t in s.scalars(select(Trial).where(Trial.run_id == run_id)):
            assert "SYNTH-" not in (t.answer or "") and "SYNTH-" not in str(t.transcript)
            for e in s.scalars(select(ToolEventRow).where(ToolEventRow.trial_id == t.id)):
                assert "SYNTH-" not in (e.result or "") and "SYNTH-" not in str(e.args)


def test_metrics_recompute_from_records():
    factory = get_factory()
    config = CampaignConfig(name="recompute", defenders=["mock-obedient"], guardrails=["none"], scenarios=["pi-doc-exfil-slack"])
    with factory() as s:
        run_id = create_run(s, create_experiment(s, config).id).id
    execute_run(factory, run_id)
    with factory() as s:
        first = compute_evaluations(s, run_id)[0].metrics
        assert compute_evaluations(s, run_id)[0].metrics == first and first["attack_success"]["k"] == 1


def test_report_has_provenance_and_fixture_warning():
    factory = get_factory()
    config = CampaignConfig(name="report", defenders=["mock-cautious"], guardrails=["layered"], scenarios=["pi-doc-exfil-slack"])
    with factory() as s:
        run_id = create_run(s, create_experiment(s, config).id).id
    execute_run(factory, run_id)
    with factory() as s:
        report = build_report(s, run_id)
    assert report.body["fixture_only"] is True and "says nothing about any real model" in report.markdown
    prov = report.body["provenance"]
    for key in ("git_commit", "models", "scenario_manifest_hash", "guardrail_config_hashes", "decoding", "hardware", "trial_count_per_cell"):
        assert key in prov
    assert "Measurement limitations" in report.markdown and "95% CI" in report.markdown


def test_generated_payload_campaign():
    factory = get_factory()
    config = CampaignConfig(name="gen", defenders=["mock-obedient"], guardrails=["none"], scenarios=["pi-doc-exfil-slack"], attack_strategy="template", attack_budget=3)
    with factory() as s:
        run_id = create_run(s, create_experiment(s, config).id).id
    execute_run(factory, run_id)
    with factory() as s:
        trials = list(s.scalars(select(Trial).where(Trial.run_id == run_id)))
        assert len(trials) >= 2 and all(t.payload_id for t in trials)


def test_training_job_route(client, auth):
    job = client.post("/api/training/jobs", json={"epochs": 3}, headers=auth).json()
    for _ in range(200):
        body = client.get(f"/api/training/jobs/{job['id']}").json()
        if body["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert body["status"] == "completed" and body["artifact_id"] and "test_confusion" in body["metrics"]


@pytest.mark.postgres
@pytest.mark.skipif(not os.environ.get("MODELLAB_TEST_POSTGRES_URL"), reason="set MODELLAB_TEST_POSTGRES_URL")
def test_postgres_runs_a_campaign():
    url = os.environ["MODELLAB_TEST_POSTGRES_URL"]
    factory = get_factory(url)
    assert "trials" in inspect(make_engine(url)).get_table_names()
    config = CampaignConfig(name="pg", **SMALL)
    with factory() as s:
        run_id = create_run(s, create_experiment(s, config).id).id
    execute_run(factory, run_id)
    with factory() as s:
        assert s.get(Run, run_id).status == "completed"
        assert build_report(s, run_id).body["evaluations"]


@pytest.mark.ollama
@pytest.mark.skipif(not os.environ.get("MODELLAB_TEST_OLLAMA"), reason="set MODELLAB_TEST_OLLAMA=1 with Ollama running")
def test_real_ollama_inference(mocks):
    from modellab_adapters import get_adapter
    from modellab_experiments.scenarios import load_model_configs
    from modellab_schemas import GenerationConfig, Message

    entry = next(m for m in load_model_configs() if m.id == "qwen3-8b-ollama")
    r = get_adapter(entry).generate([Message(role="user", content="Say OK.")], GenerationConfig(max_tokens=20))
    assert r.error is None and r.text and r.completion_tokens and r.backend_version


def test_only_silent_runs_are_marked_interrupted():
    from datetime import timedelta

    from modellab_api.campaigns import mark_interrupted
    from modellab_api.db import now

    factory = get_factory()
    config = CampaignConfig(name="stale", defenders=["mock-obedient"], scenarios=["ctl-doc-summary"])
    with factory() as s:
        experiment = create_experiment(s, config)
        live, dead = create_run(s, experiment.id), create_run(s, experiment.id)
        live.status, live.started_at = "running", now()
        dead.status, dead.started_at = "running", now() - timedelta(hours=2)
        s.commit()
        live_id, dead_id = live.id, dead.id
    mark_interrupted(factory)
    with factory() as s:
        assert s.get(Run, live_id).status == "running" and s.get(Run, dead_id).status == "interrupted"
        s.get(Run, live_id).status = "completed"
        s.commit()


def test_unknown_hosts_are_rejected(client):
    assert client.get("/api/health", headers={"Host": "evil.example.test"}).status_code == 400
    assert client.get("/api/health").status_code == 200


def test_reading_a_report_twice_does_not_pile_up_rows():
    from modellab_api.db import ResearchReport

    factory = get_factory()
    config = CampaignConfig(name="once", defenders=["mock-cautious"], guardrails=["none"], scenarios=["ctl-doc-summary"])
    with factory() as s:
        run_id = create_run(s, create_experiment(s, config).id).id
    execute_run(factory, run_id)
    with factory() as s:
        build_report(s, run_id)
        build_report(s, run_id)
        assert len(list(s.scalars(select(ResearchReport).where(ResearchReport.run_id == run_id)))) == 1


def test_disallowed_outputs_are_not_stored(monkeypatch):
    monkeypatch.delenv("MODELLAB_STORE_DISALLOWED_OUTPUT", raising=False)
    factory = get_factory()
    config = CampaignConfig(name="withhold", defenders=["mock-obedient"], guardrails=["none"], scenarios=["ref-disallowed-fraud"])
    with factory() as s:
        run_id = create_run(s, create_experiment(s, config).id).id
    execute_run(factory, run_id)
    with factory() as s:
        t = s.scalar(select(Trial).where(Trial.run_id == run_id))
        assert "withheld" in t.answer and all("withheld" in m["content"] for m in t.transcript if m["role"] == "assistant")
