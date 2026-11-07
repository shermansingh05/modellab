# ModelLab: local-first AI security research platform

[![CI](https://github.com/shermansingh05/modellab/actions/workflows/ci.yml/badge.svg)](https://github.com/shermansingh05/modellab/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

ModelLab runs reproducible security experiments on open-weight LLMs and sandboxed AI agents. It tests prompt injection, agent tool misuse, MCP tool poisoning, RAG access control, and guardrails, and grades each result on **what actually executed in the sandbox**, not on what the model claims it did.

It's built for security engineers, AI red teams, and researchers evaluating systems they own or are authorized to test. It's an experimental research tool, not a production security control.

## Try it in two minutes

No GPU or model download needed. The demo uses deterministic test fixtures.

```bash
git clone https://github.com/shermansingh05/modellab.git
cd modellab
uv sync
uv run modellab demo
```

Fixture results check that the pipeline works. They say nothing about any real model.

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

### Injection classifier baseline

TF-IDF plus logistic regression on synthetic data, scored on 72 rows from templates held out of training: precision 0.62, recall 0.83, F1 0.71 (TP 30, FP 18, TN 18, FN 6). Calibration error 0.29. It is a weak signal on unseen phrasing, which is why it never overrides access control.

**Still running:** standard vs. abliterated attack scenarios, cross-model transfer, guardrail layer comparison. These results will be added here when they finish.

Full reports with configuration and provenance: [`a-refusal-parent-vs-abliterated`](reports/examples/a-refusal-parent-vs-abliterated.md). JSON and CSV sit beside them. Replies to disallowed requests are never published.

<!-- results:end -->

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

## Run the dashboard

```bash
make setup
make api
```

Then, in a second terminal:

```bash
make web
```

Open http://127.0.0.1:3100. Both services stay on loopback, so keep them that way.

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
- [Threat model](docs/threat-model.md)
- [Evaluation methodology](docs/evaluation-methodology.md)
- [Model safety](docs/model-safety.md)
- [Hardware](docs/hardware.md)
- [Limitations](docs/limitations.md): what's unfinished or untested, including the Transformers and vLLM adapters and LoRA training

## Responsible use

All attacks run against local synthetic fixtures, and there's no feature for targeting external systems. Test only what you own or are authorized to test. Abliterated models are included to measure what safety training contributes, and replies to disallowed requests are stored only as hashes. See [SECURITY.md](SECURITY.md) to report a vulnerability.

## License

[Apache 2.0](LICENSE). Model weights aren't included and carry their publishers' licenses.
