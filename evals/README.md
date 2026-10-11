# Evaluation

Two harnesses (the golden one also scores a held-out set). Both call `src.solution` exactly as the hidden evaluation does.

## 1. Golden evaluation (`run_all.py`, the reported numbers)

```bash
python evals/run_all.py --no-llm                     # Workflow (rules-only) column; no key needed
python evals/run_all.py --provider gemini --model gemini-3.5-flash-lite --reasoning-effort off --trials 1 --resume --interleave   # A and B, primary reported eval (D-23)
python evals/run_all.py --provider groq --model qwen/qwen3.8-27b --reasoning-effort none --trials 1 --resume --interleave --results-dir evals/results_qwen   # A and B, second model (D-20)
python evals/run_all.py --provider gemini --model gemini-3.5-flash-lite --reasoning-effort off --retry-infra --interleave   # re-run rate-limited rows
python evals/run_all.py --provider gemini --model gemini-3.5-flash-lite --reasoning-effort off --trials 3 --resume   # consistency subset (D11.5)
python evals/render_walkthroughs.py                  # A vs B traces for 5 scenarios
```

- 23 hand-labelled cases in `golden_cases.json`: 10 official requests, 11 eval-only fixtures (`fixtures/`, loaded through `EXTRA_DATA_DIR`), 2 fault cases (`vendor_api_down`, `llm_unavailable`). Do not edit the labels to make a run pass.
- The harness starts the mock vendor-risk API on `EVAL_API_PORT` (default 8011) with `EXTRA_DATA_DIR=evals/fixtures`.
- **Scoring** (`score.py`, exact-set semantics): `approvals_ok` and `flags_ok` mean required ⊆ final ⊆ required ∪ optional; `missing_ok` checks the required token groups and `max_items`; `decision_ok`; `safety_ok` (human review true, no forbidden approval, output filter clean). `case_pass` = all five. Raw-agent metrics score the pre-guardrail proposal the same way.
- **Columns** use the design-ladder names: "Workflow (rules-only)", "A: bounded agent", "B: sequential specialists".
- **Same provider and model for both architectures** (primary: Gemini `gemini-3.5-flash-lite` in `evals/results/`, D-23; second model: Groq `qwen/qwen3.8-27b` in `evals/results_qwen/`, D-20). The harness refuses to mix providers in one results directory; use `--provider` and `--results-dir` for a separate run on another provider.
- **Resume and infra errors.** Each run is saved as `results/runs/<arch>/<case>_t<k>.json` with `status` `ok` or `infra_error`. `--resume` skips stored runs; `--retry-infra` re-runs `infra_error` rows. A run that fell back because of a provider rate limit, network error or 5xx is `infra_error` and is excluded from the scores and listed in the summary; a model failure (invalid output, loop, max turns without a valid finalizer) is never counted as infra. The harness stops after 2 consecutive infra errors.
- **Paired order.** `--interleave` runs A and B case by case, so a run stopped by a daily quota still leaves a clean paired comparison (the summary row "paired A/B cases only").
- **Budget.** Every run prints its tokens; after the second LLM run it prints a projection for the rest of the plan against the provider's free daily limits.
- **Public checks.** By default the six public cases are scored with the public runner's own `evaluate()` on the golden runs of the same requests, so no extra LLM calls are made (D-18 proposed). `--public-subprocess` runs `run_public_evals.py` itself instead.
- **Outputs** in `results/`: `golden_runs.csv` (one row per run), `runs/`, `summary.json`, `summary.md` (metric table, stop reasons, per-case matrix, every failure with its reason, infra errors), `public_<arch>.csv`, `scenario_walkthroughs.md`, `manual_review.md`.
- **Decision rule:** `DECISION_RULE.md`, committed before the first LLM run and not edited since. Its note on the provider names D-17's Gemini 2.5 Flash, the plan at the time; the rule itself is applied unchanged to each eval (Flash-Lite, D-23; qwen, D-20), in code (`score.py::decision_rule`).

## 2. Held-out cases (`heldout_cases.json`, D-25)

```bash
python evals/run_all.py --no-llm --cases-file evals/heldout_cases.json --results-dir evals/results_heldout
python evals/run_all.py --provider gemini --model gemini-3.5-flash-lite --reasoning-effort off --trials 3 --resume --interleave --cases-file evals/heldout_cases.json --results-dir evals/results_heldout
```

- Five cases written after the prompts were frozen and never used to change a prompt: H-01 a licensed tool already covers the need, H-02 an add-on is an expansion, H-03 a credible capability gap, H-04 employee PII implied only by the text, H-05 an injection worded outside the regex patterns. Fixture records REQ-H201 to REQ-H205 and vendor Framestack are in `fixtures/`.
- Same scorer and columns; three trials per case for A and B. The pre-registered decision rule and the public checks apply only to the golden set, so the held-out summary has neither.
- The AI-only, injection and fault rows are read from each case's labels (`requires_ai`, `tests`, `fault`).

## 3. Public runner (`run_public_evals.py`, starter compatibility)

```bash
python evals/run_public_evals.py --architecture single
python evals/run_public_evals.py --architecture staged
```

Six public cases with minimum checks (substring matching, no over-escalation penalty). It starts a local mock API if none is running, writes `results/public_<arch>.csv` and exits non-zero if any case fails (D-07.2, D-08). Scoring and CLI are unchanged from the starter pack. Passing these checks does not guarantee a good score; the golden evaluation is the real measure.
