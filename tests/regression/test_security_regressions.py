"""If one of these fails, a defense got weaker or a control got less usable. Runs on deterministic fixtures."""
import pytest

from modellab_experiments.agent import run_trial
from modellab_guardrails import build_guardrails
from modellab_schemas import GenerationConfig


def trials(scenarios, adapter, preset, kind):
    return {s.id: run_trial(s, adapter, build_guardrails(preset), GenerationConfig()) for s in scenarios.values() if s.kind == kind}


def test_baseline_is_actually_vulnerable(scenarios, mocks):
    """Guards the test harness itself: a defense can't look good if the baseline never fails."""
    results = trials(scenarios, mocks[0], "none", "attack")
    assert all(o.grade.objective_achieved for o in results.values()), [k for k, o in results.items() if not o.grade.objective_achieved]


def test_layered_blocks_every_attack(scenarios, mocks):
    results = trials(scenarios, mocks[0], "layered", "attack")
    assert not [k for k, o in results.items() if o.grade.objective_achieved]
    assert not [k for k, o in results.items() if o.grade.unauthorized_executions]


def test_tool_policy_stops_every_unauthorized_execution(scenarios, mocks):
    results = trials(scenarios, mocks[0], "tool_policy", "attack")
    assert not [k for k, o in results.items() if o.grade.unauthorized_executions]


@pytest.mark.parametrize("preset", ["none", "tool_policy", "layered"])
def test_legitimate_controls_stay_usable(scenarios, mocks, preset):
    results = trials(scenarios, mocks[1], preset, "benign")
    assert not [k for k, o in results.items() if not o.grade.legit_success]
    assert not [k for k, o in results.items() if o.grade.false_positive_denials]


def test_tool_policy_keeps_attack_scenario_utility(scenarios, mocks):
    results = trials(scenarios, mocks[1], "tool_policy", "attack")
    measured = {k: o.grade.legit_success for k, o in results.items() if o.grade.legit_success is not None}
    assert measured and all(measured.values()), measured


def test_known_gap_tool_policy_alone_misses_allowed_channel_credential(scenarios, mocks):
    """A documented limitation: argument-blind authorization lets a credential through an allowed channel."""
    result = run_trial(scenarios["tm-write-credential"], mocks[0], build_guardrails("tool_policy"), GenerationConfig())
    assert result.grade.objective_achieved is True
    layered = run_trial(scenarios["tm-write-credential"], mocks[0], build_guardrails("layered"), GenerationConfig())
    assert layered.grade.objective_achieved is False
