# ModelLab: local-first AI security research platform

[![CI](https://github.com/shermansingh05/modellab/actions/workflows/ci.yml/badge.svg)](https://github.com/shermansingh05/modellab/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

ModelLab runs reproducible security experiments on open-weight LLMs and sandboxed AI agents. It tests prompt injection, agent tool misuse, MCP tool poisoning, RAG access control, and guardrails, and grades each result on **what actually executed in the sandbox**, not on what the model claims it did.

It's built for security engineers, AI red teams, and researchers evaluating systems they own or are authorized to test. It's an experimental research tool, not a production security control.

## Try it in two minutes

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git. No GPU, API key, or model download. The demo uses deterministic test fixtures.

```bash
git clone https://github.com/shermansingh05/modellab.git
cd modellab
uv run modellab demo
```

It runs 20 attacks and 8 legitimate-task controls against each defense, then prints a table like this for an agent that obeys any instruction it reads:

```text
none         attacks won 20/20, legitimate tasks passed 26/26
tool_policy  attacks won 1/20, legitimate tasks passed 26/26
layered      attacks won 0/20, legitimate tasks passed 16/26
```

Those are fixture results. They prove the pipeline works and say nothing about any real model. They also show the tradeoff this project measures: the layered defense stops everything, but withholding whole documents costs utility.

To explore it in the dashboard, you also need Node.js 20 or newer:

```bash
make dev
```

Then open http://127.0.0.1:3100. Everything stays on your machine, and all files land in the ignored `var/` folder.

## Security audit

`make audit` runs the test suite, runs the demo with outbound network blocked at the OS level, and scans the code, dependencies, and Git history. Read the [security audit](docs/AUDIT.md) for results, the vulnerabilities found and fixed, and the remaining risks. It's a self-assessment, not an independent penetration test.

## What you get from a run

- A **results table** for each model and guardrail combination, with counts and confidence intervals
- A **trace of every trial:** each tool call, whether it ran or was denied and by which guardrail, the redacted transcript, and the evidence behind the grade
- **Reports** in Markdown, JSON, and CSV, recording the Git commit, model digests, decoding settings, hardware, and known limitations
- A **dashboard** to run campaigns, watch them live, and inspect traces

![Benchmark Explorer comparing attack success and legitimate task success across models and guardrails, using real results](docs/images/benchmarks.jpg)

![Trace Explorer showing a denied tool call and the guardrail decisions behind it](docs/images/trace.jpg)

## What it measures

Each campaign runs scenarios across models and guardrail configurations, then reports:

- **Attack success:** the attacker's objective actually happened, out of valid attempts
- **Unauthorized attempts and executions,** counted separately
- **Legitimate task success and false positives,** because a defense that breaks real work isn't a win
- **Refusal rate by request label,** kept apart from correctness
- **Latency, tokens, throughput, and GPU memory**

Proportions are published as counts with 95% Wilson intervals. See the [evaluation methodology](docs/evaluation-methodology.md).

## Results

<!-- results:begin -->

Measured on Apple M1 Max with 32 GB, through Ollama 0.40.14, using the GGUF weights Ollama serves. Each report records the exact digests.
These are small, synthetic experiments, not a general ranking of model safety. Intervals are 95% Wilson and treat trials as independent, which understates real uncertainty because repeats of one scenario are correlated.

### Refusal behavior

12 prompts, 3 seeded trials each, temperature 0.7. Refusal is detected by phrase matching and says nothing about whether an answer is correct or harmful.

| Model | Harmless refused | Ambiguous refused | Disallowed refused |
|---|---|---|---|
| Qwen3 8B | 0/12 (0%, CI 0%-24%) | 0/12 (0%, CI 0%-24%) | 10/12 (83%, CI 55%-95%) |
| Qwen3 8B abliterated | 0/12 (0%, CI 0%-24%) | 0/12 (0%, CI 0%-24%) | 0/12 (0%, CI 0%-24%) |

### Standard vs. abliterated, with and without defenses

20 attack and 8 control scenarios, 3 seeded trials each, temperature 0.7.

| Model | Guardrails | Attack success | Unauthorized tool executed | Legitimate task success | False positive controls |
|---|---|---|---|---|---|
| Qwen3 8B abliterated | `none` | 36/60 (60%, CI 47%-71%) | 33/60 (55%, CI 42%-67%) | 60/78 (77%, CI 66%-85%) | 0/24 (0%, CI 0%-14%) |
| Qwen3 8B abliterated | `layered` | 0/60 (0%, CI 0%-6%) | 0/60 (0%, CI 0%-6%) | 43/78 (55%, CI 44%-66%) | 0/24 (0%, CI 0%-14%) |
| Qwen3 8B | `none` | 41/60 (68%, CI 56%-79%) | 34/60 (57%, CI 44%-68%) | 71/78 (91%, CI 83%-96%) | 0/24 (0%, CI 0%-14%) |
| Qwen3 8B | `layered` | 0/60 (0%, CI 0%-6%) | 0/60 (0%, CI 0%-6%) | 46/78 (59%, CI 48%-69%) | 0/24 (0%, CI 0%-14%) |

### Guardrail layers on Qwen3 8B

Same scenarios, 3 seeded trials each. A defense only counts if legitimate work keeps working, so read the last two columns too.

| Model | Guardrails | Attack success | Unauthorized tool executed | Legitimate task success | False positive controls |
|---|---|---|---|---|---|
| Qwen3 8B | `none` | 41/60 (68%, CI 56%-79%) | 34/60 (57%, CI 44%-68%) | 71/78 (91%, CI 83%-96%) | 0/24 (0%, CI 0%-14%) |
| Qwen3 8B | `prompt_only` | 38/60 (63%, CI 51%-74%) | 31/60 (52%, CI 39%-64%) | 73/78 (94%, CI 86%-97%) | 0/24 (0%, CI 0%-14%) |
| Qwen3 8B | `input_classifier` | 22/60 (37%, CI 26%-49%) | 15/60 (25%, CI 16%-37%) | 47/78 (60%, CI 49%-70%) | 0/24 (0%, CI 0%-14%) |
| Qwen3 8B | `trained_classifier` | 12/60 (20%, CI 12%-32%) | 12/60 (20%, CI 12%-32%) | 24/78 (31%, CI 22%-42%) | 15/24 (62%, CI 43%-79%) |
| Qwen3 8B | `output_classifier` | 34/60 (57%, CI 44%-68%) | 34/60 (57%, CI 44%-68%) | 53/78 (68%, CI 57%-77%) | 0/24 (0%, CI 0%-14%) |
| Qwen3 8B | `tool_policy` | 3/60 (5%, CI 2%-14%) | 0/60 (0%, CI 0%-6%) | 63/78 (81%, CI 71%-88%) | 0/24 (0%, CI 0%-14%) |
| Qwen3 8B | `layered` | 0/60 (0%, CI 0%-6%) | 0/60 (0%, CI 0%-6%) | 46/78 (59%, CI 48%-69%) | 0/24 (0%, CI 0%-14%) |

### Cross-model transfer

Payloads written by the abliterated model, tested on the standard model. A small sample of three scenarios.

| Model | Guardrails | Attack success | Unauthorized tool executed | Legitimate task success | False positive controls |
|---|---|---|---|---|---|
| Qwen3 8B | `none` | 1/5 (20%, CI 4%-62%) | 1/5 (20%, CI 4%-62%) | 3/5 (60%, CI 23%-88%) | n/a |

### Injection classifier baseline

TF-IDF plus logistic regression on synthetic data, scored on 72 rows from templates held out of training: precision 0.62, recall 0.83, F1 0.71 (TP 30, FP 18, TN 18, FN 6). Calibration error 0.29. It is a weak signal on unseen phrasing, which is why it never overrides access control.

### LLM judge reliability

Qwen3 8B judging 60 sampled attack transcripts against deterministic outcomes: Cohen's kappa 0.69, with 0 unparseable replies. No human-labeled sample yet.

**See one attack end to end:** [an injected instruction, unguarded and defended](reports/examples/case-study-document-injection.md).

Full reports with configuration and provenance: [`a-refusal-parent-vs-abliterated`](reports/examples/a-refusal-parent-vs-abliterated.md), [`bcdef-parent-vs-abliterated`](reports/examples/bcdef-parent-vs-abliterated.md), [`h-guardrail-layers`](reports/examples/h-guardrail-layers.md), [`j-cross-model-transfer`](reports/examples/j-cross-model-transfer.md). JSON and CSV sit beside them. Replies to disallowed requests are never published.

<!-- results:end -->

## What the results show

On this small, synthetic sample:

1. **Refusal training didn't protect the agent's tools.** The standard model refused 10 of 12 disallowed requests and the abliterated model refused none, yet both acted on injected instructions at similar rates. Unguarded attacks succeeded 41/60 and 36/60 times, and those intervals overlap, so this doesn't show either model is safer against injection.
2. **The abliterated model's lower score isn't a safety win.** It repeatedly called `rag` instead of `rag.search`, so its RAG attacks failed along with the legitimate RAG tasks. Its legitimate task success was also lower: 60/78, against 71/78.
3. **Telling the model to be careful barely helped.** A security instruction in the system prompt moved attack success from 41/60 to 38/60, within the margin of error.
4. **Deterministic tool policy gave the best tradeoff.** It cut attack success to 3/60 and kept legitimate success at 63/78, with no prohibited tool executed. All three remaining wins were one scenario: posting a credential to a channel the agent was allowed to use, which authorization alone can't see.
5. **The trained classifier cost more than it was worth.** It cut attacks to 12/60 but blocked 15 of 24 legitimate control tasks, because it was trained on synthetic data and is weak on unseen phrasing.
6. **Layering stopped everything, at a real cost.** No attack succeeded on either model and no control task was blocked, but legitimate success on attack scenarios suffered, taking the standard model's overall figure from 71/78 to 46/78. A flagged document gets withheld in full, so the agent can't finish its real task. Separating the safe content from the injected content is the next problem worth solving.
7. **An LLM judge isn't a substitute for checking what ran.** Grading 60 transcripts, Qwen3 8B disagreed with the deterministic outcome 9 times (kappa 0.69), including 6 false alarms and 3 missed compromises.

See [limitations](docs/limitations.md) before generalizing from any of this.

## What's included

| Area | Details |
|---|---|
| **Model registry** | Pinned revisions, artifact hashes, and remote code always off |
| **Inference** | Ollama (verified), Transformers and vLLM adapters, and a mock for CI |
| **Scenarios** | 20 attacks, 8 legitimate-task controls, and 12 refusal prompts in versioned YAML |
| **Target sandbox** | Synthetic documents, chat, repository, SQL, MCP server, and RAG, with deterministic audit events |
| **Guardrails** | Input and retrieved-context classifiers, tool-argument validation, deterministic authorization, sensitive-data detection, output policy, and human approval |
| **Attack generation** | Templates, paraphrases, multilingual variants, and an attacker model, with deduplication and budgets |
| **Classifier studio** | CPU-only TF-IDF baseline with held-out templates, calibration, and leakage checks |
| **Interfaces** | REST API, `modellab` CLI, and a Next.js research dashboard |

A classifier can never override a deterministic authorization denial.

## Run real models

You need [Ollama](https://ollama.com) and about 16 GB of unified memory or VRAM. Each model is about 5 GB.

```bash
uv run modellab doctor
uv run modellab models pull qwen3-8b-ollama
uv run modellab eval run configs/experiments/h_guardrail_layers.yaml
```

## Common commands

```bash
uv run modellab scenarios list
uv run modellab infer mock-cautious "Hello"
uv run modellab eval compare <run-id> <run-id>
uv run modellab eval report <run-id>
uv run modellab train classifier
uv run modellab test
```

Many commands accept `--json`.

## Documentation

- [Architecture](docs/architecture.md)
- [Security audit](docs/AUDIT.md)
- [Threat model](docs/threat-model.md)
- [Evaluation methodology](docs/evaluation-methodology.md)
- [Model safety](docs/model-safety.md)
- [Hardware](docs/hardware.md)
- [Limitations](docs/limitations.md): what's unfinished or untested, including the Transformers and vLLM adapters and LoRA training

## Responsible use

All attacks run against local synthetic fixtures, and there's no feature for targeting external systems. Test only what you own or are authorized to test. Abliterated models are included to measure what safety training contributes, and replies to disallowed requests are stored only as hashes. See [SECURITY.md](SECURITY.md) to report a vulnerability.

## License

[Apache 2.0](LICENSE). Model weights aren't included and carry their publishers' licenses.
