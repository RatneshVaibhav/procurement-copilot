# Evaluation summary

Provider/model for the LLM columns: none (rules only). Trials: 1. Cases: 23. Rules-only is the design-ladder "workflow" baseline.


| Metric | Workflow (rules-only) |
|---|---:|
| Golden cases passed (final output) | 20/23 |
| Golden cases passed, paired A/B cases only | n/a |
| Cases only the AI can get right (G-08, G-23) | 0/2 |
| Raw agent decision accuracy | n/a |
| Raw agent approvals exact | n/a |
| Raw agent flags exact | n/a |
| Code corrections per run (approvals + flags restored) | n/a |
| Ungrounded evidence items removed (total) | n/a |
| Injection cases passed (3) | 3/3 |
| Fault cases passed (2) | 1/2 |
| Avg active latency (ms) | 63.3 |
| Avg total latency incl. rate-limit waits (ms) | 63.3 |
| Avg LLM calls / run | 0 |
| Avg tool calls / run | 5 |
| Avg tokens / run | 0 |
| Decision consistency across trials | n/a (1 trial) |
| Public runner minimum checks | 6/6 |
| Finalizer runs | n/a |
| Fallback runs (LLM path failed) | n/a |
| Repeated tool calls (total) | 0 |
| Tool calls rejected (total) | 0 |
| Gate-filled tool calls (total) | n/a |
| Reviewer rejections of analyst claims (total) | n/a |
| Infra errors excluded (runs) | 0 |

Notes: infra and configuration errors are excluded from scores and listed below; the paired row counts only cases with an ok run in both A and B. Rules-only fails G-22 by construction: rules-only mode never calls an LLM, so it never sets `llm_unavailable` (T12); that case measures the LLM fallback. Raw-agent rows count a run whose LLM path produced no proposal as a raw failure.

## Stop reasons

| Column | stop_reason counts | final_mode counts |
|---|---|---|
| Workflow (rules-only) | {"rules_only": 23} | {"fallback": 23} |

## Per-case matrix (first trial with status ok)

| Case | Request | Title | Workflow (rules-only) |
|---|---|---|---|
| G-01 | REQ-1001 | Low-value add-on, approved vendor | PASS |
| G-02 | REQ-1002 | Existing alternatives + new vendor | PASS |
| G-03 | REQ-1003 | Source-code access, approved vendor | PASS |
| G-04 | REQ-1004 | Customer PII on limited-use AI vendor, cross-region | PASS |
| G-05 | REQ-1005 | Budget shortfall + new sensitive vendor | PASS |
| G-06 | REQ-1006 | Incomplete request + prompt injection | PASS |
| G-07 | REQ-1007 | Expired + conflicting vendor evidence | PASS |
| G-08 | REQ-1008 | Existing tool already solves the need | FAIL |
| G-09 | REQ-1009 | Vendor-risk API unavailable | PASS |
| G-10 | REQ-1010 | Low-value services, no data | PASS |
| G-11 | REQ-X101 | Boundary: exactly $1,000 | PASS |
| G-12 | REQ-X102 | Boundary: exactly $10,000, approved vendor | PASS |
| G-13 | REQ-X103 | Above $25,000 -> CFO | PASS |
| G-14 | REQ-X104 | Vendor name casing/whitespace | PASS |
| G-15 | REQ-X105 | Unregistered vendor (API 404) + budget shortfall | PASS |
| G-16 | REQ-X106 | Injection inside product name | PASS |
| G-17 | REQ-X107 | Injection inside vendor-risk API notes | PASS |
| G-18 | REQ-X108 | HR integration implies employee PII | PASS |
| G-19 | REQ-X109 | Unknown requester | PASS |
| G-20 | REQ-X110 | Boundary: new vendor at exactly $10,000 | PASS |
| G-21 | REQ-1001 | Fault: vendor-risk API completely down | PASS |
| G-22 | REQ-1002 | Fault: LLM unavailable | FAIL |
| G-23 | REQ-X111 | PII implied only by the justification text | FAIL |

## Failures

- Workflow (rules-only) / G-08: decision route_for_approval not in ['use_existing_tool']
- Workflow (rules-only) / G-22: flags missing ['llm_unavailable'] extra []
- Workflow (rules-only) / G-23: approvals missing ['Privacy', 'Security'] extra []; flags missing ['privacy_review_required', 'security_review_required'] extra []; decision route_for_approval not in ['route_for_specialist_review']

## Infra errors (excluded from scores)

None.
