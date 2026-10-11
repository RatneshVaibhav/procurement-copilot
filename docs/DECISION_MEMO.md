# Architecture Decision Memo

## Decision
I would ship **A, the single bounded agent**, on top of the deterministic rules.

Before any LLM run, I committed a rule (`evals/DECISION_RULE.md`): B ships only if it passes at least 2 more golden cases than A, or fixes a safety failure A has, within 2× A's latency. On all 23 cases A passed 21 and B 18, with no safety failures. A second, stronger model gave the same answer.

## Evidence
Same cases for both, one model per comparison, strict scoring (over-escalating fails). Main eval: Gemini `gemini-3.5-flash-lite` (`evals/results/summary.md`):

| Metric | A | B | Rules-only |
|---|---:|---:|---:|
| Golden cases passed | 21/23 | 18/23 | 20/23 |
| Injection, fault cases | 3/3, 2/2 | 2/3, 2/2 | 3/3, 1/2 |
| Same decision in 3 trials (6 cases) | 4/6 | 3/6 | n/a |
| Avg active latency (ms) | 6791.3 | 8286.1 | 63.9 |
| Avg LLM / tool calls | 3.3 / 5.3 | 3.9 / 6.2 | 0 / 5 |
| Held-out cases, first trial | 4/5 | 4/5 | 2/5 |

Case by case, A never failed a golden case that rules-only passed; B failed three (G-04, G-10, G-16). On qwen (`evals/results_qwen/summary.md`) the free token cap allowed 10 paired cases: A passed 9, B 7.

On five held-out cases written after freezing the prompts (`evals/results_heldout/`), both agents beat the rules; B caught the existing-tool and injection cases in all three trials, A in one and two.

## Trade-offs
Both share one rules engine; the AI can add a review but never remove one. B's reviewer double-checks the evidence, but its analyst fell back to rules in 7 runs outside the outage case. Its readier "an existing tool covers this" found a held-out case, but also told reviewers to reuse a tool when the request needed specialist review or a new purchase (G-16; G-04 and G-07 on qwen). A's misses are safer: it routes for approval with the overlap flag visible.

The model matters more than the architecture: with qwen, A catches a licensed tool already covering the need (G-08), which rules can't; Flash-Lite manages it once in three trials.

## Risks / limitations
The main model is small and free; qwen covered only part of the cases. Neither agent adds Security for personal data only implied by the text (G-23 and H-04 fail everywhere). Two golden requests shaped the overlap prompt; hence the held-out set. Before production I'd want repeated trials on a stronger model and a deterministic personal-data check.

## Why this is the right MVP
Safety comes from code, not the number of agents: approvals, flags and missing information are deterministic, a human makes every decision, and no tool can approve, buy or notify anyone. One bounded agent adds the judgement the rules can't, at the lowest cost. B's extra stage found more on held-out cases but failed more often and, when wrong, pointed reviewers at the wrong tool.
