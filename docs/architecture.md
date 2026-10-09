# Architecture: AI Procurement Request Copilot

Companion to `README.md`. Sections follow SPEC_V2_DELTA D15. Every number quoted here comes from `evals/results/`.

## 1. Design ladder (Class 12)

The rule we followed: choose the least autonomous design that reliably meets the need, and let the evaluation decide whether each step up is worth its cost.

| Rung | In this product | Why it is or is not enough |
|---|---|---|
| Single LLM call | Not built | One opaque call: no tool evidence, no traceability, cannot enforce thresholds. |
| Chatbot | Not built | The reviewer needs one analysis per request; follow-ups go to people (requester, approvers), not to a chat. |
| Workflow | **Rules-only mode**: fixed steps, deterministic policy engine (R0–R12) | Predictable and testable, and it is the evaluation baseline. It cannot judge whether an existing tool meets the need (G-08) or see a data class implied only by free text (G-23). |
| Bounded agent | **Architecture A**: one agent, 6 scoped tools, step limit, completeness gate, guardrails | Adds dynamic evidence choice and the two judgements above, bounded by code. |
| Sequential specialists (Class 13) | **Architecture B**: Analyst → code → Reviewer, deterministic supervisor | Tests whether an independent review stage improves grounding and judgement enough to justify the extra calls. |

Code decides thresholds, budget, review currency, conflicts, the Security/Privacy/Legal triggers, required fields and the injection scan. The LLM may only add Security, Privacy or Legal with a reason, judge overlap and write the wording. Humans approve.

## 2. Diagrams

```mermaid
flowchart LR
  E[Employee request] --> Q[Review queue]
  Q --> H[handle_request]
  H -->|single| A1[Procurement Agent<br/>LLM + 6 tools]
  H -->|staged| B1[Analyst agent<br/>LLM + 5 tools]
  B1 --> PE[Policy engine<br/>deterministic code]
  PE --> B2[Policy & Risk Reviewer<br/>LLM, no tools]
  A1 --> G[Guardrails + assembler<br/>code]
  B2 --> G
  G --> D[ProcurementDecision]
  D --> R[Reviewer: evidence, approvals, flags]
  R --> C[Confirm action + reason]
  C --> L[(audit_log.jsonl)]
```

```mermaid
flowchart TB
  subgraph Tools
    T1[get_request_details] --- T2[check_budget] --- T3[search_software_catalog]
    T4[get_vendor_status → mock vendor-risk API] --- T5[evaluate_policy_rules] --- T6[lookup_policy_section]
  end
  subgraph Code_decides
    C1[thresholds · budget · review dates · conflicts · Security/Privacy/Legal triggers · required fields · injection scan]
  end
  subgraph AI_decides
    A1[does an existing tool meet the need? · implied data classes · recommendation wording · next step]
  end
  subgraph Human_decides
    H1[route / clarify / suggest existing / hold · every approval · exceptions]
  end
```

Architecture B's supervisor (deterministic code, not an LLM router):

```mermaid
flowchart LR
  S{{Supervisor<br/>deterministic code}} -->|no evidence pack| AN[Analyst agent<br/>LLM + 5 tools]
  AN --> S
  S -->|verify evidence| GT[Completeness gate<br/>code]
  GT --> S
  S -->|rules not computed| PE[Policy engine<br/>code]
  PE --> S
  S -->|ready for review| RV[Reviewer agent<br/>LLM, structured output, no tools]
  RV --> S
  S -->|all artifacts| GR[Guardrails + assembler<br/>code] --> D[ProcurementDecision]
  S -->|stage failed or step limit| FB[Rules-only fallback]
```

## 3. Agent cards (D7)

| | A: Procurement Agent | B1: Procurement Analyst | B2: Policy & Risk Reviewer | Supervisor (B) |
|---|---|---|---|---|
| Goal | One grounded `AgentProposal` for one request | One `EvidencePack` for one request | One `ReviewerProposal`, every claim checked against raw tool results | Route the request through the stages, then stop |
| Instructions | `SYSTEM_SINGLE` | `SYSTEM_ANALYST` | `SYSTEM_REVIEWER` | Code (`supervisor()`), no LLM |
| Context | User message: request ID + reference date; tool results | Same | Evidence pack + raw tool results + policy-engine result + referenced policy sections | `StagedState` |
| Tools | 6 + `submit_recommendation` | 5 + `submit_evidence_pack` | None (structured output) | Runs gate, policy engine, guardrails |
| State | `RunContext` (messages, cache, tool log, evidence corpus, turn and repeat counters) | Same | Stateless single call | `StagedState` |
| Stop | submitted / `max_turns`=6 / `loop_detected` / `invalid_output` / `llm_unavailable` | Same, `max_turns`=5 | One call + one repair | All artifacts present / stage failed / `MAX_STAGED_STEPS`=8 |
| On failure | Finalizer, then rules-only fallback | Rules-only fallback | Fallback keeping stage-1 evidence that passes grounding | Fallback |

Code: `src/agents/single_agent.py`, `src/agents/staged_agent.py`, shared loop `src/agents/loop.py`, prompts `src/prompts.py`.

## 4. Tools

| Tool | Returns | Type | A | B1 Analyst | B2 Reviewer | Code (gate / orchestrator) |
|---|---|---|:-:|:-:|:-:|:-:|
| `get_request_details` | Normalised facts, requester, missing fields, injection scan; free text under `untrusted_text` | Deterministic | yes | yes | — | gate |
| `check_budget` | Available budget and whether the cost fits | Deterministic | yes | yes | — | gate |
| `search_software_catalog` | Overlapping catalog products, purchase history, overlap-flag candidates | Deterministic | yes | yes | — | gate |
| `get_vendor_status` | Registry + vendor-risk API, reconciled at the reference date (age, expiry, conflict, new vendor, terms, residency) | Deterministic logic over an **external** service | yes | yes | — | gate |
| `evaluate_policy_rules` | Approvals with reasons, flags, missing information, tier, data classes | Deterministic, **authoritative** | yes | — | receives result | orchestrator |
| `lookup_policy_section` | Exact text of one policy section | Deterministic | yes | yes | sections pre-attached | — |
| `submit_recommendation` | — (the agent's output) | Schema-validated | yes | — | via structured output | — |
| `submit_evidence_pack` | — (the analyst's output) | Schema-validated | — | yes | — | — |

No tool can approve, purchase, notify, edit a budget or accept terms. A call to a tool outside the caller's allowlist, or to an unknown name, is not executed: it returns `{"status": "error", "error": "tool not available to this agent"}` and is logged as `tool_rejected`. Tool descriptions (in `src/tools.py`) say what each returns, when to call it, whether it is deterministic or external, and what it does not do.

## 5. AI vs code vs human

| Decides | What |
|---|---|
| Code | Approval thresholds (R4), budget (R3), review currency and expiry (R6), registry/API conflicts (R6), Security/Privacy/Legal triggers (R6–R9), required fields (R1), injection scan (R10), final decision precedence (R12), grounding of evidence, output filter |
| AI | Whether a catalog product already meets the stated need (`overlap_assessment`), data classes implied only by free text (may add Security/Privacy/Legal with a reason), recommendation and next-step wording |
| Human | Which action to take (send for approvals, request clarification, suggest existing tool, hold), every approval and exception. Overrides need a written reason; every action goes to `runtime/audit_log.jsonl`. |

## 6. Handoff schema (B: Analyst → Reviewer)

The structured handoff is `EvidencePack` (`src/schemas.py`): `need_summary`, `data_classes_implied`, `overlap_assessment`, `vendor_observations`, `uncertainties`, `injection_observed`, `injection_excerpt`, `evidence`, `gaps`, `unsupported_or_unverified`. It is validated with pydantic (one repair, then fallback); prose is never passed between agents. The reviewer also receives the raw tool results, the policy-engine result and only the policy sections the engine cited, and returns a `ReviewerProposal` with an `analyst_audit` (issues found, rejected claims, agreement with the overlap assessment).

Real example: _filled in from `evals/results/runs/staged/` after the evaluation run._

## 7. Stop and escalation conditions

- Every result has `human_review_required = true`; the copilot only recommends.
- Agent loops stop on submission, `max_turns`, `loop_detected` (two all-repeat turns), `invalid_output` (after one repair) or `tool_use_failed`; a failed loop goes to the structured finalizer, then to the rules-only fallback.
- B's supervisor stops on all artifacts present, a failed stage, or `MAX_STAGED_STEPS` = 8.
- LLM unavailable (outage, rate limit, auth): rules-only fallback with the flag `llm_unavailable` and the banner "AI analysis unavailable: showing rule-based result".
- Vendor-risk API unavailable: flag `vendor_risk_unavailable`, both evidence gaps listed, never a favorable status; Security unless the registry review is current and the data is not sensitive (Assumption 13).
- Every run's trace records ordered steps, `stop_reason` and `final_mode` (UI panel "How this was decided"; `evals/results/runs/`).

## 8. Failure mode → control → proof (T0.3)

| Failure mode | Control | Proof |
|---|---|---|
| Wrong tool / skipped evidence | Completeness gate runs any missing required tool | `test_failure_lab::test_skipped_tools_are_gate_filled`; metric `gate_filled` |
| Unsupported conclusion | Policy engine is authoritative; grounding check drops evidence whose numbers, dates or IDs are not in tool results | `test_guardrails` (EvidenceTests); metric `ungrounded_evidence_removed` |
| Loop | `MAX_TURNS`; repeated identical tool calls served from cache and counted; two all-repeat turns → forced finish | `test_failure_lab::test_loop_is_stopped`; `stop_reason=loop_detected` |
| Invalid output | Pydantic validation, one repair, then JSON-schema finalizer, then rules-only fallback | `test_failure_lab::test_invalid_output_repaired`, `::test_invalid_twice_falls_back` |
| Too much autonomy | No action tools; unknown tools rejected; output filter; `human_review_required = true` | `test_failure_lab::test_unknown_tool_rejected`; golden `safety_ok` |
| Unstructured handoff | `EvidencePack` validated; invalid pack → one repair → fallback | `test_staged::test_invalid_pack_falls_back` |
| Supervisor loop | Deterministic `supervisor()` with `MAX_STAGED_STEPS` | `test_staged::test_step_limit_stops` |
| Specialist disagreement | Reviewer records rejected analyst claims in `analyst_audit`; policy engine breaks ties; shown in UI | `test_staged::test_reviewer_audit_recorded`; metric `reviewer_rejections` |
| No escalation | Every result routes to a human; degraded states show banners; actions need confirmation | `test_solution_rules_only`; `test_webapp` |
| No trace | Trace with ordered steps and `stop_reason` saved for every run | `test_trace::test_trace_has_steps_and_stop_reason` |
| Prompt injection in business data | Regex scanner (R10), untrusted-data block, role and flag filtering | `test_injection`; golden G-06, G-16, G-17 |
| Tool / API unavailable | Classified vendor outcomes; never favorable; flags + banners | `test_vendor_tool`; golden G-09, G-21 |
| LLM unavailable or rate-limited | Rules-only fallback with `llm_unavailable`; eval separates `infra_error` from model failure | golden G-22; `test_llm_client` |

## 9. What we deliberately did not build

- An LLM-routed supervisor: routing is deterministic, so it stays in code (Class 13).
- A third agent.
- LangGraph or another framework: plain Python gives exact LLM and tool-call counts, fewer dependencies for the one-command start, and the graph is six deterministic nodes.
- RAG over the policy: the policy is short and structured; the engine encodes it and `lookup_policy_section` returns exact text.
- Real integrations (approvals, purchasing, email, Slack).

## 10. Prompt changes

Prompts are stored in `src/prompts.py` (T16 text plus the D13 additions). Changes from the spec text:

| Change | Why | Evidence |
|---|---|---|
| `SYSTEM_REVIEWER`: "You have no tools; call submit_recommendation exactly once." became "You have no tools; return your recommendation once, as the JSON object requested." | D2.7 makes the reviewer structured-output only; there is no tool to call. | Spec conflict (T16 vs D2.7), not an eval result. |

No prompt was tuned after the evaluation started (prompts frozen before the first LLM eval run).
