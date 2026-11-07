# Threat model

ModelLab is a research tool for one trusted operator on their own machine. It is not a production security appliance.

## In scope

| Threat | Control |
|---|---|
| Hostile content steers the defender | Everything runs in in-memory fixtures with synthetic data. The defender only proposes actions, and the broker decides. |
| Attacker model tampers with the experiment | It returns text only, placed on the scenario's declared surface. It holds no reference to the evaluator, registry, or broker. |
| A classifier approves something policy forbids | Every guardrail runs, and any denial blocks. Deterministic denials can't be overridden. |
| Model repositories run code | `trust_remote_code` can't be set to true in the schema. Transformers models must pin a commit, load safetensors only, and download an allowlist of file patterns. |
| Credentials in traces | Synthetic credentials and common token formats are redacted before they're stored. |
| Harmful output is retained | Replies to disallowed requests are stored as a length and hash unless `MODELLAB_STORE_DISALLOWED_OUTPUT=1`. |
| Remote callers use admin routes | The API binds to loopback. Anything that runs a model or changes state needs a bearer token, and those routes close if no token is configured. |
| Another website drives a local run | The web proxy holds the token, and it rejects non-GET requests unless the Origin matches a loopback Host. |
| Inference reaches a remote host | Adapters refuse non-loopback URLs unless `MODELLAB_ALLOW_REMOTE_INFERENCE=1`. |
| A runaway model | Step, tool-call, token, and wall-clock budgets apply, and runs can be cancelled between steps. |

## Out of scope, and known gaps

- **Sandbox isolation is logical, not enforced by the OS.** Fixtures make no network or filesystem calls because they aren't written to, but no container or seccomp profile enforces that. Running a model's generated code is deliberately not a feature.
- **GET routes are unauthenticated.** They're meant for loopback. Traces are redacted but still sensitive, so don't expose this API.
- **Model weights are trusted once pulled.** Ollama pulls are recorded by digest but not independently verified.
- **Local users.** Anyone with shell access can read `.env` and the database.

Only test systems you own or are explicitly authorized to test.
