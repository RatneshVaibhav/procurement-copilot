# Agent log

How I used Claude Code to build this project and where I stepped in (Class 10: agentic coding with human ownership of correctness).

## Setup
- **Provider and model.** I started on Groq `openai/gpt-oss-20b`, free tier, the spec's default (D-12). It made only one tool call per turn, so one A run took about 7 calls and ~17K tokens against a free cap of 200K tokens a day. I didn't want to pay for this project, so I asked for free Gemini 2.5 Flash for the reported eval and Groq for development checks (D-17). Gemini then turned out to allow only 20 requests a day on my project, far below the ~150 the eval needs. So I moved the reported eval to `qwen/qwen3.8-27b` on Groq (D-20): free, parallel tool calls, about 11.5K tokens per A run. Reasoning is off because Groq limits that model to 1,000 output tokens a minute. Even so, qwen's daily cap meant only part of the cases could run per day. On the last day I moved the main eval to Gemini `gemini-3.5-flash-lite` (D-23). My existing Gemini key could use it, with a much bigger daily allowance, so both versions could run every case in one go. The qwen results stay in the project as a second model.
- **Rate limits I ran into.** Groq: 8,000 tokens per minute and 1,000 requests per day (smoke-test headers), and a 200,000 tokens/day cap for qwen (from a 429 error). Gemini 2.5 Flash: `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, limit 20. Flash-Lite never hit a daily limit during the full run.
- **Budget.** Free tiers only, my call. The price is a partial LLM eval, so I chose a paired order: A and B run on the same case before moving to the next one. That way the A-vs-B comparison stays fair wherever the quota runs out.

## Inspection and plan
- I started with the kickoff prompt from PLAN.md. Claude Code read the specs and listed scaffold defects, spec conflicts and open questions before changing any code. I answered the open questions and recorded the answers in `docs/DECISIONS.md` before Phase 0.
- The kickoff report itself wasn't saved in the repo, so I had its proposed defaults written out one by one as D-07.1 to D-07.11. That way nothing depended on chat history.
- How I resolved the conflicts:
  - forced `tool_choice` is removed, because three spec sections contradicted it (D-07.11);
  - the Analyst gets 5 tools;
  - the public runner changes only its startup, output path and exit code (D-08);
  - a registered vendor that the vendor-risk API doesn't know adds Security (D-01);
  - no product names inside rule patterns (D-02);
  - the overlap flag is decided by code only (D-03);
  - an injection flag added by the LLM must quote the exact text (D-04).
- **Working mode.** I had it run Phases 0 to 7 back to back instead of stopping after each one (D-11). Every phase still had to end with tests, a diff-reviewer pass, a commit and a build-log entry. It could pause for only four reasons:
  - a business rule DECISIONS.md doesn't cover;
  - a check still failing after three honest attempts;
  - provider, key or budget problems;
  - anything that needs secrets or a push.

## Per phase
| Phase | What got built | What the review caught (fixed before moving on) |
|---|---|---|
| P0 | Setup, scaffold fixes F1–F7, config, LLM smoke test | My change: continuous mode (D-11) instead of a stop after every phase |
| P1 | Deterministic core: data access, injection scan, policy engine R0–R12, tools | Server error text was leaking into engine output (now treated as untrusted); a keyword fallback matched "product" as "prod" |
| P2 | Guardrails, fallback, tracing: a rules-only safety net that passes the public checks with the LLM off | The grounding check could be fooled by substring matches and by the agent's own tool arguments |
| P3 | LLM client, bounded loop, Architecture A | A unit test was silently calling the real LLM (fixed by blanking keys in tests); 400-error handling misread the word "reasoning" in model output |
| P4 | Architecture B: deterministic supervisor, analyst, reviewer | A reviewer `tool_use_failed` error skipped the normal fallback; the policy block was missing the untrusted-data prefix |
| P5 | Eval harness; decision rule committed before any LLM run; rules-only baseline 20/23 | The provider-mixing guard covered only one column; a missing key would have produced fake A/B runs |
| P6 | Web app: queue, analysis, evidence, trace panel, actions with confirmation, audit log | An old result could show under a different request; Confirm was clickable before the consequence loaded |
| P7 | Docs, eval runs (qwen, then the full Flash-Lite eval and consistency trials), compare view, evaluation dashboard, evidence pack | The README still said results came from Gemini; the evidence pack didn't escape request text; numbers like "3.10" failed the grounding check |

The unit tests went from the starter set to 209 by the end. None of them calls a real LLM.

## Evidence (Class 10 checklist)
- **One diff I reviewed line by line:** commit `a5555c1`, the evidence-pack part of `webapp/main.py` and its test in `tests/test_webapp.py`. I checked two things. First, every piece of request, vendor or LLM text goes through `_md()` before it lands in the Markdown, so a justification can't fake a heading, a table row, a link or HTML. Second, the test really tries `<img src=x onerror=alert(1)>` and a fake "## Approvals required" line.
- **One wrong assumption that came up:** the plan expected Gemini's free tier to allow "a few hundred" requests a day. On my project it was 20, so running the reported eval on Gemini (D-17) couldn't work and I moved it to qwen on Groq (D-20). Another one: I assumed Gemini's OpenAI-compatible API handles tool calls like OpenAI's. With the Gemini 3 models it doesn't: each tool call carries a "thought signature" that has to be sent back. Without it, every run fell back to rules-only after the first call. The client now passes the signature back, and the Groq messages are unchanged. A smaller one: a 400-error check matched the word "reasoning" inside model output and would have quietly changed model settings in the middle of the eval.
- **Where I redirected the agent:** I kept the project on free tiers, even though it meant partial coverage. When the quota became the bottleneck, I first chose the paired order and honest reporting of what didn't run. Then I moved the main eval to a free model with a bigger allowance, so the comparison covers every case. I asked about getting more API keys from extra accounts, then dropped the idea: it breaks the providers' terms, and the reported numbers have to come from one model anyway. When the deadline got tight, I gave the build one more day and asked for every deliverable to be finished properly.

## My judgement calls
1. **Decision rule.** I kept the spec's default rule (D-13) and had it committed before the first LLM eval run, so the result couldn't be tuned afterwards. B ships only if it passes at least 2 more golden cases than A, or fixes a safety failure A has, at no more than 2× A's latency. A second agent doubles the moving parts, so it has to earn them.
2. **Overlap flag (assumption 11).** The flag is literal and set by code: same category or an identical product name. Whether the existing tool actually meets the need is the AI's judgement, and that only drives `use_existing_tool`. That judgement is exactly where B went wrong on G-04 and G-07.
3. **Vendor API down (assumption 13).** If the registry review is current and no sensitive data is involved, the gap is recorded and flagged but doesn't add Security. Policy §10 only escalates when the gap is material.
4. **Ship A.** Before production I'd want the full case set with several trials, plus a deterministic check for personal data that's only implied in the free text (G-23).
