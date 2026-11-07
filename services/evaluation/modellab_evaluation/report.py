"""Research reports. Every number comes from persisted evaluation records."""
from __future__ import annotations

import csv
import io

LIMITATIONS = [
    "Trials use synthetic fixtures and a text-based tool protocol. Results may not transfer to other agents or real tools.",
    "The refusal detector is a phrase matcher. It misses soft refusals and can misread discussion of refusals.",
    "Ollama serves its own GGUF packaging, so weights can differ from the pinned Hugging Face revision. Compare artifact digests.",
    "Seeded generation can still vary across hardware and backend versions. Repeated trials show variance only when trials > 1.",
    "Wilson intervals treat trials as independent. Trials on the same scenario are correlated, so true uncertainty is larger.",
]


def _fmt(p: dict | None) -> str:
    if not p or p.get("n", 0) == 0:
        return "n/a (n=0)"
    low, high = p["ci95"]
    return f"{p['k']}/{p['n']} = {p['rate']:.1%} (95% CI {low:.1%}-{high:.1%})"


def build_markdown(body: dict) -> str:
    run, prov = body["run"], body["provenance"]
    lines = [f"# ModelLab report: {body['experiment']['name']}", "", f"Run `{run['id']}`, status **{run['status']}**.", ""]
    if body["fixture_only"]:
        lines += ["> **Fixture data.** This run used deterministic mock fixtures. It validates the pipeline and says nothing about any real model.", ""]
    lines += ["## Results", "", "| Model | Guardrails | Attack success | Legitimate task success | Unauthorized executions | False positive trials |", "|---|---|---|---|---|---|"]
    for e in body["evaluations"]:
        m = e["metrics"]
        lines.append(f"| {e['model_id']} | {e['guardrail_preset']} | {_fmt(m['attack_success'])} | {_fmt(m['legit_task_success'])} | "
                     f"{_fmt(m['unauthorized_execution_rate'])} | {_fmt(m['false_positive_trials'])} |")
    labeled = [e for e in body["evaluations"] if e["metrics"]["refusal_by_label"]]
    if labeled:
        lines += ["", "## Refusal rate by request label", "", "Refusal is measured apart from correctness, and neither result alone shows a security outcome.", "",
                  "| Model | Harmless | Ambiguous | Disallowed |", "|---|---|---|---|"]
        for e in labeled:
            r = e["metrics"]["refusal_by_label"]
            lines.append(f"| {e['model_id']} | {_fmt(r.get('harmless'))} | {_fmt(r.get('ambiguous'))} | {_fmt(r.get('disallowed'))} |")
    lines += ["", "## Performance", "", "| Model | Guardrails | Median trial ms | p95 trial ms | Median tokens per trial | Median tokens/s | Peak GPU MB | Errored |", "|---|---|---|---|---|---|---|---|"]
    for e in body["evaluations"]:
        m = e["metrics"]
        num = lambda v: "n/a" if v is None else f"{v:.0f}"  # noqa: E731
        lines.append(f"| {e['model_id']} | {e['guardrail_preset']} | {num(m['latency_ms']['median'])} | {num(m['latency_ms']['p95'])} | "
                     f"{num(m['tokens_per_trial']['median'])} | {num(m['tokens_per_s']['median'])} | {num(m['gpu_memory_mb_peak'])} | {m['trials']['errored']} |")
    lines += ["", "## Provenance", "", f"- Git commit: `{prov.get('git_commit')}`", f"- Scenario manifest: `{prov.get('scenario_manifest_hash')}`",
              f"- Dataset version: {prov.get('dataset_version') or 'none used'}", f"- Decoding: `{prov.get('decoding')}`",
              f"- Seed base: {prov.get('base_seed')}, trials per cell: {prov.get('trial_count_per_cell')}", f"- Hardware: `{prov.get('hardware')}`",
              f"- Guardrail config hashes: `{prov.get('guardrail_config_hashes')}`", f"- Started: {run.get('started_at')}, finished: {run.get('finished_at')}", "", "### Models", ""]
    for mid, info in prov.get("models", {}).items():
        lines.append(f"- **{mid}**: `{info}`")
    lines += ["", "## Measurement limitations", ""] + [f"- {x}" for x in LIMITATIONS]
    if body.get("sample_traces"):
        lines += ["", "## Sanitized sample traces", ""]
        for t in body["sample_traces"]:
            lines += [f"### {t['scenario_id']} / {t['model_id']} / {t['guardrail_preset']}", "",
                      f"Objective achieved: **{t['objective_achieved']}**, legitimate task: **{t['legit_success']}**", ""]
            lines += [f"- Tool `{e['tool']}`: executed={e['executed']}, denied_by={e['denied_by']}" for e in t["tool_events"]]
            lines.append("")
    return "\n".join(lines) + "\n"


def to_csv(body: dict) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["model", "guardrails", "metric", "k", "n", "rate", "ci95_low", "ci95_high"])
    for e in body["evaluations"]:
        for name in ("attack_success", "legit_task_success", "benign_task_success", "guardrail_block_rate",
                     "unauthorized_attempt_rate", "unauthorized_execution_rate", "false_positive_trials"):
            p = e["metrics"][name]
            ci = p["ci95"] or [None, None]
            writer.writerow([e["model_id"], e["guardrail_preset"], name, p["k"], p["n"], p["rate"], ci[0], ci[1]])
    return buffer.getvalue()
