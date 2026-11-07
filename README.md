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

Real-model experiments on Qwen3 8B and its abliterated variant are in progress, so no benchmark numbers are published yet. Measured results will appear here and in [`reports/examples`](reports/examples), with their full provenance.

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

Most list and report commands accept `--json`.

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
