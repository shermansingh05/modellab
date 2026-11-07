# Architecture

ModelLab keeps four roles apart. The attacker only produces text. The defender only proposes actions. The tool broker decides what runs. The grader reads what happened.

```
attacker (template or model)        registry (pinned models)
        | candidate text                     |
        v                                    v
synthetic environment <---- broker <---- defender model
  docs, chat, repo, SQL,      |  ^            (proposes tool calls as JSON)
  MCP server, RAG             |  |
        |                guardrails: input, retrieved, tool, output
        | audit events
        v
deterministic grader --> metrics (counts, denominators, intervals) --> report
```

| Area | Location |
|---|---|
| Schemas | `packages/schemas` |
| Model adapters: mock, Ollama, Transformers, vLLM | `packages/model-adapters` |
| Guardrails | `packages/guardrails` |
| Graders and LLM judge | `packages/graders` |
| Inference recording | `services/inference` |
| Scenarios, agent loop, attacker | `services/experiments` |
| Synthetic environment | `services/sandbox` |
| Metrics and reports | `services/evaluation` |
| Classifier studio | `services/training` |
| Redaction and tracing | `services/observability` |
| API, CLI, persistence, campaign runner | `apps/api` |
| Dashboard | `apps/web` |

## Decisions

- **SQLite by default, PostgreSQL when shared.** A new developer can run the demo with no services. One Alembic history covers both, and CI tests both.
- **In-process worker by default, Dramatiq when `REDIS_URL` is set.** The Dramatiq path is implemented but hasn't been run: see `limitations.md`.
- **Metrics are recomputed from trial records.** Evaluation rows are derived data, so a report can't drift from its evidence.
- **Trials have stable keys,** built from scenario version, model, guardrails, trial index, and payload. Cancelled or interrupted runs resume by skipping finished keys.
- **A text tool protocol.** Defenders reply with JSON, so every backend behaves the same way, at the cost of not testing native function calling.
- **Classifiers are stored as JSON,** never pickles, so loading an artifact can't run code.
