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
| D-07.1–D-07.11 | Ambiguities | Proposed defaults and spec-vs-spec resolutions, listed one by one | All | Various |
| D-08 | X3 | `run_public_evals.py` exits non-zero on any fail or error | P0 | T2 F1 |
| D-09 | X6 | Leave `README.md` until Phase 7 | P7 | PLAN P7 |
| D-10 | Budget | Real LLM runs allowed without asking (replaced; see D-11) | P3–P5 | PLAN P3, P4 checks |
| D-11 | Working mode | Run Phases 0–7 continuously; pause only for the four listed reasons | All | CLAUDE.md, PLAN.md, /phase skill |
| D-12 | Provider | Groq, `openai/gpt-oss-20b`, free tier, `reasoning_effort=low`, both architectures | P0–P5 | D1, D4 |
| D-13 | Decision rule | D11.7 default rule as written, committed before the first LLM eval | P5 | D11.7 |
| D-17 | Budget | Free tiers only: Gemini 2.5 Flash for the reported eval, Groq gpt-oss-20b for development checks (amends D-12) | P3–P5 | D1, D4, D11 |

D-01, D-02 and D-04 below were proposed in the kickoff report and are **accepted as written** (9 Oct 2026).

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

## D-07: Proposed defaults (numbered)

- **D-07.1 Reference date.** If the T3 regex fails on `data/README.md`, use a second regex matched to its wording.
- **D-07.2 Public runner output.** `evals/run_public_evals.py` writes `evals/results/public_<arch>.csv` and auto-starts the mock API only when the URL host is local.
- **D-07.3 Smoke test.** `scripts/smoke_llm.py` warns when the resolved model ID is not in the provider's model list.
- **D-07.4 Registry review date.** Registry "Approved" with a blank or future review date counts as not current: add Security, but do not set `vendor_review_expired`.
- **D-07.5 API outcomes.** API unavailable: add both evidence-gap items. API 404: add `"vendor-risk record (not found)"`.
- **D-07.6 `--no-llm`.** `evals/run_all.py --no-llm` runs rules-only mode only; the summary merges it with stored LLM results.
- **D-07.7 Grounding.** Implement the T11 grounding check as written (numbers, dates, IDs). List the AC-2.2 status-grounding gap under known limitations in the README in Phase 7.
- **D-07.8 Unknown request.** An unknown `request_id` returns a valid `request_clarification` decision instead of raising.
- **D-07.9 Phase 2 fallback.** In Phase 2, before the agents exist, the fallback adds `llm_unavailable`.
- **D-07.10 Python.** Run Python with `.venv/bin/python`; documented commands stay `python ...`.
- **D-07.11 Spec-vs-spec.**
  - Forced `tool_choice` is removed (D1/D8/D9).
  - The Analyst has 5 tools (D5), not 4 (T18 diagram).
  - Use the D11.1 design-ladder column names.
  - Commit messages follow PLAN.
  - F1 changes only the public runner's startup, output path and exit code (D-08); scoring and CLI stay unchanged.

## D-08 (X3): Public runner exit code

- `evals/run_public_evals.py` exits non-zero when any case fails or errors.
- Scoring logic is unchanged.

## D-09 (X6): README timing

- Do not edit `README.md` before Phase 7.

## D-10: Real-LLM runs (replaced 9 Oct 2026)

- Real LLM runs are allowed without asking.
- Up to 25 real requests across Phases 3–4 (smoke test, `run_one`, public runners), then the planned eval runs (PLAN Phase 5 run order).
- This replaces the CLAUDE.md rule "ask before more than 4 real requests outside the eval".

## D-11: Continuous working mode

- Run Phases 0 to 7 continuously. For each phase, follow the `/phase` procedure: tasks, tests, checks, `diff-reviewer`, commit. Then append 5–10 lines to `docs/BUILD_LOG.md` (summary, tests, reviewer verdict, deviations, open questions) and continue straight into the next phase.
- **Pause only for:**
  1. a business-rule or policy question that DECISIONS.md does not cover, where the conservative choice is unclear;
  2. a failing check that cannot be fixed in 3 honest attempts (never weaken a test);
  3. LLM provider or key errors, or a budget projection showing the full eval cannot finish by Sun 11 Oct 12:00 IST;
  4. anything that needs secrets or a `git push`.
- For everything else: choose the most conservative option, record it here as "D-1x (proposed)", and keep going.
- Run long commands (evals) in the background, e.g. `nohup .venv/bin/python evals/run_all.py --trials 1 --resume > runtime/eval_run.log 2>&1 &`. Continue with the next phase while they run, check the log between tasks, and re-run with `--resume` / `--retry-infra` after rate-limit stops.
- Prompts freeze before the full LLM eval. After that, do not change prompts or agent code unless both architectures are re-run.
- After a context compaction: re-read CLAUDE.md, `docs/DECISIONS.md` and `docs/BUILD_LOG.md`, then continue from the next unfinished task.
- Human-only items (browser UI checks, pushing to GitHub, AGENT_LOG, rewriting the memo in the human's voice, submission) go in the "Human checklist" at the end of `docs/BUILD_LOG.md`. Do not wait for them.
- Stop only when Phase 7 is complete (excluding the push), with one final summary: eval headline numbers and the human checklist.

## D-12: LLM provider

- Groq, `openai/gpt-oss-20b`, free tier, `LLM_REASONING_EFFORT=low`.
- The same provider and model for both architectures.
- If the budget projection fails, pause (D-11 rule 3).

## D-13: Decision rule

- Use the D11.7 default rule as written. Write it to `evals/DECISION_RULE.md` and commit it before the first LLM eval run.

## D-14 (proposed): Vendor-risk 404 with sensitive data → Privacy

- R8 covers API `ok` (cross-region) and API `unavailable` (residency unverified), but is silent on API `not_found`. A 404 gives no residency information either, so policy §6 ("may be stored outside the region") and §10 ("do not infer a favorable status") point to Privacy.
- **Rule.** If the API returns 404, **or** returns a record without a boolean `stores_data_outside_region`, and the request involves PII or confidential documents → add **Privacy** with the reason "Data residency unverified (...)" (§6, §10). No Legal from this rule (no cross-region issue is identified).
- Golden impact: none (G-15 already requires Privacy through customer PII).

## D-15 (proposed): Smaller conservative choices in the deterministic core

- R1 `"product or vendor name"` is listed when **either** the product name or the vendor name is missing.
- A missing vendor name skips the vendor-risk API call (`outcome = not_checked`); the vendor is not cleared, so Security and Legal (terms unknown) are added.
- Unknown `data_access_level` keyword fallback (R7) collects **every** matching class, not just the first.
- The R10 scan also covers every free-text field of the vendor-risk API record and the purchase-history notes of catalog candidates (superset of R10).
- Tools that take `request_id` refuse any ID other than the request being analysed (error result, not executed).
- R5 agent keywords shorter than 3 characters are ignored (a 1–2 letter keyword would match every catalog row); at most 5 are used.
- R7 unknown-level keyword fallback matches whole tokens (plurals allowed), so `product_usage` is not `prod` and `reporting` is not `repo`; such values stay `unrecognized_data_access_level` (Security).
- Vendor-risk API error text written by the server is untrusted: engine reasons and evidence use only code-derived text (`HTTP 503`, `timeout`, `connection error`); the server's detail is kept under `untrusted_text` and scanned (R10).
- The `evaluate_policy_rules` tool returns a compact view to the LLM (approvals with reasons, flags, missing information, tier, data classes, vendor summary, rules decision); the full `PolicyResult` stays in the run context for guardrails and the UI (token budget, D4).

## D-16 (proposed): Guardrail interpretations (T11)

- **use_existing_tool and contradictory overlap entries.** R12 step 2 counts an `overlap_assessment` entry whose `software_id` is in `overlap_flag_candidates` and `covers_stated_need = true`, **except** when `relationship = "related_not_substitute"` (a related, non-substitute product cannot cover the need; the pair is contradictory). `same_product_expansion` + covers is allowed, because a requested upgrade (e.g. a "Pro" tier) may already be covered by the licensed product; OUTPUT_RULES in the prompt handle the seats/add-on case. **Open question for the human:** keep this narrow exclusion, or follow R12 literally.
- **Grounding check strictness (D-07.7).** Tokens match as whole tokens (digit/ID boundaries, so `1500` does not match inside `15000`), full `YYYY-MM-DD` dates must appear whole, and the grounding corpus leaves out values the agent chose itself (catalog keywords, vendor names other than the request's).
- **Next-step wording after a code correction.** The proposal's `next_step` names who acts next. If code restored or dropped any approval role, the T11.1 template is used instead, so the next step never lists the wrong approvers. The recommendation sentence follows T11 as written.
- **Specialist flags follow accepted roles.** When an LLM-added Security/Privacy/Legal role is accepted, its flag is added even if the proposal forgot to list it (R11: the specialist flags follow the roles).
- **Injection excerpt minimum.** D-04's verbatim check also requires at least 8 non-space characters, so a trivial excerpt cannot match by accident. The `injection_observed = true` field counts as proposing `prompt_injection_detected`.
- **Wording filters.** Proposal `recommendation` / `next_step` longer than 400 characters, or matching an R10 injection pattern as well as the T11 output filter, fall back to the template.

## D-17: Two free providers, one per job (human decision, Sat 10 Oct 2026; amends D-12)

- The human does not want to pay for an LLM plan. The Groq free tier (200K tokens/day) cannot fit the full eval: gpt-oss-20b on Groq makes one tool call per turn, so a run takes 6–7 calls and ~17K tokens (BUILD_LOG, Phase 3).
- **Reported eval:** Gemini 2.5 Flash, free tier, for **both** architectures. Every number in `evals/results/summary.md`, the README and the memo comes from this one provider and model.
- **Development checks:** Groq `openai/gpt-oss-20b`, free tier, `reasoning_effort=low`, for the P3/P4 real runs (`run_one`, public runner). Optionally, a secondary A-vs-B run on a small case subset, both on Groq, reported as a separate, clearly labelled table.
- **Never mixed:** a comparison never combines providers, and a rate-limited run never switches provider mid-run (it falls back to rules only and is recorded as `infra_error`).
- Scripts take `--provider groq|gemini` (sets `LLM_PROVIDER` for that process); the trace records provider and model.
- The human adds `GEMINI_API_KEY` to `.env` before Phase 5. If Gemini's free daily request cap proves too low for the eval, pause again (D-11 rule 3).
