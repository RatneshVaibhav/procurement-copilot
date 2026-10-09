# PLAN.md: Build plan v2 (spec-driven, phase by phase)

**Deadline.** At the end of Class 13 the instructor moved Assessment 3 to **Sunday 11 Oct 2026, night**. The brief PDF still says 8 Oct; confirm the exact time on the academic calendar. This plan targets **form submitted by Sun 21:00 IST**.

**Docs.** `docs/SPEC_FUNCTIONAL.md` (F), `docs/SPEC_TECHNICAL.md` (T), `docs/SPEC_V2_DELTA.md` (D, wins over T where they differ), rules in `CLAUDE.md`.

**Rule (D-11, replaces the per-phase STOP).** Each phase ends with checks, a `diff-reviewer` pass, a commit and 5–10 lines in `docs/BUILD_LOG.md`; then work continues straight into the next phase. Pause only for the four D-11 reasons (see `docs/DECISIONS.md`). Every "Human:" step below goes into the "Human checklist" at the end of `docs/BUILD_LOG.md` and is not waited for. Stop only when Phase 7 is complete (excluding the push).

---

## Schedule (IST)

| When | Phase | Milestone |
|---|---|---|
| Fri 20:00–20:45 | P0 Setup, scaffold fixes, smoke test | Key works, model ID verified |
| Fri 20:45–23:30 | P1 Deterministic core | Engine reproduces the golden table (deterministic aspects) |
| Sat 09:00–10:15 | P2 Guardrails, fallback, trace, adapter | **Safety net**: valid rules-only product. Human pushes. |
| Sat 10:15–13:00 | P3 LLM client, bounded loop, Architecture A, failure lab | A: public 6/6 |
| Sat 14:00–15:45 | P4 Architecture B (supervisor + 2 specialists) | B: public 6/6 |
| Sat 15:45–18:00 | P5 Eval harness, decision rule, rules-only run, start LLM run | **Prompts frozen** |
| Sat night | LLM eval runs in the background (`--resume` as quota allows) | |
| Sun 09:00–12:00 | P6 Web app | |
| Sun 12:00–15:30 | P7 Docs, clean-environment test, secret scan | Repo public |
| **Sun 16:00** | **CODE FREEZE** | Only fixes for failing checks after this |
| Sun 16:00–20:00 | P8 Human: agent log, proofread, memo in own voice, submit | **Submitted by 21:00** |

If you start late, shift rows by the same amount and apply the cut lines earlier. Never move the code freeze past Sun 18:00.

---

## LLM budget (decide before Phase 3)

One full trial is ~22 LLM cases × (A ≈ 3 calls + B ≈ 4 calls) ≈ 150 calls. `run_all.py` prints a token projection after two runs (D11.4); trust that number over this estimate.

| Option | Fits by Sunday? | Notes |
|---|---|---|
| Groq free, `openai/gpt-oss-20b` | Unlikely for a full trial | 8K tokens/min, 200K tokens/day per model. Prompt caching helps (D3). Spread runs over Sat night + Sun with `--resume`. |
| **Groq Developer plan** (pay as you go) | Yes | gpt-oss-20b is $0.075 / $0.30 per M input/output tokens; a full eval is likely under $1. Needs a card. |
| **Gemini 2.5 Flash free** (`LLM_PROVIDER=gemini`) | Likely | Generous tokens/min; daily request cap of a few hundred or more. |

Rules: never mix providers or models across architectures in reported numbers. During P3–P4 use at most ~20 real runs. Unit tests never call a real LLM.

---

## Kickoff prompt (paste into Claude Code first)
```
Read CLAUDE.md, then docs/SPEC_FUNCTIONAL.md, docs/SPEC_TECHNICAL.md (start at T0), docs/SPEC_V2_DELTA.md and PLAN.md.
Before writing any code:
1. Inspect the repository and summarise the current architecture in 10 lines.
2. List every scaffold defect you find. Compare with T2 F1–F7 and report anything extra.
3. List anything in the specs that conflicts with the code, the policy, or another spec file, and any ambiguous item.
4. Confirm the Phase 0 task list and the files you will touch.
Do not modify any file until I reply "go".
```

---

## Phase 0: Setup and scaffold fixes (≈45 min)
**Spec:** T1, T2, T3, D1, D2, D4.

**Tasks**
1. `.gitignore`: add `runtime/`, `.env`, `.venv/`, `.claude/settings.local.json`; remove `evals/results_*.csv` (F2). Keep the rest of `.claude/` tracked.
2. Scaffold fixes F1, F4 (basic classified outcomes), F5, F7 (T2). `run_local.py` starts the mock API and a placeholder FastAPI app returning "ok" at `/`. Full UI comes in P6.
3. Delete the Streamlit `app.py`. `requirements.txt`: remove `streamlit`; add `openai` and `langsmith` with lower bounds, pinned to the versions you install. Update `verify_setup.py` `REQUIRED_MODULES` (no streamlit; add openai).
4. `src/config.py` (T3): `get_settings()` read at call time; `REFERENCE_DATE` and `POLICY_VERSION` parsed from the policy file.
5. `.env.example` exactly as T3.
6. `scripts/smoke_llm.py` (standalone; raw `openai` SDK):
   - print provider, base_url, model; list models and warn if `MODEL_NAME` is absent;
   - one tool-call round trip with a dummy tool (`tool_choice="auto"`, prompt asks the model to call it); print the parsed arguments;
   - one `response_format` JSON-schema call (strict when D2 says so) on a tiny schema; print the parsed object;
   - check `reasoning_effort` acceptance;
   - print latency, usage (including cached tokens if present) and the `x-ratelimit-*` headers;
   - exit non-zero with a clear message on any failure.

**Checks:** `python verify_setup.py` → PRE-FLIGHT PASSED. Starter tests pass. Start `run_local.py`, curl `/` and the mock `/health`, then stop it.
**Human:** `cp .env.example .env`, add your key, run `python scripts/smoke_llm.py`. Note the model and rate-limit headers in `docs/AGENT_LOG.md`. Decide the LLM budget option.
**Log to BUILD_LOG and continue (D-11).**

## Phase 1: Deterministic core (≈2 h 45)
**Spec:** T4, T5, T6.1–T6.4, D5.

**Tasks**
1. `src/normalize.py` (T4.2).
2. `src/data_access.py` additions (T4.1): `EXTRA_DATA_DIR`, runtime submissions, `norm_key`, `find_vendor`, `find_employee`.
3. `src/injection.py` (R10).
4. Hardened `src/vendor_client.py` (T6.4).
5. `src/schemas.py`: `PolicyResult`, `VendorStatus`, the T8 models and the D6 additions.
6. `src/policy_engine.py`: R0–R12 exactly as written.
7. `src/tools.py`: the 6 tools, `RunContext`, cache, tool log, evidence corpus (T6); descriptions per D5; per-agent allowlists; out-of-scope and unknown calls rejected (D5).
8. Tests: `test_policy_engine.py`, `test_injection.py`, `test_vendor_tool.py` (T15), `test_tools.py` (scoping + rejection).
9. `tests/test_golden_deterministic.py`: for all 23 golden cases (fixtures via `EXTRA_DATA_DIR`, faults simulated), assert approvals and flags with exact-set semantics and the missing-information groups and `max_items`. Skip only the aspects in each case's `requires_ai` and the `llm_unavailable` flag.

**Checks:** all tests pass; the T5 expected-output table is reproduced exactly.
**Human:** read the engine's evidence strings for REQ-1007 (conflict) and REQ-1009 (unavailable), and two tool descriptions. Would a reviewer understand them?
**Log to BUILD_LOG and continue (D-11).**

## Phase 2: Guardrails, fallback, trace, adapter (≈1 h 15) → safety net
**Spec:** T11, T12, T13, D10.

**Tasks**
1. `src/guardrails.py` (T11, including the output filter, grounding check and T11.1 templates).
2. `src/fallback.py` (T12).
3. `src/tracing.py` (D10): step recorder; LangSmith shim that is a no-op unless configured.
4. `src/solution.py`: `handle_request_with_trace(request_id, architecture, mode)`; `handle_request` calls it. Until agents exist, both architectures use the fallback.
5. Tests: `test_guardrails.py`, `test_solution_rules_only.py`, `test_trace.py`.
6. Commit: `"deterministic baseline: rules-only copilot"`.

**Checks:** with `LLM_SIMULATE_OUTAGE=1`, `python evals/run_public_evals.py --architecture single` → **6/6**, same for staged.
**Human:** create the GitHub repo and push. A valid, honest, AI-less product now exists; everything after this improves it.
**Log to BUILD_LOG and continue (D-11).**

## Phase 3: LLM client, bounded loop, Architecture A (≈2 h 45)
**Spec:** T7, T8, T9, T16, D1–D4, D7, D8, D12, D13.

**Tasks**
1. `src/structured.py` (D2.1) + `tests/test_structured.py`.
2. `src/llm_client.py`: `chat()` and `chat_structured()`; throttle, retries, `LLMRateLimited`, header-aware waits, token accounting, simulate-outage hook, `reasoning_effort` handling (T7, D1–D4). Optional LangSmith wrap (D10). `tests/test_llm_client.py`.
3. `tests/fakes.py::ScriptedLLM` (D12).
4. `src/prompts.py`: T16 text verbatim plus D13 changes; static system prompts (D3).
5. `src/agents/loop.py` (D8) including the finalizer (D2.4).
6. `src/agents/single_agent.py` (D7 card A) with the completeness gate (T6.3). Wire into `solution.py`.
7. `tests/test_failure_lab.py` (D12, A rows).
8. `scripts/run_one.py <request_id> --arch single|staged`: prints the final decision, raw proposal, `stop_reason`, `final_mode`, the step trace, guardrail events and tokens.

**Checks**
- Unit tests pass with no network. `smoke_llm.py` still passes.
- `run_one.py` on REQ-1006, 1008, 1009 (3 real runs). Expected: 1006 → `request_clarification` + injection flag, no CFO; 1008 → `use_existing_tool`; 1009 → unavailable surfaced.
- Public runner, single → 6/6.

**Human:** read the 3 outputs and step traces. Is the recommendation useful to a reviewer? Tune prompts only for a concrete problem and log each change in `docs/architecture.md` → "Prompt changes".
**Log to BUILD_LOG and continue (D-11).**

## Phase 4: Architecture B, sequential specialists (≈1 h 45)
**Spec:** T10, D6, D7, D9, D13.

**Tasks**
1. `src/agents/staged_agent.py`: `StagedState`, deterministic `supervisor()`, nodes analyst / gate / policy_engine / reviewer / finalize / fallback (D9). Reviewer via `chat_structured(ReviewerProposal)`.
2. Wire into `solution.py`.
3. `tests/test_staged.py` (D12).

**Checks:** unit tests pass. `run_one.py --arch staged` on REQ-1006 and 1008 (2 real runs); the trace shows supervisor route reasons in order. Public runner, staged → 6/6.
**Log to BUILD_LOG and continue (D-11).**

## Phase 5: Evaluation harness (≈2 h 15) → prompts frozen
**Spec:** T14, D11.

**Tasks**
1. `evals/run_all.py` and `evals/score.py` (T14 + D11): rules-only column, per-case matrix, `--resume`, `--retry-infra`, `infra_error`, budget print, new summary rows, design-ladder column names, `summary.md` / `summary.json`.
2. `evals/render_walkthroughs.py` (D11.8).
3. `evals/results/manual_review.md` template: 5 runs per architecture (REQ-1002, 1004, 1006, 1007, 1008 + one fault case); columns: recommendation sensible / evidence checks out / anything misleading / tone.
4. Write `evals/DECISION_RULE.md` from D11.7 as written (D-13) and commit it before step 3 of the run order.
5. Update `evals/README.md`.

**Run order**
1. `python evals/run_all.py --no-llm`
2. Commit `DECISION_RULE.md` (D-13); prompts are frozen from here (D-11).
3. `python evals/run_all.py --trials 1 --resume` (repeat with `--resume` / `--retry-infra` until no rows are missing or infra errors).
4. If budget allows: `python evals/run_all.py --trials 3 --cases G-02,G-06,G-07,G-08,G-17,G-23 --resume`.
5. `python evals/render_walkthroughs.py`. Commit `evals/results/`.

**Human:** read `summary.md` and every failure line. Fill `manual_review.md` while runs proceed. Remember D11.9: a change after the full run means re-running both architectures, or documenting it instead.
**Log to BUILD_LOG and continue (D-11).**

## Phase 6: Web app (≈3 h)
**Spec:** T17, D14, F §5 (US-1 to US-5).

**Tasks**
1. `webapp/main.py` (T17 API; `/api/analyze` adds `trace_steps` and `trace_meta`).
2. `webapp/static/*`: queue, request card, run bar, banners, recommendation, approvals with reasons, flags, missing / could-not-verify, evidence table, **"How this was decided" panel**, footer, action bar, confirmation modal, success state, audit history. Empty, loading and error states.
3. "New request" form (US-6) only if P0–P5 are done by Sun 10:30. "Compare both" (US-7) only if everything else is done.

**Checks (manual, in the browser):**
1. REQ-1006 → injection banner, clarification; choosing "Send for approvals" requires an override reason.
2. REQ-1007 → conflict shown side by side.
3. REQ-1008 → "Suggest existing tool" highlighted.
4. Mock API stopped (or a wrong `VENDOR_RISK_BASE_URL`), run REQ-1001 → unavailable banner, no favorable status.
5. Trace panel shows ordered steps and a stop reason; for staged, supervisor route reasons and the reviewer audit.
6. Confirming an action writes an audit-log line.
7. XSS: a justification of `<img src=x onerror=alert(1)>` renders as plain text.
**Log to BUILD_LOG and continue (D-11).**

## Phase 7: Docs and clean-environment test (≈3 h 30; Claude Code drafts, you review in P8)
**Spec:** T18, D15, F §8–9.

**Tasks**
1. `docs/architecture.md` with all D15 sections.
2. `README.md` with exactly these sections:
   1. What it does (3 lines)
   2. Setup and run (one command)
   3. Product workflow
   4. Architecture (design ladder in one paragraph, diagram, A vs B)
   5. Tools and agents (agent cards summary, tool scope table)
   6. Assumptions (copy F §8)
   7. Evaluation (method, `summary.md` table, how to reproduce, budget/infra notes)
   8. Architecture comparison (link `scenario_walkthroughs.md`)
   9. Ship decision (apply `DECISION_RULE.md` to the numbers)
   10. Known limitations (F §9 open questions, rate limits, small eval set, no real integrations, single trial if applicable)
3. `docs/DECISION_MEMO.md` (≤ 500 words, template `templates/architecture_decision.md`) using `/eval-report`. Only numbers from `evals/results/`. Apply the pre-registered rule honestly, even if it says ship A. Print the word count.
4. **Clean-environment test:** fresh clone into a temp dir → new venv → `pip install -r requirements.txt` → `python verify_setup.py` → `python -m unittest discover -s tests` → `python evals/run_all.py --no-llm` (writing to a temp results dir) → `python run_local.py`, load the page, stop.
5. **Secret scan:** `git log -p | grep -iE "api[_-]?key|AIza|gsk_|lsv2_"` finds nothing beyond `.env.example` placeholders; `git ls-files .env` prints nothing.

**Human:** push and make the repository **public**.
**End of build (D-11): final summary with eval headline numbers and the human checklist. Code freeze Sun 16:00.**

## Phase 8: Human only (Sun 16:00–21:00)
| Time | Task |
|---|---|
| 16:00–17:00 | Finish `docs/AGENT_LOG.md` (Class 10 evidence: inspection prompt, a plan you corrected, one diff you reviewed, one wrong assumption you caught, one decision you overruled). |
| 17:00–18:30 | Rewrite `DECISION_MEMO.md` in your own voice. Proofread the README. Check every number against `evals/results/summary.md`. Recount memo words (≤ 500). Confirm all 10 README sections. |
| 18:30–19:00 | Rehearse defending 4 calls: the decision rule, assumption 11 (overlap flag), assumption 13 (API down + not sensitive), and why the ship choice is not "more agents". |
| 19:00–19:30 | PDF only if the Google Form asks for an upload (plain, ≤ 2 pages, from the memo). |
| 19:30–20:30 | Final push. `git status` clean, `.env` untracked, repo **public** (check in a private window), Mermaid renders, README run steps work. |
| 20:30–21:00 | **Submit** the repo URL on the Google Form. Screenshot the confirmation. |

Open the Google Form at the safety-net milestone (Sat ~10:15) to see exactly what it asks for.

---

## Cut lines (clock-triggered; apply without debate)
| If by... | ...this isn't done | Then drop |
|---|---|---|
| Sat 11:00 | P2 safety net | US-7 compare view, US-6 new-request form, LangSmith |
| Sat 18:30 | P4 Architecture B | B's repair attempt; keep B minimal (analyst → gate → engine → reviewer) |
| Sat 20:00 | P5 harness | `--trials 3` subset and walkthrough renderer (write 2 walkthroughs by hand) |
| Sun 13:00 | P6 web app | All polish. Keep queue, analysis result, trace panel (steps list only), action + modal, audit log |
| Sun 16:00 | anything | Stop building. Write what exists honestly under "Known limitations" |

**Never cut:** guardrails, fallback, completeness gate, step limits and `stop_reason`, failure-lab tests, the golden eval on both architectures, the pre-registered decision rule, the one-command start, the 10 README sections, the memo.

## Definition of done (maps to the brief's scoring)
| Brief item | Evidence in repo | Lecture link |
|---|---|---|
| Product + workflow (15%) | Queue → analysis → trace panel → confirm → audit log; README workflow | C9, C11, C12 HITL |
| End-to-end product (20%) | `python run_local.py`; clean-environment test passed | C11 |
| Agent + tool design (20%) | 6 scoped tools with descriptions; agent cards; A bounded loop; B supervisor + specialists; `docs/architecture.md` | C12 anatomy, C13 patterns + tool scoping |
| Reliability + human controls (15%) | Guardrails, gate, fallback, failure-lab tests, no action tools, approval UX with reason, audit log, fault cases | C12 + C13 failure labs |
| Evaluation + comparison (20%) | `run_all.py`; 23 golden cases; rules-only baseline; raw vs final metrics; pre-registered rule; walkthroughs; manual review | C13 evaluation |
| Engineering + communication (10%) | Tests, README, ≤ 500-word memo, no secrets, `AGENT_LOG.md` | C10 |
