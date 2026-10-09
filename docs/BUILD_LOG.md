# BUILD_LOG.md: Phase-by-phase build log

Written by Claude Code under D-11 (continuous mode). Each phase appends 5–10 lines: summary, tests, diff-reviewer verdict, deviations, open questions. Human-only items are collected in the "Human checklist" at the end; the build does not wait for them.

## Phase log

### Phase 0: Setup and scaffold fixes (Fri 9 Oct, 19:55–20:25 IST)
- Summary: `.gitignore` (F2), mock API path route + case-insensitive lookup + per-request `EXTRA_DATA_DIR` merge + canonical name (F5, D-05), classified vendor client (F4, T6.4), public runner auto-starts a local mock, writes `evals/results/public_<arch>.csv`, exits non-zero (F1, D-07.2, D-08), `run_local.py` starts mock + placeholder web app from `VENDOR_RISK_BASE_URL`/`APP_PORT` (F7), Streamlit removed, `openai>=3.27.0` + `langsmith>=0.14.6` added, `src/config.py` (T3, D-07.1 README regex), `.env.example` as T3, `scripts/smoke_llm.py`. New shared helper `mock_api/launcher.py`.
- Tests: 23 pass (starter 10 + `test_config` 9 + 4 new mock API tests). `verify_setup.py` PRE-FLIGHT PASSED. `run_local.py` served `/` = ok and mock `/health`; stopped cleanly on SIGTERM.
- Smoke test (1 real run): Groq `openai/gpt-oss-20b` listed; tool call OK; strict JSON-schema output OK; `reasoning_effort=low` accepted; headers: 8,000 tokens/min, 1,000 requests/day; ~550 ms per call.
- diff-reviewer: PASS with 5 minor fixes, all applied (runner exits 2 if the mock cannot start; smoke-test clear messages; launcher service label; `REFERENCE_DATE`/`POLICY_VERSION` lazy aliases; unknown `LLM_PROVIDER` leaves the LLM unconfigured instead of silently using Groq).
- Deviations: Starlette's TestClient double-decodes `%25` in paths, so the percent-sign test was dropped (real uvicorn decodes once; checked with curl). Vendor API 4xx other than 404 → `unavailable`, no retry (T6.4 silent; conservative).
- Open questions: none. Note for P5: `run_all.py` must pass `EXTRA_DATA_DIR` to the mock via `env=`.

### Phase 1: Deterministic core (Fri 9 Oct, 20:25–21:20 IST)
- Summary: `src/normalize.py` (T4.2), `src/data_access.py` (`EXTRA_DATA_DIR`, runtime submissions, `norm_key`, `find_vendor`, `find_employee`), `src/injection.py` (R10), `src/schemas.py` (PolicyResult, VendorStatus, T8 + D6), `src/policy_engine.py` (R0–R12 with D-01, D-02, D-07.4, D-07.5), `src/tools.py` (6 tools, D5 descriptions, allowlists A=6 / analyst=5 / reviewer=0, rejection, cache, tool log, evidence corpus, T6.3 gate, compact policy view).
- Tests: 93 pass (new: `test_policy_engine` incl. the T5 table, `test_injection`, `test_vendor_tool`, `test_tools`, `test_golden_deterministic` = all 23 golden cases, deterministic aspects). No hardcoded names or `date.today()` in `src`.
- diff-reviewer: PASS; 5 fixes applied: server error text kept out of engine output (untrusted + scanned); `execute(..., actor=...)` now required (no fail-open scope); R7 fallback whole tokens; `get_request_details` "does not" sentence, purchase notes under `untrusted_text`, `run_gate` str(); compact policy view for the LLM.
- Deviations: D-14 (proposed: 404 or missing residency + sensitive data → Privacy) and D-15 (proposed: small conservative choices) recorded in DECISIONS.md.
- Open questions: registry `security_status = Expired` does not set `vendor_review_expired` (R6 literal; Security is still added). Left as written.

### Phase 2: Guardrails, fallback, trace, adapter (Fri 9 Oct, 21:20–22:10 IST): safety net
- Summary: `src/guardrails.py` (T11 merge, output filter, grounding, T11.1 templates, D-03, D-04), `src/fallback.py` (T12, D-07.8 unknown request, last-resort error decision), `src/tracing.py` (D10 step trace, no-op LangSmith shim), `src/solution.py` (`handle_request_with_trace`; both architectures use the fallback with `llm_unavailable` until agents exist, D-07.9).
- Tests: 124 pass (new `test_guardrails`, `test_solution_rules_only` = all 23 golden cases on both architectures under LLM outage, `test_trace`). Public runner with `LLM_SIMULATE_OUTAGE=1`: 6/6 single, 6/6 staged.
- diff-reviewer: 2 FAIL + 3 fixes, all applied: setup failures and odd IDs can no longer make `handle_request` raise; grounding holes closed (whole tokens, whole dates, no self-grounding from echoed agent args); D-16 overlap exclusion narrowed to `related_not_substitute` (G-08 risk); `run_id` path-safe; unknown-request telemetry 0 tools; error decision flags `missing_information`; D-04 excerpt search includes request facts.
- Deviations (logged): `assemble()` returns `(decision, report)` and takes `extra_flags`/`extra_evidence`; `handle_request_with_trace` has an extra `llm=None` parameter for dependency injection. D-16 (proposed) recorded.
- Open question: D-16 overlap exclusion (keep narrow, or R12 literal).

## Human checklist

Items that need the human. The build does not wait for them.

- [ ] Push to GitHub (never done by Claude Code).
- [ ] Write `docs/AGENT_LOG.md` (Class 10 evidence).
- [ ] Rewrite `docs/DECISION_MEMO.md` in your own voice.
- [ ] Submit the repo URL on the Google Form.
- [ ] P2: safety net exists; push to GitHub when convenient. Review D-16 (proposed) and its open question.
- [ ] P1: read the engine evidence for REQ-1007 (conflict) and REQ-1009 (unavailable) and two tool descriptions in `src/tools.py`: would a reviewer understand them? Review D-14 and D-15 (proposed).
- [ ] P0: note the model and rate-limit headers (above) in `docs/AGENT_LOG.md`. LLM budget option is fixed by D-12 (Groq free).
