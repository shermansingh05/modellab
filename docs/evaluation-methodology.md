# Evaluation methodology

## Definitions

- **Attack success:** the attacker's objective actually happened in the target environment, divided by valid attack trials that completed. A model claiming it did something counts for nothing.
- **Unauthorized attempt:** the model requested a prohibited tool call. **Unauthorized execution:** that call actually ran. They're counted separately.
- **Blocked attempt:** a prohibited call stopped before execution.
- **False positive:** a permitted action or control task that a guardrail denied.
- **Legitimate task success:** the scenario's utility criteria held, measured on attack and control scenarios.
- **Refusal rate:** a phrase detector's result by request label, reported apart from correctness.

Errored trials are excluded from rates and reported as a count.

## Grading

Authorization and tool outcomes are graded by deterministic predicates over audit events. The optional LLM judge never overrides them. `modellab eval judge` measures its agreement with deterministic outcomes and any human labels (Experiment I).

## Uncertainty

Proportions are published as k/n with 95% Wilson intervals. These intervals assume independent trials, but repeated trials of one scenario are correlated, so they understate real uncertainty. Run-to-run variance is reported only when a cell has more than one trial.

## Classifier evaluation

Whole templates are held out, so the test set measures unseen phrasing. Regularization is picked on validation loss, and the test split is never used for tuning. Near-duplicate and group-overlap checks are reported with results.

## Experiment families

| Family | Status |
|---|---|
| A Refusal behavior | Implemented and run on real models |
| B Indirect prompt injection | Implemented and run on real models |
| C Tool authorization | Implemented and run on real models |
| D MCP tool content | Implemented and run on real models |
| E RAG access control | Implemented and run on real models |
| F Multi-turn persistence | Implemented and run on real models |
| G Quantization comparison | Config provided. Not run: needs a second quantization pulled |
| H Guardrail layers | Implemented and run on the parent model |
| I LLM judge reliability | Implemented and run against deterministic outcomes. No human-labeled sample yet |
| J Cross-model transfer | Implemented and run on a small sample |
