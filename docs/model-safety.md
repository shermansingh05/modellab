# Model safety

This project includes abliterated variants, which are open-weight models with refusal behavior deliberately removed. They exist here to measure what safety training contributes, inside a sandbox, under controlled budgets.

- **Disallowed prompts are deliberately mild.** The categories are limited to fraud and harassment framing. The suite has no weapons, biological, or child-safety prompts, and it shouldn't.
- **Outputs aren't retained.** Replies to disallowed requests are stored only as a length and hash by default, and are never published in reports.
- **Refusal isn't safety.** A low refusal rate shows behavior under one detector, and it doesn't measure how harmful or correct an answer is.
- **No weights in Git.** Weights come from their publishers under their own licenses. Check them before use.
- **Authorized targets only.** Attacks run against local fixtures. There is no feature for targeting external systems.
