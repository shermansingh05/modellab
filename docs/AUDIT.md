# Security audit

**This is a self-assessment by the project's author, done with AI assistance. It is not an independent penetration test or a certification.** Everything below can be reproduced, so please check it yourself.

```bash
git clone https://github.com/shermansingh05/modellab.git && cd modellab
uv sync --frozen && (cd apps/web && npm ci)
make audit
```

## Is it safe to run?

**The deterministic demo is low risk.** It needs no GPU, model download, or services, and it completed with all outbound network blocked by the operating system. It writes only to an ignored `var/` folder inside the repository, plus a temporary database under `make audit`.

**Real-model runs need more thought.** They require installing Ollama and downloading third-party weights, and one of those models has had its safety behavior removed. Get approval before doing that on a corporate device. The sandbox is logical rather than enforced by the OS, so use a dedicated research machine if your policy requires isolation.

| You run | Network | Writes to | Risk notes |
|---|---|---|---|
| `make audit` | Package advisory lookups, plus package downloads on a first install | `.venv`, a temp folder | None beyond installing dependencies |
| `modellab demo` | None | `var/` | Uses fixtures only |
| API and dashboard | Loopback only | `var/` | Admin token lives in `.env`, which is ignored by Git |
| `modellab eval run` with real models | Loopback to Ollama | `var/` | Runs model-generated tool calls against in-memory fixtures only |
| `modellab models pull` | Ollama or Hugging Face | Backend's model store | Third-party weights, 5 GB or more |

## Results

| Check | Result |
|---|---|
| Test suite from a clean clone | 184 passed, 2 skipped (the 2 need live Ollama and Postgres, and passed when run separately) |
| End-to-end smoke test (`make smoke`) | Real API and dashboard processes run a campaign through the proxy, and CI repeats it on every push |
| Demo with outbound network denied by macOS `sandbox-exec` | Passed, after confirming the block stops `curl` |
| Tracked files changed by the demo | None |
| Static analysis (Bandit, medium and above) | No findings |
| Python dependencies, including optional extras (`pip-audit`) | No known vulnerabilities on the audit date |
| Web dependencies (`npm audit`) | No known vulnerabilities on the audit date |
| Secrets in Git history (pattern scan and `detect-secrets`) | None. Flagged items were commit hashes, a fake test key, and a CI-only database password |
| Model weights in Git | None |
| Dynamic code execution in source (`eval`, `exec`, pickle loading, shell commands) | None |

### Live attacks on the running API

| Attempt | Response |
|---|---|
| Start an experiment with no token | 401 |
| Run inference with no token, or the wrong token | 401 |
| Cancel a run with no token | 401 |
| Invalid request with a valid token | 422 |
| Hostile Host header, simulating DNS rebinding | 400 |
| Dashboard proxy: POST from another site's Origin | 403 |
| Dashboard proxy: hostile Host | 403 |
| Dashboard proxy: encoded path traversal | 404 |
| Admin token present in the browser bundle | Not found |

The API, dashboard, and Ollama were all listening on `127.0.0.1` only.

## Vulnerabilities found and fixed

| Severity | Finding | Fix |
|---|---|---|
| **High** | Model-written SQL could create files on the host through `ATTACH DATABASE` and `VACUUM INTO`. No model attempted this in recorded runs. | A SQLite authorizer denies these operations, with regression tests |
| Medium | An endless recursive SQL query could hang a run | Query time limit and row cap |
| Medium | A hostile website could reach the loopback API through DNS rebinding | Host header allowlist |
| Medium | 15 known advisories in the main dependencies, plus some in optional ML packages | Upgraded |
| Low | Malformed tool arguments could crash a run instead of failing one call | Handled, with a test |
| Low | Tool arguments on disallowed requests could store harmful text | Withheld |
| Low | Personal email in commit metadata | History rewritten to a no-reply address before publishing |

Four measurement bugs were also found by auditing real trials. For the first two, all results produced before the fixes were discarded and rerun. The third counted calls to nonexistent tools as unauthorized executions, and it was corrected from stored evidence with `modellab eval regrade`, which is recorded in the affected reports. The fourth only counted denied tool calls as false positives, which hid a classifier blocking 15 of 24 legitimate control tasks, so the metric now counts any intervention on a control task.

Dependency updates aren't merged on CI alone. A Monaco editor update passed CI but pulled in a critical `dompurify` advisory and broke its web workers, so it was reverted. That decision was re-checked on the dates below and still holds.

## Dependency decisions

Pins are exact, so every upgrade is deliberate. These were applied together and verified as a set:

| Upgraded | From | To |
|---|---|---|
| fastapi | 0.162.0 | 0.162.4 |
| pydantic | 2.10.6 | 2.14.3 |
| sqlalchemy | 2.0.37 | 2.1.8 |
| psycopg[binary] | 3.2.4 | 3.3.8 |
| pyyaml | 6.0.2 | 6.0.3 |
| typer | 0.27.3 | 0.29.0 |
| scikit-learn | 1.6.1 | 1.9.1 |
| numpy | 2.2.2 | 2.5.4 |
| datasets | 5.1.0 | 5.2.0 |
| ruff | 0.17.3 | 0.17.4 |

The scikit-learn and NumPy majors matter most, because the published classifier numbers come from them. Retraining on 1.9.1 and NumPy 2.5.4 reproduced the baseline exactly — same confusion matrix (TP=30 FP=18 TN=18 FN=6) and the same artifact SHA-256, `d6e7c322527f…` — so [the classifier baseline](../reports/examples/classifier-baseline.json) still describes the artifact the guardrail loads.

Held back, with reasons:

| Held | Why |
|---|---|
| `monaco-editor` 0.57.0 | Depends on `dompurify` ≤ 3.4.16. Installing it turns `npm audit` from zero findings into one critical DOM-XSS advisory, so the update is a net security regression. |
| `typescript` 7.0.2 | A major release. 5.9.3 is current, type-checks clean, and nothing here needs 7. |
| `dramatiq[redis]` 2.2.1 | A major release on the optional queue path, which has no Redis available on the audit machine and so cannot be exercised. Shipping an untested major on a code path the tests skip would be guessing. |

## Residual risks

- **The sandbox is logical.** Tools only touch in-memory state by design, but no container or seccomp profile enforces that.
- **Read routes have no authentication.** They rely on loopback binding and the Host check, so any local process can read traces.
- **Weights are verified by hashing bytes where that is possible, and the digest says which.** `modellab models verify` checks a model's live digest against the registry pin, and a run refuses to start when an unpinned model's digest has changed since it last ran, when a pin mismatches, or when a pin cannot be checked at all. Transformers digests (`snapshot:`) and loopback Ollama digests (`blobs:`) are hashes of the bytes on disk, so a file edited in place is caught even though every filename and the server's own reported digest stay the same. A remote Ollama falls back to `manifest:`, the server's own word, which detects a swap but attests nothing. vLLM reports nothing, so a check says `unavailable`. Kinds are never compared with each other. None of this is a signature chain back to the publisher.
- **The scans have limits.** Pattern-based secret scanning and static analysis can miss things, and advisory results change over time. Re-run `make audit`.
- **The Linux network-block path in `make audit` hasn't been tested.** It was only run on macOS.
- **Written but not exercised:** the Transformers and vLLM adapters, the Dramatiq worker, and Docker Compose. See [limitations](limitations.md).

See the [threat model](threat-model.md) for the full picture.
