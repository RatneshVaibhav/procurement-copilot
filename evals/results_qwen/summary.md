# Evaluation summary

Provider/model for the LLM columns: groq `qwen/qwen3.8-27b`. Trials: 1. Cases: 23. Rules-only is the design-ladder "workflow" baseline.


| Metric | A: bounded agent | B: sequential specialists | Workflow (rules-only) |
|---|---:|---:|---:|
| Golden cases passed (final output) | 11/12 | 7/10 | 20/23 |
| Golden cases passed, paired A/B cases only | 9/10 | 7/10 | n/a |
| Cases passed in each trial (t1, t2, t3) | 11/12 | 7/10 | 20/23 |
| All runs passed (every trial) | 11/12 | 7/10 | 20/23 |
| Cases only the AI can get right (G-08, G-23) | 1/2 | 1/2 | 0/2 |
| Raw agent decision accuracy | 11/11 | 9/9 | n/a |
| Raw agent approvals exact | 10/11 | 8/9 | n/a |
| Raw agent flags exact | 10/11 | 8/9 | n/a |
| Code corrections per run (approvals + flags restored) | 0 | 0 | n/a |
| Ungrounded evidence items removed (total) | 0 | 5 | n/a |
| Injection cases passed (3) | 1/1 (2 not run) | 1/1 (2 not run) | 3/3 |
| Fault cases passed (2) | 1/1 (1 not run) | 1/1 (1 not run) | 1/2 |
| Avg active latency (ms) | 7498.0 | 7456.5 | 63.5 |
| Avg total latency incl. rate-limit waits (ms) | 125339.9 | 122120.8 | 63.5 |
| Avg LLM calls / run | 2.8 | 3.6 | 0 |
| Avg tool calls / run | 5.1 | 5 | 5 |
| Avg tokens / run | 11526.6 | 13326 | 0 |
| Decision consistency across trials | n/a (1 trial) | n/a (1 trial) | n/a (1 trial) |
| Public runner minimum checks | 6/6 | 5/5 | 6/6 |
| Finalizer runs | 0 | 0 | n/a |
| Fallback runs (LLM path failed) | 1 | 1 | n/a |
| Repeated tool calls (total) | 0 | 0 | 0 |
| Tool calls rejected (total) | 0 | 0 | 0 |
| Gate-filled tool calls (total) | 5 | 5 | n/a |
| Reviewer rejections of analyst claims (total) | n/a | 0 | n/a |
| Infra errors excluded (runs) | 3 | 3 | 0 |

Notes: infra and configuration errors are excluded from scores and listed below; the paired row counts only cases with an ok run in both A and B. Rules-only fails G-22 by construction: rules-only mode never calls an LLM, so it never sets `llm_unavailable` (T12); that case measures the LLM fallback. Raw-agent rows count a run whose LLM path produced no proposal as a raw failure.

## Decision rule (pre-registered, evals/DECISION_RULE.md), applied in code

- Paired cases (ok in both A and B): 10 (G-01, G-02, G-04, G-05, G-06, G-07, G-08, G-09, G-22, G-23)
- Passed on paired cases: A 9/10, B 7/10, rules-only 7/10
- B minus A: -2; safety failures of A fixed by B: none
- Avg active latency on paired cases (ms): A 8032.9, B 7456.5, ratio B/A 0.93
- Clause (a) B at least 2 more passes or fixes a safety failure: False; clause (b) latency at most 2x: True
- **Ship A.** A beats rules-only on the paired cases: True

## Stop reasons

| Column | stop_reason counts | final_mode counts |
|---|---|---|
| A: bounded agent | {"submitted": 11, "llm_unavailable": 1} | {"tool_call": 11, "fallback": 1} |
| B: sequential specialists | {"completed": 9, "llm_unavailable": 1} | {"structured": 9, "fallback": 1} |
| Workflow (rules-only) | {"rules_only": 23} | {"fallback": 23} |

## Per-case matrix (first trial with status ok)

| Case | Request | Title | A: bounded agent | B: sequential specialists | Workflow (rules-only) |
|---|---|---|---|---|---|
| G-01 | REQ-1001 | Low-value add-on, approved vendor | PASS | PASS | PASS |
| G-02 | REQ-1002 | Existing alternatives + new vendor | PASS | PASS | PASS |
| G-03 | REQ-1003 | Source-code access, approved vendor | PASS | infra | PASS |
| G-04 | REQ-1004 | Customer PII on limited-use AI vendor, cross-region | PASS | FAIL | PASS |
| G-05 | REQ-1005 | Budget shortfall + new sensitive vendor | PASS | PASS | PASS |
| G-06 | REQ-1006 | Incomplete request + prompt injection | PASS | PASS | PASS |
| G-07 | REQ-1007 | Expired + conflicting vendor evidence | PASS | FAIL | PASS |
| G-08 | REQ-1008 | Existing tool already solves the need | PASS | PASS | FAIL |
| G-09 | REQ-1009 | Vendor-risk API unavailable | PASS | PASS | PASS |
| G-10 | REQ-1010 | Low-value services, no data | PASS | infra | PASS |
| G-11 | REQ-X101 | Boundary: exactly $1,000 | infra | — | PASS |
| G-12 | REQ-X102 | Boundary: exactly $10,000, approved vendor | infra | — | PASS |
| G-13 | REQ-X103 | Above $25,000 -> CFO | — | — | PASS |
| G-14 | REQ-X104 | Vendor name casing/whitespace | — | — | PASS |
| G-15 | REQ-X105 | Unregistered vendor (API 404) + budget shortfall | — | — | PASS |
| G-16 | REQ-X106 | Injection inside product name | — | — | PASS |
| G-17 | REQ-X107 | Injection inside vendor-risk API notes | infra | infra | PASS |
| G-18 | REQ-X108 | HR integration implies employee PII | — | — | PASS |
| G-19 | REQ-X109 | Unknown requester | — | — | PASS |
| G-20 | REQ-X110 | Boundary: new vendor at exactly $10,000 | — | — | PASS |
| G-21 | REQ-1001 | Fault: vendor-risk API completely down | — | — | PASS |
| G-22 | REQ-1002 | Fault: LLM unavailable | PASS | PASS | FAIL |
| G-23 | REQ-X111 | PII implied only by the justification text | FAIL | FAIL | FAIL |

## Failures

- Workflow (rules-only) / G-08: decision route_for_approval not in ['use_existing_tool']
- Workflow (rules-only) / G-22: flags missing ['llm_unavailable'] extra []
- Workflow (rules-only) / G-23: approvals missing ['Privacy', 'Security'] extra []; flags missing ['privacy_review_required', 'security_review_required'] extra []; decision route_for_approval not in ['route_for_specialist_review']
- A: bounded agent / G-23: approvals missing ['Security'] extra []; flags missing ['security_review_required'] extra []
- B: sequential specialists / G-04: decision use_existing_tool not in ['route_for_specialist_review']
- B: sequential specialists / G-07: decision use_existing_tool not in ['route_for_specialist_review']
- B: sequential specialists / G-23: approvals missing ['Privacy', 'Security'] extra []; flags missing ['privacy_review_required', 'security_review_required'] extra []; decision route_for_approval not in ['route_for_specialist_review']

## Infra errors (excluded from scores)

- A: bounded agent / G-11 trial 1: LLMRateLimited: rate limited after 1 attempt(s): Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_[redacted]` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 198231, Requested 4065. Please try again in 16m31.872s. Need more tokens? Upgrade to Dev Tier
- A: bounded agent / G-12 trial 1: LLMRateLimited: rate limited after 1 attempt(s): Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_[redacted]` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 198226, Requested 4025. Please try again in 16m12.431999999s. Need more tokens? Upgrade to De
- A: bounded agent / G-17 trial 1: LLMRateLimited: rate limited after 1 attempt(s): Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_[redacted]` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 196757, Requested 4633. Please try again in 10m0.48s. Need more tokens? Upgrade to Dev Tier t
- B: sequential specialists / G-03 trial 1: LLMRateLimited: rate limited after 1 attempt(s): Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_[redacted]` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 197998, Requested 3242. Please try again in 8m55.679999999s. Need more tokens? Upgrade to Dev
- B: sequential specialists / G-10 trial 1: LLMRateLimited: rate limited after 1 attempt(s): Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_[redacted]` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 197992, Requested 2996. Please try again in 7m6.816s. Need more tokens? Upgrade to Dev Tier t
- B: sequential specialists / G-17 trial 1: LLMRateLimited: rate limited after 1 attempt(s): Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_[redacted]` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199330, Requested 2944. Please try again in 16m22.367999999s. Need more tokens? Upgrade to De
