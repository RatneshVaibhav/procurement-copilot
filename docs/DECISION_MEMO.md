# Architecture Decision Memo

## Decision
I would ship **A, the single bounded agent**.

Before any LLM evaluation ran, I committed a rule (`evals/DECISION_RULE.md`): B ships only if it passes at least 2 more golden cases than A, or fixes a safety failure that A has, within 2× A's latency. On the 10 cases both architectures completed, A passed 9 and B passed 7, and neither had a safety failure.

## Evidence
Both architectures ran the same 23 golden cases with the same model (Groq `qwen/qwen3.8-27b`, free tier). Scoring is strict, so over-escalating also fails a case. Numbers from `evals/results/summary.md`:

| Metric | A: bounded agent | B: sequential specialists | Rules-only |
|---|---:|---:|---:|
| Golden cases passed | 11/12 | 7/10 | 20/23 |
| Paired cases passed | 9/10 | 7/10 | n/a |
| AI-only cases (G-08, G-23) | 1/2 | 1/2 | 0/2 |
| Avg active latency (ms) | 7498.0 | 7456.5 | 63.5 |
| Avg LLM / tool calls per run | 2.8 / 5.1 | 3.6 / 5 | 0 / 5 |
| Avg tokens / run | 11526.6 | 13326 | 0 |
| Ungrounded evidence removed | 0 | 5 | n/a |

A daily token cap on the free tier stopped some runs. A completed 12 LLM cases, B 10. The comparison therefore uses the 10 paired cases.

## Trade-offs
Both versions share one rules engine: code computes the approval thresholds, the budget check, vendor-review status, the Security/Privacy/Legal triggers and the injection scan. The AI can add a review but can never remove what code decided.

The AI adds judgement that rules can't, like spotting that a tool we already pay for covers the request (G-08: both agents pass, rules-only fails).

B's reviewer removed evidence items that weren't backed by tool results, which helps trust. But it cost more LLM calls (3.6 vs 2.8 per run) and more tokens (13326 vs 11526.6 per run), and fixed none of A's failures. It also lost G-04 and G-07: both B agents decided an existing product already covered the need, and the reviewer repeated the analyst's mistake.

## Risks / limitations
Coverage is partial and I ran one trial, so the result could shift on the full set. Neither agent reliably adds Security or Privacy when personal data is only implied by the text (G-23 fails for A, B and rules-only). Before production I would run every case several times and add a deterministic personal-data check.

## Why this is the right MVP
Safety here comes from code, not from the number of agents: approvals, flags and missing information are deterministic, a human makes every decision, and no tool can approve, buy or notify anyone. One bounded agent adds the judgement a reviewer needs at the lowest cost; a second agent didn't earn its extra calls.
