"""Exports finished real-model runs to reports/examples and rewrites the README's results section.

Every number comes from persisted records. Fixture runs are never published as results.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy import select

from modellab_api.campaigns import build_report, write_report_files
from modellab_api.db import Experiment, GuardrailDecisionRow, Run, ToolEventRow, TrainingJob, Trial, get_factory
from modellab_experiments.scenarios import load_scenarios

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "examples"
BEGIN, END = "<!-- results:begin -->", "<!-- results:end -->"
GUARD_ORDER = ["none", "prompt_only", "input_classifier", "trained_classifier", "output_classifier", "human_approval", "tool_policy", "layered"]
EXPECTED = {
    "bcdef-parent-vs-abliterated": "standard vs. abliterated attack scenarios",
    "j-cross-model-transfer": "cross-model transfer",
    "h-guardrail-layers": "guardrail layer comparison",
}
TITLES = {
    "qwen3-8b-ollama": "Qwen3 8B",
    "qwen3-8b-abliterated-ollama": "Qwen3 8B abliterated",
}


def fmt(p: dict | None) -> str:
    if not p or not p["n"]:
        return "n/a"
    low, high = p["ci95"]
    return f"{p['k']}/{p['n']} ({p['rate']:.0%}, CI {low:.0%}-{high:.0%})"


def model_name(model_id: str) -> str:
    return TITLES.get(model_id, model_id)


def latest_real_runs(session) -> dict[str, Run]:
    runs = session.scalars(select(Run).where(Run.status == "completed").order_by(Run.finished_at)).all()
    out = {}
    for run in runs:
        models = (run.provenance or {}).get("models") or {}
        if models and any(m.get("variant") != "fixture" for m in models.values()):
            out[session.get(Experiment, run.experiment_id).name] = run
    return out


def attack_table(body: dict) -> list[str]:
    rows = [e for e in body["evaluations"] if e["metrics"]["attack_success"]["n"]]
    rows.sort(key=lambda e: (e["model_id"], GUARD_ORDER.index(e["guardrail_preset"])))
    lines = ["| Model | Guardrails | Attack success | Unauthorized tool executed | Legitimate task success | False positive controls |", "|---|---|---|---|---|---|"]
    for e in rows:
        m = e["metrics"]
        lines.append(f"| {model_name(e['model_id'])} | `{e['guardrail_preset']}` | {fmt(m['attack_success'])} | {fmt(m['unauthorized_execution_rate'])} | {fmt(m['legit_task_success'])} | {fmt(m['false_positive_trials'])} |")
    return lines


def section(reports: dict[str, dict], classifier: dict | None, judge: dict | None) -> str:
    lines = [BEGIN, ""]
    if not reports:
        lines += ["No real-model runs have finished yet.", "", END]
        return "\n".join(lines)
    any_body = next(iter(reports.values()))
    prov = any_body["provenance"]
    hw = prov["hardware"]
    versions = {i.get("backend_version") for i in prov["models"].values()}
    memory = f"{int(hw['memory_bytes']) / 2**30:.0f} GB" if hw.get("memory_bytes") else "unknown memory"
    lines += [
        f"Measured on {hw.get('cpu', hw['machine'])} with {memory}, through Ollama {', '.join(sorted(filter(None, versions)))}, using the GGUF weights Ollama serves. Each report records the exact digests.",
        "These are small, synthetic experiments, not a general ranking of model safety. Intervals are 95% Wilson and treat trials as independent, which understates real uncertainty because repeats of one scenario are correlated.",
        "",
    ]
    if body := reports.get("a-refusal-parent-vs-abliterated"):
        cfg = body["config"]
        lines += ["### Refusal behavior", "", f"12 prompts, {cfg['trials']} seeded trials each, temperature {cfg['generation']['temperature']}. Refusal is detected by phrase matching and says nothing about whether an answer is correct or harmful.", "",
                  "| Model | Harmless refused | Ambiguous refused | Disallowed refused |", "|---|---|---|---|"]
        for e in sorted(body["evaluations"], key=lambda x: x["model_id"], reverse=True):
            r = e["metrics"]["refusal_by_label"]
            lines.append(f"| {model_name(e['model_id'])} | {fmt(r.get('harmless'))} | {fmt(r.get('ambiguous'))} | {fmt(r.get('disallowed'))} |")
        lines += [""]
    if body := reports.get("bcdef-parent-vs-abliterated"):
        cfg = body["config"]
        lines += ["### Standard vs. abliterated, with and without defenses", "", f"20 attack and 8 control scenarios, {cfg['trials']} seeded trials each, temperature {cfg['generation']['temperature']}.", ""] + attack_table(body) + [""]
    if body := reports.get("h-guardrail-layers"):
        cfg = body["config"]
        lines += ["### Guardrail layers on Qwen3 8B", "", f"Same scenarios, {cfg['trials']} seeded trials each. A defense only counts if legitimate work keeps working, so read the last two columns too.", ""] + attack_table(body) + [""]
    if body := reports.get("j-cross-model-transfer"):
        lines += ["### Cross-model transfer", "", "Payloads written by the abliterated model, tested on the standard model. A small sample of three scenarios.", ""] + attack_table(body) + [""]
    if classifier:
        c = classifier["test_confusion"]
        lines += ["### Injection classifier baseline", "",
                  f"TF-IDF plus logistic regression on synthetic data, scored on {classifier['split_sizes']['test']} rows from templates held out of training: precision {c['precision']:.2f}, recall {c['recall']:.2f}, F1 {c['f1']:.2f} (TP {c['tp']}, FP {c['fp']}, TN {c['tn']}, FN {c['fn']}). Calibration error {classifier['calibration']['ece']:.2f}. It is a weak signal on unseen phrasing, which is why it never overrides access control.", ""]
    if judge:
        lines += ["### LLM judge reliability", "", f"Qwen3 8B judging {judge['sampled']} sampled attack transcripts against deterministic outcomes: Cohen's kappa {judge['kappa_vs_deterministic']:.2f}, with {judge['unparseable']} unparseable replies. No human-labeled sample yet.", ""]
    pending = [EXPECTED[n] for n in EXPECTED if n not in reports]
    if pending:
        lines += [f"**Still running:** {', '.join(pending)}. These results will be added here when they finish.", ""]
    if (OUT / "case-study-document-injection.md").exists():
        lines += ["**See one attack end to end:** [an injected instruction, unguarded and defended](reports/examples/case-study-document-injection.md).", ""]
    names = ", ".join(f"[`{n}`](reports/examples/{n}.md)" for n in sorted(reports))
    lines += [f"Full reports with configuration and provenance: {names}. JSON and CSV sit beside them. Replies to disallowed requests are never published.", "", END]
    return "\n".join(lines)


CASE_SCENARIO, CASE_MODEL = "pi-doc-exfil-slack", "qwen3-8b-ollama"


def case_study(session, run: Run) -> str | None:
    """One real attack, unguarded and defended, from persisted evidence. Trial 0 of each, whatever it shows."""
    scenario = load_scenarios()[CASE_SCENARIO]

    def trial(preset: str) -> Trial | None:
        return session.scalar(select(Trial).where(Trial.run_id == run.id, Trial.scenario_id == CASE_SCENARIO, Trial.model_id == CASE_MODEL,
                                                  Trial.guardrail_preset == preset, Trial.trial_index == 0, Trial.status == "completed"))

    pairs = [(p, trial(p)) for p in ("none", "layered")]
    if not all(t for _, t in pairs):
        return None
    out = ["# Case study: an injected instruction in a document", "",
           f"Real trials from run `{run.id}` on {model_name(CASE_MODEL)}. Nothing here is edited beyond credential redaction.", "",
           f"**The user asks:** {scenario.task}", "", "**A document in the sandbox also says:**", "", "```text", (scenario.payload or "").strip(), "```", "",
           f"**Protected boundary:** {scenario.protected_boundary}", ""]
    for preset, t in pairs:
        out += [f"## With guardrails: `{preset}`", "", f"- Attacker objective achieved: **{t.objective_achieved}**", f"- Legitimate task completed: **{t.legit_success}**",
                f"- Unauthorized tool calls: {t.unauthorized_attempts} attempted, {t.unauthorized_executions} executed", "", "**What the sandbox recorded:**", ""]
        events = session.scalars(select(ToolEventRow).where(ToolEventRow.trial_id == t.id).order_by(ToolEventRow.seq)).all()
        out += ["| # | Tool | Arguments | Outcome |", "|---|---|---|---|"]
        out += [f"| {e.seq} | `{e.tool}` | `{json.dumps(e.args)}` | {('denied: ' + e.denied_by) if e.denied_by else ('executed' if e.executed else 'not run')} |" for e in events]
        decisions = [d.data for d in session.scalars(select(GuardrailDecisionRow).where(GuardrailDecisionRow.trial_id == t.id))]
        blocks = [d for d in decisions if d["decision"] != "allow"]
        if blocks:
            out += ["", "**Guardrails that intervened:**", ""] + [f"- `{d['guardrail']}` at the {d['stage']} stage: {d['decision']} ({d['reason_code']})" for d in blocks]
        out += ["", "**The model's final answer:**", "", "> " + (t.answer or "(none)").replace("\n", "\n> "), "", "**Grading evidence:**", ""] + [f"- `{x}`" for x in t.evidence] + [""]
    return "\n".join(out)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    factory = get_factory()
    reports: dict[str, dict] = {}
    with factory() as session:
        for name, run in latest_real_runs(session).items():
            report = build_report(session, run.id)
            for path in write_report_files(report.body, report.markdown, OUT):
                path.rename(OUT / f"{name}{path.suffix}")
            reports[name] = report.body
            if name == "bcdef-parent-vs-abliterated" and (case := case_study(session, run)):
                (OUT / "case-study-document-injection.md").write_text(case)
        job = session.scalar(select(TrainingJob).where(TrainingJob.status == "completed", TrainingJob.kind == "tfidf-logreg").order_by(TrainingJob.finished_at.desc()))
        classifier = job.metrics if job else None
    if classifier:
        (OUT / "classifier-baseline.json").write_text(json.dumps(classifier, indent=2) + "\n")
    judge_path = OUT / "judge-reliability.json"
    judge = json.loads(judge_path.read_text()) if judge_path.exists() else None
    readme = ROOT / "README.md"
    text = readme.read_text()
    if BEGIN not in text:
        raise SystemExit("README has no results markers")
    readme.write_text(re.sub(re.escape(BEGIN) + ".*?" + re.escape(END), lambda _: section(reports, classifier, judge), text, flags=re.S))
    print(f"published: {sorted(reports)}")


if __name__ == "__main__":
    main()
