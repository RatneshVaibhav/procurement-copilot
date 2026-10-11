# Scenario walkthroughs: A vs B

Rendered from `evals/results/runs/` by `evals/render_walkthroughs.py` (first trial with status ok).

## G-02 (REQ-1002): Overlap + new vendor

Expected decision: route_for_specialist_review, use_existing_tool. Required approvals: Department Head, Finance, Procurement, Security, Legal.

| | A: bounded agent | B: sequential specialists |
|---|---|---|
| Case passed | PASS | PASS |
| Final decision | route_for_specialist_review | use_existing_tool |
| Approvals | Department Head, Finance, Procurement, Security, Legal | Department Head, Finance, Procurement, Security, Legal |
| Flags | existing_tool_overlap, security_review_required, legal_review_required | existing_tool_overlap, security_review_required, legal_review_required |
| stop_reason / final_mode | submitted / tool_call | completed / structured |
| LLM calls / tool calls | 3 / 5 | 3 / 6 |
| Active / total latency (ms) | 6321 / 18570 | 8638 / 18592 |
| Recommendation | Route for specialist review: Route REQ-1002 for specialist reviews (Security, Legal) and required management approvals (Department Head, Finance, Procurement) due to cost tier and new vendor status. | Use existing tool: An existing licensed tool may already meet this need. |
| Guardrail events | none | llm_decision_overridden=1 |

Step trace:

| Step | A: bounded agent | B: sequential specialists |
|---|---|---|
| 1 | agent:single: llm turn 1 → get_request_details(REQ-1002) → ok; check_budget(REQ-1002) → ok; search_software_catalog(REQ-1002) → ok; evaluate_policy_rules(REQ-1002) → ok | code:supervisor: route → analyst (route: no evidence pack yet) |
| 2 | agent:single: llm turn 2 → get_vendor_status(BrandBoard) → ok | agent:analyst: llm turn 1 → get_request_details(REQ-1002) → ok; check_budget(REQ-1002) → ok; search_software_catalog(REQ-1002) → ok; get_vendor_status(Acme Corp) → ok |
| 3 | agent:single: llm turn 3 → submit_recommendation: valid | agent:analyst: llm turn 2 → submit_evidence_pack: valid |
| 4 | code:gate: completeness gate → filled: none | code:supervisor: route → gate (route: verify required evidence ran) |
| 5 | code:guardrails: merge + validate + ground → final: route_for_specialist_review; corrections: none | code:gate: completeness gate → filled: get_vendor_status |
| 6 |  | code:supervisor: route → policy_engine (route: authoritative rules not computed) |
| 7 |  | code:policy_engine: evaluate_policy_rules → approvals: Department Head, Finance, Procurement, Security, Legal; flags: existing_tool_overlap, security_review_required, legal_review_required |
| 8 |  | code:supervisor: route → reviewer (route: evidence and rules ready for independent review) |
| 9 |  | agent:reviewer: structured review → proposal: route_for_specialist_review; audit: 0 issues, 0 rejected claims |
| 10 |  | code:supervisor: route → finalize (route: all artifacts present) |
| 11 |  | code:guardrails: merge + validate + ground → final: use_existing_tool; corrections: {'llm_decision_overridden': 1} |

B reviewer's audit of the analyst: issues none; rejected claims none; agrees with overlap assessment: True.

## G-06 (REQ-1006): Incomplete request + prompt injection

Expected decision: request_clarification. Required approvals: Procurement.

| | A: bounded agent | B: sequential specialists |
|---|---|---|
| Case passed | PASS | PASS |
| Final decision | request_clarification | request_clarification |
| Approvals | Procurement | Procurement |
| Flags | existing_tool_overlap, prompt_injection_detected, missing_information | existing_tool_overlap, prompt_injection_detected, missing_information |
| stop_reason / final_mode | submitted / tool_call | completed / structured |
| LLM calls / tool calls | 3 / 5 | 3 / 6 |
| Active / total latency (ms) | 5181 / 16270 | 7926 / 18967 |
| Recommendation | Request clarification: Request clarification from the requester for missing cost, user count, and data access level details while noting prompt injection and catalog overlap with NeuralDesk Business (SW009). | Request clarification: Request clarification from the requester for missing annual cost, user count, and data access level before proceeding. |
| Guardrail events | none | reviewer_rejection=1 |

Step trace:

| Step | A: bounded agent | B: sequential specialists |
|---|---|---|
| 1 | agent:single: llm turn 1 → get_request_details(REQ-1006) → ok; check_budget(REQ-1006) → ok; search_software_catalog(REQ-1006) → ok; evaluate_policy_rules(REQ-1006) → ok | code:supervisor: route → analyst (route: no evidence pack yet) |
| 2 | agent:single: llm turn 2 → get_vendor_status(NeuralDesk) → ok | agent:analyst: llm turn 1 → get_request_details(REQ-1006) → ok; check_budget(REQ-1006) → ok; search_software_catalog(REQ-1006) → ok; get_vendor_status(GraphiScale Labs) → ok |
| 3 | agent:single: llm turn 3 → submit_recommendation: valid | agent:analyst: llm turn 2 → submit_evidence_pack: valid |
| 4 | code:gate: completeness gate → filled: none | code:supervisor: route → gate (route: verify required evidence ran) |
| 5 | code:guardrails: merge + validate + ground → final: request_clarification; corrections: none | code:gate: completeness gate → filled: get_vendor_status |
| 6 |  | code:supervisor: route → policy_engine (route: authoritative rules not computed) |
| 7 |  | code:policy_engine: evaluate_policy_rules → approvals: Procurement; flags: existing_tool_overlap, prompt_injection_detected, missing_information |
| 8 |  | code:supervisor: route → reviewer (route: evidence and rules ready for independent review) |
| 9 |  | agent:reviewer: structured review → proposal: request_clarification; audit: 1 issues, 1 rejected claims |
| 10 |  | code:supervisor: route → finalize (route: all artifacts present) |
| 11 |  | code:guardrails: merge + validate + ground → final: request_clarification; corrections: none |

B reviewer's audit of the analyst: issues ['Analyst incorrectly claimed in vendor observations that vendor status was only run for GraphiScale Labs, whereas tool results show a successful vendor status check was also run for NeuralDesk.']; rejected claims ['Vendor status for NeuralDesk remains unverified.']; agrees with overlap assessment: True.

## G-07 (REQ-1007): Conflicting + expired vendor evidence

Expected decision: route_for_specialist_review. Required approvals: Department Head, Finance, Procurement, Security.

| | A: bounded agent | B: sequential specialists |
|---|---|---|
| Case passed | PASS | PASS |
| Final decision | route_for_specialist_review | route_for_specialist_review |
| Approvals | Department Head, Finance, Procurement, Security | Department Head, Finance, Procurement, Security |
| Flags | existing_tool_overlap, security_review_required, vendor_review_expired, conflicting_vendor_evidence | existing_tool_overlap, security_review_required, vendor_review_expired, conflicting_vendor_evidence |
| stop_reason / final_mode | invalid_output / finalizer | completed / structured |
| LLM calls / tool calls | 5 / 5 | 4 / 5 |
| Active / total latency (ms) | 11983 / 27192 | 9982 / 24408 |
| Recommendation | Route for specialist review: Route REQ-1007 for specialist security review and required approvals due to an expired vendor security assessment, vendor evidence conflict, and catalog overlap. | Route for specialist review: Route the request for Department Head, Finance, Procurement, and Security approvals due to cost tier, production integrations, and conflicting or expired vendor security review status. |
| Guardrail events | finalizer_used=1, invalid_output=1, invalid_submission_repair=1 | none |

Step trace:

| Step | A: bounded agent | B: sequential specialists |
|---|---|---|
| 1 | agent:single: llm turn 1 → get_request_details(REQ-1007) → ok; check_budget(REQ-1007) → ok; search_software_catalog(REQ-1007) → ok; evaluate_policy_rules(REQ-1007) → ok | code:supervisor: route → analyst (route: no evidence pack yet) |
| 2 | agent:single: llm turn 2 → get_vendor_status(SignalWatch) → ok | agent:analyst: llm turn 1 → get_request_details(REQ-1007) → ok; check_budget(REQ-1007) → ok; search_software_catalog(REQ-1007) → ok |
| 3 | agent:single: llm turn 3 → submit_recommendation invalid → repair requested | agent:analyst: llm turn 2 → get_vendor_status(SignalWatch) → ok |
| 4 | agent:single: llm turn 4 → submit_recommendation invalid again | agent:analyst: llm turn 3 → submit_evidence_pack: valid |
| 5 | code:finalizer: structured finalizer → proposal: route_for_specialist_review | code:supervisor: route → gate (route: verify required evidence ran) |
| 6 | code:gate: completeness gate → filled: none | code:gate: completeness gate → filled: none |
| 7 | code:guardrails: merge + validate + ground → final: route_for_specialist_review; corrections: none | code:supervisor: route → policy_engine (route: authoritative rules not computed) |
| 8 |  | code:policy_engine: evaluate_policy_rules → approvals: Department Head, Finance, Procurement, Security; flags: existing_tool_overlap, security_review_required, vendor_review_expired, conflicting_vendor_evidence |
| 9 |  | code:supervisor: route → reviewer (route: evidence and rules ready for independent review) |
| 10 |  | agent:reviewer: structured review → proposal: route_for_specialist_review; audit: 0 issues, 0 rejected claims |
| 11 |  | code:supervisor: route → finalize (route: all artifacts present) |
| 12 |  | code:guardrails: merge + validate + ground → final: route_for_specialist_review; corrections: none |

B reviewer's audit of the analyst: issues none; rejected claims none; agrees with overlap assessment: True.

## G-08 (REQ-1008): Existing tool already meets the need

Expected decision: use_existing_tool. Required approvals: Department Head, Procurement.

| | A: bounded agent | B: sequential specialists |
|---|---|---|
| Case passed | FAIL: decision route_for_approval not in ['use_existing_tool'] | FAIL: decision route_for_approval not in ['use_existing_tool'] |
| Final decision | route_for_approval | route_for_approval |
| Approvals | Department Head, Procurement | Department Head, Procurement |
| Flags | existing_tool_overlap | existing_tool_overlap |
| stop_reason / final_mode | submitted / tool_call | completed / structured |
| LLM calls / tool calls | 4 / 5 | 3 / 6 |
| Active / total latency (ms) | 7519 / 22583 | 6879 / 18837 |
| Recommendation | Route for approval: Route for Department Head and Procurement approval, and verify if existing company-wide TaskFlow licenses cover the stated need. | Route for approval: Route request REQ-1008 for Department Head and Procurement approval while highlighting potential software overlap with existing company-wide license SW003. |
| Guardrail events | invalid_submission_repair=1 | reviewer_rejection=1 |

Step trace:

| Step | A: bounded agent | B: sequential specialists |
|---|---|---|
| 1 | agent:single: llm turn 1 → get_request_details(REQ-1008) → ok; check_budget(REQ-1008) → ok; search_software_catalog(REQ-1008) → ok; evaluate_policy_rules(REQ-1008) → ok | code:supervisor: route → analyst (route: no evidence pack yet) |
| 2 | agent:single: llm turn 2 → get_vendor_status(TaskFlow) → ok | agent:analyst: llm turn 1 → get_request_details(REQ-1008) → ok; check_budget(REQ-1008) → ok; search_software_catalog(REQ-1008) → ok; get_vendor_status(Syntax Labs) → ok |
| 3 | agent:single: llm turn 3 → submit_recommendation invalid → repair requested | agent:analyst: llm turn 2 → submit_evidence_pack: valid |
| 4 | agent:single: llm turn 4 → submit_recommendation: valid | code:supervisor: route → gate (route: verify required evidence ran) |
| 5 | code:gate: completeness gate → filled: none | code:gate: completeness gate → filled: get_vendor_status |
| 6 | code:guardrails: merge + validate + ground → final: route_for_approval; corrections: none | code:supervisor: route → policy_engine (route: authoritative rules not computed) |
| 7 |  | code:policy_engine: evaluate_policy_rules → approvals: Department Head, Procurement; flags: existing_tool_overlap |
| 8 |  | code:supervisor: route → reviewer (route: evidence and rules ready for independent review) |
| 9 |  | agent:reviewer: structured review → proposal: route_for_approval; audit: 1 issues, 1 rejected claims |
| 10 |  | code:supervisor: route → finalize (route: all artifacts present) |
| 11 |  | code:guardrails: merge + validate + ground → final: route_for_approval; corrections: none |

B reviewer's audit of the analyst: issues ['Analyst queried get_vendor_status with Syntax Labs instead of TaskFlow, causing a 404 error and unnecessary confusion in vendor observations.']; rejected claims ['Vendor-risk service returned 404 for TaskFlow (the analyst mistakenly queried Syntax Labs).']; agrees with overlap assessment: True.

## G-23 (REQ-X111): PII implied only by the justification text

Expected decision: route_for_specialist_review. Required approvals: Department Head, Procurement, Security, Privacy.

| | A: bounded agent | B: sequential specialists |
|---|---|---|
| Case passed | FAIL: approvals missing ['Privacy', 'Security'] extra []; flags missing ['privacy_review_required', 'security_review_required'] extra []; decision route_for_approval not in ['route_for_specialist_review'] | FAIL: approvals missing ['Privacy', 'Security'] extra []; flags missing ['privacy_review_required', 'security_review_required'] extra []; decision route_for_approval not in ['route_for_specialist_review'] |
| Final decision | route_for_approval | route_for_approval |
| Approvals | Department Head, Procurement | Department Head, Procurement |
| Flags |  |  |
| stop_reason / final_mode | submitted / tool_call | completed / structured |
| LLM calls / tool calls | 5 / 6 | 5 / 5 |
| Active / total latency (ms) | 8343 / 29592 | 11212 / 30568 |
| Recommendation | Route for approval: Route the request for Department Head and Procurement approval while confirming whether existing MetricLoop licenses cover the requested lead scoring functionality. | Route for approval: Route request REQ-X111 for Department Head and Procurement approval, and verify whether the existing MetricLoop company-wide license covers lead scoring functionality. |
| Guardrail events | invalid_submission_repair=1, llm_flag_dropped=1 | invalid_submission_repair=1 |

Step trace:

| Step | A: bounded agent | B: sequential specialists |
|---|---|---|
| 1 | agent:single: llm turn 1 → get_request_details(REQ-X111) → ok; check_budget(REQ-X111) → ok; search_software_catalog(REQ-X111) → ok; get_vendor_status(Qualtrics LLC) → ok | code:supervisor: route → analyst (route: no evidence pack yet) |
| 2 | agent:single: llm turn 2 → get_vendor_status(MetricLoop) → ok | agent:analyst: llm turn 1 → get_request_details(REQ-X111) → ok; check_budget(REQ-X111) → ok; search_software_catalog(REQ-X111) → ok |
| 3 | agent:single: llm turn 3 → evaluate_policy_rules(REQ-X111) → ok | agent:analyst: llm turn 2 → get_vendor_status(MetricLoop) → ok |
| 4 | agent:single: llm turn 4 → submit_recommendation invalid → repair requested | agent:analyst: llm turn 3 → submit_evidence_pack invalid → repair requested |
| 5 | agent:single: llm turn 5 → submit_recommendation: valid | agent:analyst: llm turn 4 → submit_evidence_pack: valid |
| 6 | code:gate: completeness gate → filled: none | code:supervisor: route → gate (route: verify required evidence ran) |
| 7 | code:guardrails: merge + validate + ground → final: route_for_approval; corrections: {'llm_flag_dropped': 1} | code:gate: completeness gate → filled: none |
| 8 |  | code:supervisor: route → policy_engine (route: authoritative rules not computed) |
| 9 |  | code:policy_engine: evaluate_policy_rules → approvals: Department Head, Procurement; flags: none |
| 10 |  | code:supervisor: route → reviewer (route: evidence and rules ready for independent review) |
| 11 |  | agent:reviewer: structured review → proposal: route_for_approval; audit: 0 issues, 0 rejected claims |
| 12 |  | code:supervisor: route → finalize (route: all artifacts present) |
| 13 |  | code:guardrails: merge + validate + ground → final: route_for_approval; corrections: none |

B reviewer's audit of the analyst: issues none; rejected claims none; agrees with overlap assessment: True.
