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

## Human checklist

Items that need the human. The build does not wait for them.

- [ ] Push to GitHub (never done by Claude Code).
- [ ] Write `docs/AGENT_LOG.md` (Class 10 evidence).
- [ ] Rewrite `docs/DECISION_MEMO.md` in your own voice.
- [ ] Submit the repo URL on the Google Form.
- [ ] P0: note the model and rate-limit headers (above) in `docs/AGENT_LOG.md`. LLM budget option is fixed by D-12 (Groq free).
