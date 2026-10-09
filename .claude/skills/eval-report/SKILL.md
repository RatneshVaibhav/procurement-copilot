---
name: eval-report
description: Draft the README evaluation, comparison and ship-decision sections and the decision memo from committed eval results only.
disable-model-invocation: true
---

1. Read evals/results/summary.json, evals/results/summary.md, evals/results/scenario_walkthroughs.md, evals/results/manual_review.md and evals/DECISION_RULE.md. Do not run any eval and do not recompute numbers from run files.
2. Apply DECISION_RULE.md literally to the numbers and state which clause decided the outcome, even if the answer is "ship A".
3. Draft README sections 7–9 and docs/DECISION_MEMO.md (template: templates/architecture_decision.md, at most 500 words).
4. Every number must appear verbatim in summary.json or summary.md. After the drafts, list each number with its source key (in your reply, not in the memo).
5. State the provider and model, the number of trials, the infra errors excluded, and that rules-only is the "workflow" baseline from the design ladder.
6. Print the memo word count. Put "DRAFT: rewrite in your own voice" at the top of the memo.
