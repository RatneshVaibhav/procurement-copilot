# Architecture Decision Memo

## Decision
I would ship **A, the single bounded agent**.

Before any LLM evaluation ran, I committed a rule (`evals/DECISION_RULE.md`): B ships only if it passes at least 2 more golden cases than A, or fixes a safety failure that A has, within 2× A's latency. On all 23 cases A passed 21 and B passed 18, and neither had a safety failure. A second, stronger model gave the same answer.

## Evidence
Same 23 golden cases for both architectures, one model per comparison, strict scoring (over-escalating also fails a case). Main eval: Gemini `gemini-3.5-flash-lite`, free tier, every case on both. Numbers from `evals/results/summary.md`:

| Metric | A: bounded agent | B: sequential specialists | Rules-only |
|---|---:|---:|---:|
| Golden cases passed | 21/23 | 18/23 | 20/23 |
| Injection / fault cases passed | 3/3 / 2/2 | 2/3 / 2/2 | 3/3 / 1/2 |
| Same decision in 3 trials (6 cases) | 4/6 | 3/6 | n/a (1 trial) |
| Fallback runs (incl. LLM-outage case) | 1 | 5 | n/a |
| Avg active latency (ms) | 6791.3 | 8286.1 | 63.9 |
| Avg LLM / tool calls per run | 3.3 / 5.3 | 3.9 / 6.2 | 0 / 5 |
| Avg tokens / run | 13600.6 | 13816.7 | 0 |

On the stronger Groq `qwen/qwen3.8-27b` (`evals/results_qwen/summary.md`) the free token cap stopped the run after 10 paired cases: A passed 9, B 7.

## Trade-offs
Both versions share one rules engine: code computes the approval thresholds, the budget check, vendor-review status, the Security/Privacy/Legal triggers and the injection scan. The AI can add a review but never remove what code decided.

B's reviewer double-checks the evidence, but costs more calls. Its analyst ran out of turns in 4 runs (the code fallback took over) and looked up vendors that don't exist (the code gate corrected it). It never turned one of A's failures into a pass.

The model matters more than the architecture. With qwen, the AI spots that a licensed tool already covers the need (G-08), which rules can't; Flash-Lite gets that right only once in three trials.

## Risks / limitations
The main eval uses a small free model, and qwen covered only part of the cases. Neither agent reliably adds Security or Privacy when personal data is only implied by the text (G-23 fails everywhere). Before production I would run every case several times on a stronger model and add a deterministic personal-data check.

## Why this is the right MVP
Safety here comes from code, not from the number of agents: approvals, flags and missing information are deterministic, a human makes every decision, and no tool can approve, buy or notify anyone. One bounded agent adds the judgement a reviewer needs at the lowest cost; a second agent didn't earn its extra calls.
