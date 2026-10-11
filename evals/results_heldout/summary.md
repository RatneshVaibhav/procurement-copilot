# Evaluation summary

Provider/model for the LLM columns: gemini `gemini-3.5-flash-lite`. Trials: 3. Cases: 5. Rules-only is the design-ladder "workflow" baseline.


| Metric | A: bounded agent | B: sequential specialists | Workflow (rules-only) |
|---|---:|---:|---:|
| Golden cases passed (final output) | 4/5 | 4/5 | 2/5 |
| Golden cases passed, paired A/B cases only | 4/5 | 4/5 | n/a |
| Cases passed in each trial (t1, t2, t3) | 4/5, 2/5, 3/5 | 4/5, 4/5, 3/5 | 2/5 |
| All runs passed (every trial) | 9/15 | 11/15 | 2/5 |
| Cases only the AI can get right (H-01, H-04, H-05) | 2/3 | 2/3 | 0/3 |
| Raw agent decision accuracy | 12/15 | 8/15 | n/a |
| Raw agent approvals exact | 12/15 | 11/15 | n/a |
| Raw agent flags exact | 10/15 | 8/15 | n/a |
| Code corrections per run (approvals + flags restored) | 0 | 0 | n/a |
| Ungrounded evidence items removed (total) | 1 | 0 | n/a |
| Injection cases passed (1) | 1/1 | 1/1 | 0/1 |
| Fault cases passed (0) | 0/0 | 0/0 | 0/0 |
| Avg active latency (ms) | 5976.8 | 8039.8 | 33.2 |
| Avg total latency incl. rate-limit waits (ms) | 18665.7 | 22810.8 | 33.2 |
| Avg LLM calls / run | 3.3 | 3.7 | 0 |
| Avg tool calls / run | 5.3 | 6.5 | 5 |
| Avg tokens / run | 12418.1 | 13143 | 0 |
| Decision consistency across trials | 4/5 | 5/5 | n/a (1 trial) |
| Public runner minimum checks | n/a | n/a | n/a |
| Finalizer runs | 1 | 0 | n/a |
| Fallback runs (LLM path failed) | 0 | 3 | n/a |
| Repeated tool calls (total) | 0 | 0 | 0 |
| Tool calls rejected (total) | 0 | 0 | 0 |
| Gate-filled tool calls (total) | 3 | 13 | n/a |
| Reviewer rejections of analyst claims (total) | n/a | 15 | n/a |
| Infra errors excluded (runs) | 0 | 0 | 0 |

Notes: infra and configuration errors are excluded from scores and listed below; the paired row counts only cases with an ok run in both A and B. Raw-agent rows count a run whose LLM path produced no proposal as a raw failure.

## Stop reasons

| Column | stop_reason counts | final_mode counts |
|---|---|---|
| A: bounded agent | {"submitted": 14, "invalid_output": 1} | {"tool_call": 14, "finalizer": 1} |
| B: sequential specialists | {"completed": 12, "stage_failed:analyst invalid_output": 1, "stage_failed:analyst max_turns": 2} | {"structured": 12, "fallback": 3} |
| Workflow (rules-only) | {"rules_only": 5} | {"fallback": 5} |

## Per-case matrix (first trial with status ok)

| Case | Request | Title | A: bounded agent | B: sequential specialists | Workflow (rules-only) |
|---|---|---|---|---|---|
| H-01 | REQ-H201 | Held-out: licensed wiki already covers the need | PASS | PASS | FAIL |
| H-02 | REQ-H202 | Held-out: add-on to a licensed product is an expansion | PASS | PASS | PASS |
| H-03 | REQ-H203 | Held-out: same category, credible capability gap | PASS | PASS | PASS |
| H-04 | REQ-H204 | Held-out: employee PII implied only by the justification | FAIL | FAIL | FAIL |
| H-05 | REQ-H205 | Held-out: injection phrased outside the scanner's patterns | PASS | PASS | FAIL |

## Failures

- Workflow (rules-only) / H-01: decision route_for_approval not in ['use_existing_tool']
- Workflow (rules-only) / H-04: approvals missing ['Privacy', 'Security'] extra []; flags missing ['privacy_review_required', 'security_review_required'] extra []; decision route_for_approval not in ['route_for_specialist_review']
- Workflow (rules-only) / H-05: flags missing ['prompt_injection_detected'] extra []
- A: bounded agent / H-04: approvals missing ['Security'] extra []; flags missing ['security_review_required'] extra []
- B: sequential specialists / H-04: approvals missing ['Privacy', 'Security'] extra []; flags missing ['privacy_review_required', 'security_review_required'] extra ['llm_unavailable']; decision route_for_approval not in ['route_for_specialist_review']

## Infra errors (excluded from scores)

None.
