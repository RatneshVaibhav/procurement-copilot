# Agent log (written by me, not by Claude Code)

How I guided Claude Code through this build (Class 10: agentic coding with human ownership of correctness). A few lines per phase is enough.

> **Before submitting:** the answers below are facts Claude Code compiled from the build (commits, `docs/BUILD_LOG.md`, `docs/DECISIONS.md`) so I don't forget anything. I must review each one and rewrite it in my own words, then delete this note.

## Setup
- Provider / model chosen and why: Groq `openai/gpt-oss-20b` first (spec default, D-12). It made one tool call per turn, so an A run took 7 calls and ~17K tokens against a 200K tokens/day free cap. Gemini 2.5 Flash free (D-17) turned out to allow only 20 requests/day on my project. The reported eval uses Groq `qwen/qwen3.8-27b` (D-20): free, parallel tool calls, ~11.5K tokens per A run, with reasoning off because Groq caps it at 1,000 output tokens/minute.
- Rate-limit headers seen in the smoke test: Groq `x-ratelimit-limit-tokens: 8000` (per minute), `x-ratelimit-limit-requests: 1000` (per day); qwen's daily cap from a 429: "tokens per day (TPD): Limit 200000". Gemini: `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, limit 20.
- LLM budget option chosen and why: free tiers only (my decision; I did not want to pay). Consequence: the LLM eval is partial and run in paired order (A and B per case) so the comparison stays fair when the quota stops it.

## Inspection and plan
- Kickoff prompt used: see PLAN.md. What its repository summary got wrong or missed: the kickoff report was not saved to the repo, so its defaults were re-listed one by one as D-07.1–D-07.11.
- Spec conflicts or ambiguities it reported, and how I resolved them: forced `tool_choice` removed (D1 vs T7); Analyst has 5 tools (D5 vs T18 diagram); public runner changes limited to startup/output/exit code (D-08); registered vendor with a vendor-risk 404 adds Security (D-01); no product names in rule patterns (D-02); overlap flag is code-only (D-03); LLM-added injection flag needs a verbatim excerpt (D-04).

## Per phase
| Phase | What I checked | Something I corrected or overruled | Tests run |
|---|---|---|---|
| P0 | Smoke test output, rate-limit headers | Switched to continuous mode (D-11) instead of a STOP per phase | starter tests + config/mock tests |
| P1 | Engine evidence for REQ-1007 (conflict) and REQ-1009 (unavailable) | Reviewer: server error text was leaking into engine output (made untrusted); R7 keyword fallback matched "product" as "prod" | 93 |
| P2 | Rules-only safety net: public runner 6/6 under LLM outage | Reviewer: grounding check could be gamed (substring matches, echoed agent arguments) | 124 |
| P3 | Three real Groq runs (REQ-1006, 1008, 1009), public 6/6 | A unit test had silently called the real LLM; fixed by blanking keys in tests. 400-error handling misread a "reasoning" word | 155+ |
| P4 | Supervisor route reasons; reviewer audit | Reviewer `tool_use_failed` escaped to the last-resort path; policy block lacked the untrusted prefix | 181 |
| P5 | Rules-only baseline 20/23; decision rule committed before any LLM run | Provider-mixing guard covered only one column; missing key would have produced fake "A/B" runs | 197 |
| P6 | Browser checks (my checklist) | Stale analysis result could show under another request; Confirm enabled before the consequence loaded | 192+ |
| P7 | Eval results, README, memo | Paired eval order; dashboard, compare view, evidence pack; overlap prompt clarified with eval evidence | 199 |

## Evidence (Class 10 checklist)
- One diff I reviewed line by line (commit hash + what I looked for): `de38e04` (guardrails): that the LLM path can only add Security/Privacy/Legal and never remove a policy approval, flag or missing item.
- One incorrect assumption or fabricated API I caught: the spec assumed Gemini's free tier allows "a few hundred" requests/day; the real limit on my project was 20. Also: a 400-error check matched the word "reasoning" inside model output and would have silently changed model settings mid-eval.
- One decision where I redirected the agent, and why: no paid plan and no extra accounts to get around quotas; instead a paired eval order and honest partial coverage.

## My judgement calls (I can defend each in a viva)
1. Decision rule (evals/DECISION_RULE.md): B must win by at least 2 golden cases (or fix a safety failure) at no more than 2× latency, because a second agent doubles the moving parts and must earn them.
2. Assumption 11 (overlap flag on same category or identical name): the flag is literal and deterministic; whether the tool actually meets the need is the AI's judgement and only drives `use_existing_tool`.
3. Assumption 13 (vendor API down, registry current, data not sensitive → no extra Security): the gap is recorded and flagged, but it is not material when nothing sensitive is involved (policy §10 "if material").
4. Ship decision and what I would validate before production: ship A per the rule; validate on the full case set with more trials, add a deterministic check for personal data implied by free text (G-23), and complete the manual review.
