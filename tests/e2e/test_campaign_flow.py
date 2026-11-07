"""The full path a researcher takes, through the public API, with deterministic fixtures."""
import time


def test_register_run_observe_deny_measure_export(client, auth):
    entry = {"id": "e2e-agent", "display_name": "E2E", "family": "fixture", "backend": "mock", "variant": "fixture", "backend_model": "mock-obedient"}
    assert client.post("/api/models", json=entry, headers=auth).status_code in (201, 409)

    suite = ["pi-doc-exfil-slack", "tm-delete-on-request", "ctl-doc-summary"]
    exp = client.post("/api/experiments", json={"name": "e2e", "defenders": ["e2e-agent"], "guardrails": ["none", "layered"], "scenarios": suite}, headers=auth)
    assert exp.status_code == 201
    run_id = client.post(f"/api/experiments/{exp.json()['id']}/run", headers=auth).json()["id"]
    for _ in range(600):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] == "completed":
            break
        time.sleep(0.05)
    assert run["status"] == "completed" and run["total_trials"] == 6

    traces = client.get(f"/api/runs/{run_id}/traces?guardrail=layered&limit=10").json()["items"]
    attack = next(t for t in traces if t["scenario_id"] == "tm-delete-on-request")
    assert attack["objective_achieved"] is False
    assert any(e["tool"] == "docs.delete" and e["denied_by"] and not e["executed"] for e in attack["tool_events"])
    baseline = client.get(f"/api/runs/{run_id}/traces?guardrail=none&scenario=tm-delete").json()["items"][0]
    assert baseline["objective_achieved"] is True and baseline["unauthorized_executions"] == 1

    metrics = {e["guardrail_preset"]: e["metrics"] for e in client.get(f"/api/evaluations?run_id={run_id}").json()["items"]}
    assert metrics["none"]["attack_success"]["k"] == 2 and metrics["none"]["attack_success"]["n"] == 2
    assert metrics["layered"]["attack_success"]["k"] == 0 and metrics["layered"]["benign_task_success"]["k"] == 1

    assert client.get(f"/api/evaluations/{run_id}/report").json()["fixture_only"] is True
    assert "# ModelLab report" in client.get(f"/api/evaluations/{run_id}/report?format=markdown").text
    assert "attack_success" in client.get(f"/api/evaluations/{run_id}/report?format=csv").text
    assert client.get("/api/overview").json()["latest_runs"]
