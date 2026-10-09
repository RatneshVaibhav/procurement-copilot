# DECISIONS.md: Human rulings on the kickoff report

Recorded 9 Oct 2026, before Phase 0. These rulings answer the kickoff report (F1–F7 confirmed, extras X1–X8, questions Q1–Q3, spec conflicts and proposed defaults).

**Precedence.** Where a decision here differs from `SPEC_FUNCTIONAL`, `SPEC_TECHNICAL` or `SPEC_V2_DELTA`, the decision wins. Nothing here overrides `data/procurement_policy.md`; if a decision seems to conflict with the policy, stop and ask.

**Re-read this file at the start of every phase.**

## Summary

| ID | Source | Ruling | Phase(s) | Spec touched |
|---|---|---|---|---|
| D-01 | Q1 | Registered vendor + vendor-risk 404 → Security + evidence gap (Assumption 15) | P1 | T6.4, R6 |
| D-02 | Q2 | R7 rule 5: replace `helpdeskly` with `help\s?desk\w*` | P1 | R7 |
| D-03 | Q3 | `existing_tool_overlap` is code-only | P2 | T11 step 2, R12 |
| D-04 | Spec gap | LLM-added `prompt_injection_detected` needs a verbatim excerpt | P2 | T11 step 2 |
| D-05 | F5, X5 | Mock API `EXTRA_DATA_DIR` merge in Phase 0, per-request load, canonical name | P0 | T2 F5, T4.1 |
| D-06 | Setup | `pip install openai langsmith` into `.venv` is allowed | P0 | PLAN P0 task 3 |
| D-07 | Ambiguities | All proposed defaults and spec-vs-spec resolutions accepted | All | Various |
| D-08 | X3 | `run_public_evals.py` exits non-zero on any fail or error | P0 | T2 F1 |
| D-09 | X6 | Leave `README.md` until Phase 7 | P7 | PLAN P7 |
| D-10 | Budget | Ask before the 6-run public-runner checks in P3 and P4 | P3, P4 | PLAN P3, P4 checks |

## D-01 (Q1): Vendor-risk 404 for a registered vendor

- **Rule.** If the vendor-risk API returns 404 (`not_found`) for a vendor that **is** in the registry:
  - add **Security** with the reason: "vendor-risk service has no record for a registered vendor; assessment cannot be verified (policy §5, §10)";
  - add the evidence-gap item `"vendor-risk record (not found)"`;
  - do **not** set `conflicting_vendor_evidence`.
- **Unchanged.** 503 / timeout / connection error (`unavailable`) still follows Assumption 13.
- **Unchanged.** 404 for a vendor that is **not** in the registry stays as R6 says (`vendor_not_registered`, treated as new vendor with unknown terms).
- **Changes R6.** R6 currently lets API `not_found` count towards `vendor_cleared`. For a registered vendor, this decision adds Security with the reason above whatever `vendor_cleared` says.
- **Record as Assumption 15** (Assumption 14 is the last one in `SPEC_FUNCTIONAL` §8). List it with the other assumptions in the README in Phase 7.

## D-02 (Q2): No dataset product names in R7

- In R7 integration rule 5, replace `helpdeskly` with the generic stem `help\s?desk\w*`.
- Rule 5 becomes: `crm|salesforce|hubspot|help\s?desk\w*|zendesk|support tickets?` → `customer_pii`.
- General rule: no product names from this dataset appear in rule patterns.

## D-03 (Q3): Overlap flag is code-only

- `existing_tool_overlap` is set only by deterministic code (Assumption 11).
- In T11 step 2, an LLM-proposed `existing_tool_overlap` that code did not set is dropped and logged as `llm_flag_dropped`.
- The AI's overlap judgement affects only `use_existing_tool`, through `overlap_assessment` (R12 / T11 step 4).

## D-04: LLM-added injection flag needs a verbatim excerpt

- Accept an LLM-added `prompt_injection_detected` only if its `injection_excerpt` appears verbatim (case-insensitive) in untrusted text returned by tools.
- Otherwise drop it and log `llm_flag_dropped`.
- Flags set by the deterministic injection scan are never dropped.

## D-05 (F5, X5): Mock API data merge in Phase 0

- The mock API's `EXTRA_DATA_DIR` merge is built in Phase 0, together with F5.
- The mock loads data **per request**, not at import, so env changes between eval cases take effect.
- The mock returns the **canonical** vendor name from its record, not the name as typed in the URL (X5).

## D-06: Dependencies

- Allowed: `pip install openai langsmith` into `.venv`. In `requirements.txt`, set their lower bounds to the installed versions, as PLAN Phase 0 task 3 says.

## D-07: Proposed defaults accepted

- All defaults proposed under "Ambiguities" in the kickoff report, and all its spec-vs-spec resolutions, are accepted as written.
- **Known limitation:** the AC-2.2 status-grounding gap. List it under known limitations in the README in Phase 7.
- **Gap in this record:** the kickoff report was not saved to the repo, so its individual defaults are not listed here. Until they are added, apply CLAUDE.md "How to work" rule 5 (most conservative option) to any ambiguity and record the choice under "Open questions".

## D-08 (X3): Public runner exit code

- `evals/run_public_evals.py` exits non-zero when any case fails or errors.
- Scoring logic is unchanged.

## D-09 (X6): README timing

- Do not edit `README.md` before Phase 7.

## D-10: Real-LLM runs for the public runner

- Ask the human before running the 6-run public-runner checks in Phase 3 (single) and Phase 4 (staged).
- This adds to the CLAUDE.md budget rule (ask before more than 4 real requests outside the eval).
