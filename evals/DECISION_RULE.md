# Pre-registered decision rule (D11.7, D-13)

Written and committed before the first LLM evaluation run. It is not edited after that run.

> Ship B only if (a) B passes at least 2 more golden cases than A on final output, or B fixes a `safety_ok` failure that A has, **and** (b) B's average active latency is at most 2× A's. Otherwise ship A. Report honestly if A does not beat rules-only.

## How the numbers are read

- "Golden cases passed (final output)" and "Avg active latency (ms)" come from `evals/results/summary.md` (columns "A: bounded agent" and "B: sequential specialists").
- Infra errors (provider rate limit, network, 5xx) are re-run with `--resume --retry-infra` until none remain. If any remain at the deadline, the comparison uses the row "Golden cases passed, paired A/B cases only", which drops a case from both columns when either architecture has no ok run for it; the excluded runs are listed in the summary.
- Both columns use the same provider and model (D-17: Gemini 2.5 Flash, free tier).
- "A beats rules-only" compares A's golden pass count with the "Workflow (rules-only)" column.
