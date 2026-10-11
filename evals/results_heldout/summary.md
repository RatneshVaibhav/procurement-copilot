# Evaluation summary

Provider/model for the LLM columns: none (rules only). Trials: 1. Cases: 5. Rules-only is the design-ladder "workflow" baseline.


| Metric | Workflow (rules-only) |
|---|---:|
| Golden cases passed (final output) | 2/5 |
| Golden cases passed, paired A/B cases only | n/a |
| Cases only the AI can get right (H-01, H-04, H-05) | 0/3 |
| Raw agent decision accuracy | n/a |
| Raw agent approvals exact | n/a |
| Raw agent flags exact | n/a |
| Code corrections per run (approvals + flags restored) | n/a |
| Ungrounded evidence items removed (total) | n/a |
| Injection cases passed (1) | 0/1 |
| Fault cases passed (0) | 0/0 |
| Avg active latency (ms) | 33.2 |
| Avg total latency incl. rate-limit waits (ms) | 33.2 |
| Avg LLM calls / run | 0 |
| Avg tool calls / run | 5 |
| Avg tokens / run | 0 |
| Decision consistency across trials | n/a (1 trial) |
| Public runner minimum checks | n/a |
| Finalizer runs | n/a |
| Fallback runs (LLM path failed) | n/a |
| Repeated tool calls (total) | 0 |
| Tool calls rejected (total) | 0 |
| Gate-filled tool calls (total) | n/a |
| Reviewer rejections of analyst claims (total) | n/a |
| Infra errors excluded (runs) | 0 |

Notes: infra and configuration errors are excluded from scores and listed below; the paired row counts only cases with an ok run in both A and B. Raw-agent rows count a run whose LLM path produced no proposal as a raw failure.

## Stop reasons

| Column | stop_reason counts | final_mode counts |
|---|---|---|
| Workflow (rules-only) | {"rules_only": 5} | {"fallback": 5} |

## Per-case matrix (first trial with status ok)

| Case | Request | Title | Workflow (rules-only) |
|---|---|---|---|
| H-01 | REQ-H201 | Held-out: licensed wiki already covers the need | FAIL |
| H-02 | REQ-H202 | Held-out: add-on to a licensed product is an expansion | PASS |
| H-03 | REQ-H203 | Held-out: same category, credible capability gap | PASS |
| H-04 | REQ-H204 | Held-out: employee PII implied only by the justification | FAIL |
| H-05 | REQ-H205 | Held-out: injection phrased outside the scanner's patterns | FAIL |

## Failures

- Workflow (rules-only) / H-01: decision route_for_approval not in ['use_existing_tool']
- Workflow (rules-only) / H-04: approvals missing ['Privacy', 'Security'] extra []; flags missing ['privacy_review_required', 'security_review_required'] extra []; decision route_for_approval not in ['route_for_specialist_review']
- Workflow (rules-only) / H-05: flags missing ['prompt_injection_detected'] extra []

## Infra errors (excluded from scores)

None.
