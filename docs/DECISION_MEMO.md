# Architecture Decision Memo

DRAFT: rewrite in your own voice.

## Decision
Ship **A: the single bounded agent**. The pre-registered rule (`evals/DECISION_RULE.md`) ships B only if it passes at least 2 more golden cases than A, or fixes a safety failure A has, at no more than 2× A's latency. On the 10 cases both architectures completed, A passed 9 and B passed 7, and neither had a safety failure.

## Evidence
Same 23 golden cases, same model for both architectures (Groq `qwen/qwen3.8-27b`, free tier), exact-set scoring that penalises over-escalation. Numbers from `evals/results/summary.md`:

| Metric | A: bounded agent | B: sequential specialists | Rules-only |
|---|---:|---:|---:|
| Golden cases passed | 11/12 | 7/10 | 20/23 |
| Paired cases passed | 9/10 | 7/10 | n/a |
| AI-only cases (G-08, G-23) | 1/2 | 1/2 | 0/2 |
| Avg active latency (ms) | 7498.0 | 7456.5 | 63.5 |
| Avg LLM / tool calls per run | 2.8 / 5.1 | 3.6 / 5 | 0 / 5 |
| Avg tokens / run | 11526.6 | 13326 | 0 |
| Ungrounded evidence removed | 0 | 5 | n/a |

The free-tier daily token cap stopped the run before all cases finished: A completed 12 LLM cases, B 10. The comparison therefore uses the 10 paired cases.

## Trade-offs
Both agents sit on the same deterministic core: code computes thresholds, budget, vendor currency and conflicts, the Security/Privacy/Legal triggers and the injection scan, and the guardrails never let the LLM remove what code decided. The AI adds what rules cannot: recognising that a licensed tool already covers the need (G-08 passed with both agents, failed with rules only). B's independent reviewer caught 5 evidence items that were not grounded in tool results, which is a real benefit for trust, but it cost more LLM calls (3.6 vs 2.8 per run) and more tokens (13326 vs 11526.6 per run) and did not improve any final decision. B lost G-04 and G-07 because both of its agents judged an existing product as covering the need; its reviewer repeated the analyst's judgement instead of correcting it.

## Risks / limitations
Partial coverage and one trial: the result could change with the full 22 cases. Neither agent reliably adds Security/Privacy when personal data is only implied by free text (G-23 failed for A and B); the rules-only fallback cannot catch it either. Before production I would run the full set with more trials and add a deterministic personal-data keyword check to the policy engine.

## Why this is the right MVP
The product's safety comes from code, not from agents: approvals, flags and missing information are computed deterministically, every recommendation goes to a human, and there are no action tools. A single bounded agent adds the judgement the reviewer needs at the lowest cost; a second agent did not earn its extra calls on this evidence.
