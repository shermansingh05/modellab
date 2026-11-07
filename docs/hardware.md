# Hardware

| Setup | What works |
|---|---|
| Any machine, no GPU | Tests, deterministic demo, dashboard, CPU classifier baseline |
| 16 GB or more of unified memory or VRAM | Qwen3 8B through Ollama at Q4_K_M, about 5.2 GB on disk |
| 24 GB or more | Unquantized Qwen3 8B through Transformers, about 16 GB on disk, with the `ml` extra |

`modellab doctor` reports what this machine has.

**Development machine:** Apple M1 Max with 32 GB of unified memory. Real results in `reports/examples` come from this machine through Ollama.

Comparing runs across backends or hardware isn't like-for-like. Quantization, chat templates, and sampling implementations all differ, which is why each report records them.

**PostgreSQL on macOS:** if a Homebrew Postgres 16 cluster exits with "postmaster became multithreaded during startup", start it with `LC_ALL=C`.
