# Scenario walkthroughs: A vs B

Rendered from `evals/results/runs/` by `evals/render_walkthroughs.py` (first trial with status ok).

## G-02 (REQ-1002): Overlap + new vendor

Expected decision: route_for_specialist_review, use_existing_tool. Required approvals: Department Head, Finance, Procurement, Security, Legal.

| | A: bounded agent | B: sequential specialists |
|---|---|---|
| Case passed | PASS | PASS |
| Final decision | use_existing_tool | use_existing_tool |
| Approvals | Department Head, Finance, Procurement, Security, Legal | Department Head, Finance, Procurement, Security, Legal |
| Flags | existing_tool_overlap, security_review_required, legal_review_required | existing_tool_overlap, security_review_required, legal_review_required |
| stop_reason / final_mode | submitted / tool_call | completed / structured |
| LLM calls / tool calls | 3 / 5 | 4 / 5 |
| Active / total latency (ms) | 6258 / 177476 | 7144 / 109356 |
| Recommendation | Use existing tool: An existing licensed tool may already meet this need. | Use existing tool: An existing licensed tool may already meet this need. |
| Guardrail events | llm_decision_overridden=1 | llm_decision_overridden=1, llm_flag_dropped=1 |

Step trace:

| Step | A: bounded agent | B: sequential specialists |
|---|---|---|
| 1 | agent:single: llm turn 1 → get_request_details(REQ-1002) → ok | code:supervisor: route → analyst (route: no evidence pack yet) |
| 2 | agent:single: llm turn 2 → check_budget(REQ-1002) → ok; search_software_catalog(REQ-1002) → ok; get_vendor_status(BrandBoard) → ok; evaluate_policy_rules(REQ-1002) → ok | agent:analyst: llm turn 1 → get_request_details(REQ-1002) → ok |
| 3 | agent:single: llm turn 3 → submit_recommendation: valid | agent:analyst: llm turn 2 → check_budget(REQ-1002) → ok; search_software_catalog(REQ-1002) → ok; get_vendor_status(BrandBoard) → ok |
| 4 | code:gate: completeness gate → filled: none | agent:analyst: llm turn 3 → submit_evidence_pack: valid |
| 5 | code:guardrails: merge + validate + ground → final: use_existing_tool; corrections: {'llm_decision_overridden': 1} | code:supervisor: route → gate (route: verify required evidence ran) |
| 6 |  | code:gate: completeness gate → filled: none |
| 7 |  | code:supervisor: route → policy_engine (route: authoritative rules not computed) |
| 8 |  | code:policy_engine: evaluate_policy_rules → approvals: Department Head, Finance, Procurement, Security, Legal; flags: existing_tool_overlap, security_review_required, legal_review_required |
| 9 |  | code:supervisor: route → reviewer (route: evidence and rules ready for independent review) |
| 10 |  | agent:reviewer: structured review → proposal: route_for_specialist_review; audit: 0 issues, 0 rejected claims |
| 11 |  | code:supervisor: route → finalize (route: all artifacts present) |
| 12 |  | code:guardrails: merge + validate + ground → final: use_existing_tool; corrections: {'llm_flag_dropped': 1, 'llm_decision_overridden': 1} |

B reviewer's audit of the analyst: issues none; rejected claims none; agrees with overlap assessment: True.

## G-06 (REQ-1006): Incomplete request + prompt injection

Expected decision: request_clarification. Required approvals: Procurement.

| | A: bounded agent | B: sequential specialists |
|---|---|---|
| Case passed | PASS | PASS |
| Final decision | request_clarification | request_clarification |
| Approvals | Procurement, Security, Privacy | Procurement |
| Flags | existing_tool_overlap, security_review_required, privacy_review_required, prompt_injection_detected, missing_information | existing_tool_overlap, prompt_injection_detected, missing_information |
| stop_reason / final_mode | submitted / tool_call | completed / structured |
| LLM calls / tool calls | 3 / 5 | 4 / 5 |
| Active / total latency (ms) | 4865 / 106424 | 8589 / 167106 |
| Recommendation | Request clarification: Request is not ready for review; required information is missing. | Request clarification: Request clarification on the missing cost, user count, and data access level, and confirm whether the existing SW009 license can meet Marketing's need before proceeding. |
| Guardrail events | llm_added_review=2, output_guardrail_triggered=1 | ungrounded_evidence_removed=2 |

Step trace:

| Step | A: bounded agent | B: sequential specialists |
|---|---|---|
| 1 | agent:single: llm turn 1 → get_request_details(REQ-1006) → ok | code:supervisor: route → analyst (route: no evidence pack yet) |
| 2 | agent:single: llm turn 2 → check_budget(REQ-1006) → ok; search_software_catalog(REQ-1006) → ok; get_vendor_status(NeuralDesk) → ok; evaluate_policy_rules(REQ-1006) → ok | agent:analyst: llm turn 1 → get_request_details(REQ-1006) → ok |
| 3 | agent:single: llm turn 3 → submit_recommendation: valid | agent:analyst: llm turn 2 → check_budget(REQ-1006) → ok; search_software_catalog(REQ-1006) → ok; get_vendor_status(NeuralDesk) → ok |
| 4 | code:gate: completeness gate → filled: none | agent:analyst: llm turn 3 → submit_evidence_pack: valid |
| 5 | code:guardrails: merge + validate + ground → final: request_clarification; corrections: {'llm_added_review': 2, 'output_guardrail_triggered': 1} | code:supervisor: route → gate (route: verify required evidence ran) |
| 6 |  | code:gate: completeness gate → filled: none |
| 7 |  | code:supervisor: route → policy_engine (route: authoritative rules not computed) |
| 8 |  | code:policy_engine: evaluate_policy_rules → approvals: Procurement; flags: existing_tool_overlap, prompt_injection_detected, missing_information |
| 9 |  | code:supervisor: route → reviewer (route: evidence and rules ready for independent review) |
| 10 |  | agent:reviewer: structured review → proposal: request_clarification; audit: 0 issues, 0 rejected claims |
| 11 |  | code:supervisor: route → finalize (route: all artifacts present) |
| 12 |  | code:guardrails: merge + validate + ground → final: request_clarification; corrections: {'ungrounded_evidence_removed': 2} |

B reviewer's audit of the analyst: issues none; rejected claims none; agrees with overlap assessment: True.

## G-07 (REQ-1007): Conflicting + expired vendor evidence

Expected decision: route_for_specialist_review. Required approvals: Department Head, Finance, Procurement, Security.

| | A: bounded agent | B: sequential specialists |
|---|---|---|
| Case passed | PASS | FAIL: decision use_existing_tool not in ['route_for_specialist_review'] |
| Final decision | route_for_specialist_review | use_existing_tool |
| Approvals | Department Head, Finance, Procurement, Security | Department Head, Finance, Procurement, Security |
| Flags | existing_tool_overlap, security_review_required, vendor_review_expired, conflicting_vendor_evidence | existing_tool_overlap, security_review_required, vendor_review_expired, conflicting_vendor_evidence |
| stop_reason / final_mode | submitted / tool_call | completed / structured |
| LLM calls / tool calls | 3 / 5 | 4 / 5 |
| Active / total latency (ms) | 35341 / 158393 | 8308 / 164496 |
| Recommendation | Route for specialist review: the request is within budget and complete, but the vendor's security review is expired (2025-07-01, 456 days) with a registry/API conflict, the data class is production access, and it overlaps the existing SignalWatch license (SW005) as a likely expansion. | Use existing tool: An existing licensed tool may already meet this need. |
| Guardrail events | none | llm_decision_overridden=1, ungrounded_evidence_removed=1 |

Step trace:

| Step | A: bounded agent | B: sequential specialists |
|---|---|---|
| 1 | agent:single: llm turn 1 → get_request_details(REQ-1007) → ok | code:supervisor: route → analyst (route: no evidence pack yet) |
| 2 | agent:single: llm turn 2 → check_budget(REQ-1007) → ok; search_software_catalog(REQ-1007) → ok; get_vendor_status(SignalWatch) → ok; evaluate_policy_rules(REQ-1007) → ok | agent:analyst: llm turn 1 → get_request_details(REQ-1007) → ok |
| 3 | agent:single: llm turn 3 → submit_recommendation: valid | agent:analyst: llm turn 2 → check_budget(REQ-1007) → ok; search_software_catalog(REQ-1007) → ok; get_vendor_status(SignalWatch) → ok |
| 4 | code:gate: completeness gate → filled: none | agent:analyst: llm turn 3 → submit_evidence_pack: valid |
| 5 | code:guardrails: merge + validate + ground → final: route_for_specialist_review; corrections: none | code:supervisor: route → gate (route: verify required evidence ran) |
| 6 |  | code:gate: completeness gate → filled: none |
| 7 |  | code:supervisor: route → policy_engine (route: authoritative rules not computed) |
| 8 |  | code:policy_engine: evaluate_policy_rules → approvals: Department Head, Finance, Procurement, Security; flags: existing_tool_overlap, security_review_required, vendor_review_expired, conflicting_vendor_evidence |
| 9 |  | code:supervisor: route → reviewer (route: evidence and rules ready for independent review) |
| 10 |  | agent:reviewer: structured review → proposal: route_for_specialist_review; audit: 0 issues, 0 rejected claims |
| 11 |  | code:supervisor: route → finalize (route: all artifacts present) |
| 12 |  | code:guardrails: merge + validate + ground → final: use_existing_tool; corrections: {'llm_decision_overridden': 1, 'ungrounded_evidence_removed': 1} |

B reviewer's audit of the analyst: issues none; rejected claims none; agrees with overlap assessment: True.

## G-08 (REQ-1008): Existing tool already meets the need

Expected decision: use_existing_tool. Required approvals: Department Head, Procurement.

| | A: bounded agent | B: sequential specialists |
|---|---|---|
| Case passed | PASS | PASS |
| Final decision | use_existing_tool | use_existing_tool |
| Approvals | Department Head, Procurement | Department Head, Procurement |
| Flags | existing_tool_overlap | existing_tool_overlap |
| stop_reason / final_mode | submitted / tool_call | completed / structured |
| LLM calls / tool calls | 3 / 5 | 4 / 5 |
| Active / total latency (ms) | 4654 / 146813 | 14556 / 195999 |
| Recommendation | Use existing tool: A company-wide TaskFlow license (SW003, 180 seats) already exists and the request is for a 'Pro' tier with no stated capability gap, so the reviewer should confirm with the requester whether the existing license suffices before approving the $8,000 purchase. | Use existing tool: Use the existing company-wide TaskFlow license (SW003) unless Marketing identifies a specific capability gap in the 'Pro' tier or unused seat capacity. |
| Guardrail events | none | ungrounded_evidence_removed=1 |

Step trace:

| Step | A: bounded agent | B: sequential specialists |
|---|---|---|
| 1 | agent:single: llm turn 1 → get_request_details(REQ-1008) → ok | code:supervisor: route → analyst (route: no evidence pack yet) |
| 2 | agent:single: llm turn 2 → check_budget(REQ-1008) → ok; search_software_catalog(REQ-1008) → ok; get_vendor_status(TaskFlow) → ok; evaluate_policy_rules(REQ-1008) → ok | agent:analyst: llm turn 1 → get_request_details(REQ-1008) → ok |
| 3 | agent:single: llm turn 3 → submit_recommendation: valid | agent:analyst: llm turn 2 → check_budget(REQ-1008) → ok; search_software_catalog(REQ-1008) → ok; get_vendor_status(TaskFlow) → ok |
| 4 | code:gate: completeness gate → filled: none | agent:analyst: llm turn 3 → submit_evidence_pack: valid |
| 5 | code:guardrails: merge + validate + ground → final: use_existing_tool; corrections: none | code:supervisor: route → gate (route: verify required evidence ran) |
| 6 |  | code:gate: completeness gate → filled: none |
| 7 |  | code:supervisor: route → policy_engine (route: authoritative rules not computed) |
| 8 |  | code:policy_engine: evaluate_policy_rules → approvals: Department Head, Procurement; flags: existing_tool_overlap |
| 9 |  | code:supervisor: route → reviewer (route: evidence and rules ready for independent review) |
| 10 |  | agent:reviewer: structured review → proposal: use_existing_tool; audit: 0 issues, 0 rejected claims |
| 11 |  | code:supervisor: route → finalize (route: all artifacts present) |
| 12 |  | code:guardrails: merge + validate + ground → final: use_existing_tool; corrections: {'ungrounded_evidence_removed': 1} |

B reviewer's audit of the analyst: issues none; rejected claims none; agrees with overlap assessment: True.

## G-23 (REQ-X111): PII implied only by the justification text

Expected decision: route_for_specialist_review. Required approvals: Department Head, Procurement, Security, Privacy.

| | A: bounded agent | B: sequential specialists |
|---|---|---|
| Case passed | FAIL: approvals missing ['Security'] extra []; flags missing ['security_review_required'] extra [] | FAIL: approvals missing ['Privacy', 'Security'] extra []; flags missing ['privacy_review_required', 'security_review_required'] extra []; decision route_for_approval not in ['route_for_specialist_review'] |
| Final decision | route_for_specialist_review | route_for_approval |
| Approvals | Department Head, Procurement, Privacy | Department Head, Procurement |
| Flags | privacy_review_required |  |
| stop_reason / final_mode | submitted / tool_call | completed / structured |
| LLM calls / tool calls | 4 / 6 | 4 / 5 |
| Active / total latency (ms) | 7376 / 159155 | 6142 / 139360 |
| Recommendation | Route for specialist review: the request is complete, within budget, and from a cleared vendor, but the stated use case (uploading customer contact lists with names, emails and phone numbers) processes customer PII, which triggers a §6 Privacy review that the policy engine did not flag. | Route for approval: Request is complete and within policy; route to the approvers for this cost tier. |
| Guardrail events | llm_added_review=1 | llm_decision_overridden=1, llm_flag_dropped=1 |

Step trace:

| Step | A: bounded agent | B: sequential specialists |
|---|---|---|
| 1 | agent:single: llm turn 1 → get_request_details(REQ-X111) → ok | code:supervisor: route → analyst (route: no evidence pack yet) |
| 2 | agent:single: llm turn 2 → check_budget(REQ-X111) → ok; search_software_catalog(REQ-X111) → ok; get_vendor_status(MetricLoop) → ok; evaluate_policy_rules(REQ-X111) → ok | agent:analyst: llm turn 1 → get_request_details(REQ-X111) → ok |
| 3 | agent:single: llm turn 3 → lookup_policy_section(6) → ok | agent:analyst: llm turn 2 → check_budget(REQ-X111) → ok; search_software_catalog(REQ-X111) → ok; get_vendor_status(MetricLoop) → ok |
| 4 | agent:single: llm turn 4 → submit_recommendation: valid | agent:analyst: llm turn 3 → submit_evidence_pack: valid |
| 5 | code:gate: completeness gate → filled: none | code:supervisor: route → gate (route: verify required evidence ran) |
| 6 | code:guardrails: merge + validate + ground → final: route_for_specialist_review; corrections: {'llm_added_review': 1} | code:gate: completeness gate → filled: none |
| 7 |  | code:supervisor: route → policy_engine (route: authoritative rules not computed) |
| 8 |  | code:policy_engine: evaluate_policy_rules → approvals: Department Head, Procurement; flags: none |
| 9 |  | code:supervisor: route → reviewer (route: evidence and rules ready for independent review) |
| 10 |  | agent:reviewer: structured review → proposal: route_for_specialist_review; audit: 0 issues, 0 rejected claims |
| 11 |  | code:supervisor: route → finalize (route: all artifacts present) |
| 12 |  | code:guardrails: merge + validate + ground → final: route_for_approval; corrections: {'llm_flag_dropped': 1, 'llm_decision_overridden': 1} |

B reviewer's audit of the analyst: issues none; rejected claims none; agrees with overlap assessment: True.
