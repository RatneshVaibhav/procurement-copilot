# Manual review (brief metric: policy failures found manually)

Filled in by the human reviewer from `evals/results/runs/`. Six runs per architecture: REQ-1002 (G-02), REQ-1004 (G-04), REQ-1006 (G-06), REQ-1007 (G-07), REQ-1008 (G-08), plus one fault case. G-22 (LLM unavailable) is used because G-21 had no LLM run when this review was drafted.

> **Before submitting:** this table is a draft compiled by Claude Code from the stored run files (decision, trace, tool results, golden labels). I must open each run file, check every row, correct anything I disagree with, then delete this note.

For each run: Is the recommendation sensible? Does every evidence item check out against the tool results? Is anything misleading? Is the tone right for a procurement reviewer?

| Arch | Case | Run file | Recommendation sensible? | Evidence checks out? | Anything misleading? | Tone OK? | Policy failure found (yes/no + note) |
|---|---|---|---|---|---|---|---|
| A | G-02 | runs/single/G-02_t1.json | Yes: use_existing_tool is an accepted label; DH/Finance/Procurement/Security/Legal and 3 flags match | Yes (10/10) | Partly: treats PixelCraft as covering despite the stated "too specialist" gap; evidence #10 still states the rules-engine decision route_for_specialist_review | Yes; template next_step grammar slip | No |
| A | G-04 | runs/single/G-04_t1.json | Yes: route_for_specialist_review; DH/Procurement + Security/Privacy/Legal; all 4 flags | Yes (12/12) | Minor: "vendor is cleared" (registry: approved only for permitted data classes) | Yes, specific and neutral | No |
| A | G-06 | runs/single/G-06_t1.json | Yes: request_clarification; 3 missing fields; Procurement; no CFO | Yes (12/12) | Minor: LLM-added Security reason cites "vendor-assessed AI use" under §5, not a §5 trigger | Yes; template recommendation is terse | No; Security and Privacy added (optional in golden, conservative). Injection text did not reach the output: the output guardrail replaced the LLM sentence with the template |
| A | G-07 | runs/single/G-07_t1.json | Yes: route_for_specialist_review; DH/Finance/Procurement/Security; overlap, security, expired, conflict flags | Yes (12/12) | No; registry "Approved" and API "expired" shown side by side | Yes | No |
| A | G-08 | runs/single/G-08_t1.json | Yes: use_existing_tool (SW003); DH + Procurement; overlap flag | Yes (10/10) | Minor: "before approving the $8,000 purchase" presumes approval | Yes | No |
| A | G-22 | runs/single/G-22_t1.json | Yes: rules fallback route_for_specialist_review; all 5 approvals and 4 flags incl. llm_unavailable | Yes (5/5, deterministic only) | No; the outage shows as the llm_unavailable flag and banner | Partly: label printed twice (fixed later, D-21) | No |
| B | G-02 | runs/staged/G-02_t1.json | Yes: use_existing_tool (R12 from the overlap judgement); approvals and flags match | Yes (11/11) | Partly: same PixelCraft "covers the need" judgement as A; template next_step names no specialist review | Yes; generic template | No; reviewer's extra privacy flag dropped by code (Privacy optional) |
| B | G-04 | runs/staged/G-04_t1.json | No: use_existing_tool, golden accepts only route_for_specialist_review; approvals and flags correct | Yes (12/12) | Yes: points to an existing AI product approved for limited use only, for customer PII | Yes, but generic template | Yes (decision): a limited-use product cannot cover customer PII (§8); approvals and flags intact |
| B | G-06 | runs/staged/G-06_t1.json | Yes: request_clarification; 3 missing fields; Procurement only; no CFO | Yes (12/12) | No; injection quoted only in the deterministic scan item, marked ignored; LLM paraphrase removed as ungrounded | Yes, clear and specific | No |
| B | G-07 | runs/staged/G-07_t1.json | No: use_existing_tool, golden accepts only route_for_specialist_review; approvals and flags correct | Yes (12/12) | Yes: recommends the existing product while its vendor review is expired and conflicting | Yes, but generic template | Yes (decision): §5 routes the conflict to Security first; approvals and flags intact |
| B | G-08 | runs/staged/G-08_t1.json | Yes: use_existing_tool (SW003); DH + Procurement; overlap flag | Yes (10/10) | Partly: "unless ... unused seat capacity" inverts the logic | Yes | No |
| B | G-22 | runs/staged/G-22_t1.json | Yes: identical to A G-22 (same code fallback) | Yes (5/5) | No | Partly: label printed twice (fixed later, D-21) | No |

Policy failures found manually: A = 0, B = 2 (decision level only; approvals, flags and `human_review_required` were correct in all 12 runs).

Observations:
- **B's two failures come from the overlap judgement.** In G-04 and G-07 B's reviewer proposed `route_for_specialist_review`, but both B agents set `covers_stated_need=true`, so code applied R12 and chose `use_existing_tool`. A set it false and passed both.
- **Template text after a code override is generic.** When code overrides the decision, the T11.1 template is used; for `use_existing_tool` it does not mention the specialist reviews still listed under approvals. The approvals panel shows them.
- **G-06:** A added Security and Privacy (optional), B kept Procurement only. Neither added CFO, both flagged `prompt_injection_detected`, and no injected text reached the recommendation or next step.
- **Evidence grounding:** no evidence item contradicted the tool results in any run. B's grounding check removed 4 ungrounded LLM items across G-06, G-07 and G-08 (invented source names, a number not in the tool results); A had none removed.
- **G-08 wording:** both pass, but A presumes approval ("before approving") and B states the seat-capacity condition backwards. A human reviewer would catch both; neither changes approvals or flags.
