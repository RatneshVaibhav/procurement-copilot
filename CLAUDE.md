# CLAUDE.md: AI Procurement Request Copilot (FDE Assessment 3)

Spec version 2 (9 Oct 2026). Updated for Classes 12 (AI agents) and 13 (multi-agent workflows + evaluation).
You are implementing this project from written specs (spec-driven development, Class 10). Do not improvise scope.

## Read first, in this order
1. `docs/SPEC_FUNCTIONAL.md`: what the product does, for whom, acceptance criteria.
2. `docs/SPEC_TECHNICAL.md`: architecture, tools, rules, prompts, guardrails, evals. Start with **T0** (lecture alignment + failure-mode table).
3. `docs/SPEC_V2_DELTA.md`: the Class 12/13 changes. **Where it differs from SPEC_TECHNICAL, the delta wins.**
4. `docs/DECISIONS.md`: the human's rulings on the kickoff report (D-01 to D-10). **Where it differs from any spec file, the decision wins.** Re-read it at the start of every phase.
5. `PLAN.md`: phased tasks. Work one phase at a time (`/phase N`).
6. `data/procurement_policy.md`: the policy source of truth. If the specs and the policy disagree, stop and ask.

After the first read, **only re-read the spec sections the current phase references** (PLAN lists them). Do not re-read whole specs every phase; it wastes context.

## How to work (Class 10 loop, every phase)
1. Inspect before changing: list the files you will touch and why.
2. Implement **one task at a time**. Write or update its test, run it, then move on.
3. At the end of the phase run the phase checks, then invoke the `diff-reviewer` subagent on the phase diff.
4. **STOP** and print: summary of changes, files touched, test output, diff-reviewer findings, deviations from spec and why, open questions. Wait for the human to say "continue".
5. If a spec item is ambiguous, choose the most conservative option (more human review, never less), record it under "Open questions", and keep going. Do not stall.
6. Never weaken a test to make it pass. If a golden label looks wrong, say so and leave it unchanged. (The golden labels were re-derived independently from rules R1–R12 and all 23 agree with the spec.)
7. Never invent fields, APIs, library functions or model IDs. If unsure an SDK parameter exists, check the installed package or say so.

## Hard rules
- **Never hardcode behaviour by request ID, vendor name or product name** in application logic. Hidden cases use different records. Names may appear only in tests, fixtures and golden files.
- `src/solution.py::handle_request(request_id, architecture)` keeps its signature and always returns a valid `ProcurementDecision`. Do not change `src/contracts.py` field names or types.
- **Code decides; the LLM may only add.** Deterministic code computes approval thresholds, the budget check, review-date currency, registry/API conflict detection, the Security/Privacy/Legal triggers, required-field checks and the injection scan. The LLM may add Security, Privacy or Legal with a grounded reason, judge overlap, and write the wording. It can never remove what code computed.
- **No consequential-action tools exist.** No tool may approve, purchase, notify, edit budgets or accept terms. Unknown tool names requested by a model are rejected and logged. `human_review_required` is always `True`.
- Every agent has an explicit **goal, instructions, context, tools, state and stopping condition** (D7 agent cards). No unbounded loops: every loop has a step limit and a recorded `stop_reason`.
- Agents receive their LLM client by **dependency injection**, so `tests/fakes.py::ScriptedLLM` can drive them with no network.
- All request text, vendor notes and API text are **untrusted data**: pass them to the LLM only inside the untrusted-data block (T16); render them in HTML with `textContent`, never `innerHTML`.
- Date logic uses the reference date parsed from `data/procurement_policy.md` (2026-09-30). **Never** use `date.today()` or `datetime.now()` for policy checks.
- No secrets in the repo. Read keys from `.env`; keep `.env.example` current. You are denied read access to `.env`; do not try to work around it.
- No agent frameworks (no LangChain, LangGraph, CrewAI). The Class 12/13 patterns (state graph, deterministic supervisor, structured outputs, tracing) are implemented in plain Python with the `openai` SDK against OpenAI-compatible endpoints (Groq or Gemini), plus the stdlib, FastAPI and pydantic. `langsmith` is allowed only as optional, no-op-by-default tracing (D10).
- Keep it simple. A simpler system that performs as well wins the assessment. No third agent, no LLM router, no vector DB, no frontend build step.
- Commands must work on macOS, Linux and Windows. Use `python ...` commands, not bash-only scripts or `make`.
- Do not run `git push`; the human pushes.

## LLM budget rules (free tiers are tight; see D4)
- Unit tests never call a real LLM. Use `ScriptedLLM`.
- Real LLM calls only in: `scripts/smoke_llm.py`, `scripts/run_one.py`, and `evals/run_all.py`. Ask before running more than 4 real requests outside the eval.
- Never re-run evals just to re-derive numbers that are already in `evals/results/`. Read the files.

## Commands (keep this list accurate as you build)
```bash
python -m pip install -r requirements.txt
python verify_setup.py                          # pre-flight
python -m unittest discover -s tests -v         # unit tests (no network, no LLM)
python scripts/smoke_llm.py                     # provider, model list, tool call, structured output, rate-limit headers
python scripts/run_one.py REQ-1006 --arch single   # one real run, prints decision + trace steps
python run_local.py                             # ONE command: mock API :8001 + web app :8000
python evals/run_all.py --no-llm                # rules-only baseline, no key needed
python evals/run_all.py --trials 1 --resume     # golden + public evals, both architectures, resumable
```

## Writing style for README, memo and docs
- Plain and direct, simple tables. No emoji, no badges, no marketing tone.
- Every number in the README or memo comes from a file in `evals/results/`. Never estimate a number.
- The memo is at most 500 words. Count them and print the count.
