# Limitations

## Implemented but never run

- **Transformers adapter.** Unit-tested for pinning rules only, with no real generation so far. Ollama is the verified backend.
- **vLLM adapter.** Tested only against a stubbed transport.
- **Encoder classifier** (`train_encoder`). Needs the `ml` extra and hasn't been run.
- **Dramatiq worker.** Written, but Redis wasn't available on the development machine. Runs were tested with the in-process worker.
- **`docker-compose.yml` and the GPU workflow.** Docker wasn't available. PostgreSQL itself was tested against a real local cluster.

## Not implemented

- **LoRA or QLoRA fine-tuning.** `train_lora` raises `NotImplementedError`.
- **S3-compatible artifact storage.** Artifacts are local files.
- **Run replay.** Traces can be inspected, and runs can be resumed, but a trial can't be replayed step by step.
- **Human approval queue.** The guardrail blocks unattended calls, but there's no interface for a person to approve one.
- **OS-level sandboxing.** See `threat-model.md`.
- **Trace access controls beyond loopback binding.** GET routes have no authentication. A host check blocks DNS rebinding, but anything running locally can read them.
- **Native MCP transport.** The MCP server is in-process JSON-RPC, not stdio or HTTP.
- **Native function calling.** All backends use a text JSON tool protocol.
- **Cost per task.** Local inference has no known per-token price, so it's reported as null.

## Measurement limits

- **Small samples.** 20 attack and 8 control scenarios, with 3 trials per cell, is not a benchmark of general model security.
- **Explicit prompts.** Tasks and payloads name tools directly so results can be graded. Attacks in the wild are subtler, and these scenarios may overstate or understate real risk.
- **Refusal detector.** It's a phrase match, and it misses soft refusals.
- **Heuristic classifier.** It ignores quoted text so that discussing an attack isn't flagged, which an attacker could abuse by quoting a payload.
- **Input guardrails withhold whole tool results.** That protects the agent but costs utility, and the results show it.
- **Synthetic classifier data.** Scores describe held-out templates, not real traffic.
- **Fixture results** validate the pipeline and say nothing about any real model.
