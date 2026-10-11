# Student submission checklist

Before submitting, confirm that:

- [x] `python verify_setup.py` passes in your project environment. (PRE-FLIGHT PASSED in a fresh clone and venv; also run by CI.)
- [x] The product can process a request end-to-end. (`python run_local.py` → queue → Analyse → evidence, approvals, flags, next step → action with confirmation → audit log.)
- [x] Architecture A is a working single-agent baseline. (`src/agents/single_agent.py`; 21/23 golden cases.)
- [x] Architecture B is a lightweight staged / 2-agent variant. (`src/agents/staged_agent.py`: analyst → code → reviewer, deterministic supervisor; 18/23.)
- [x] At least 3 tools are used; at least 1 tool/check is deterministic. (6 tools, all deterministic logic; `get_vendor_status` calls the external vendor-risk service; `src/tools.py`.)
- [x] Recommendations are returned in the `ProcurementDecision` structure. (`src/solution.py::handle_request`, unchanged signature.)
- [x] Important evidence is visible to the user. (Evidence table with source and reference, approval reasons with rule and policy section, "How this was decided" trace.)
- [x] Missing/conflicting/unavailable evidence is handled without fabrication. (Banners for unavailable, conflicting and expired vendor evidence; grounding check drops evidence not found in tool results.)
- [x] Human approval is preserved for sensitive decisions. (`human_review_required` is always true; no tool can approve, purchase or notify; overrides need a reason; actions can be revoked.)
- [x] Prompt injection inside business data does not override system behavior. (Injection cases 3/3 for A; held-out H-05; an adversarial fake model could not remove any approval.)
- [x] Date-based checks use the policy's data snapshot / reference date. (2026-09-30, parsed from `data/procurement_policy.md`; no `date.today()` in policy logic.)
- [x] The same evaluation cases were run on both architectures. (23 golden cases paired on Flash-Lite; 5 held-out cases × 3 trials on both.)
- [x] Latency and LLM/tool-call counts are reported. (README §7 tables and every `summary.md`.)
- [x] The decision memo is <= 500 words and supported by evaluation evidence. (`docs/DECISION_MEMO.md`, 498 words by `wc -w`; every number from `evals/results*/`.)
- [x] Setup instructions work from a clean environment. (Fresh clone of the public repo → venv → install → pre-flight → tests; CI on Python 3.11 and 3.12.)
- [x] Any LLM/provider SDK you added is present in `requirements.txt`. (`openai`, optional `langsmith`.)
- [x] `.env`, API keys, and other secrets are not committed. (`.env` git-ignored and never tracked; no key-shaped strings in any commit.)
