# Evaluation

Two harnesses. Both call `src.solution` exactly as the hidden evaluation does.

## 1. Golden evaluation (`run_all.py`, the reported numbers)

```bash
python evals/run_all.py --no-llm                     # Workflow (rules-only) column; no key needed
python evals/run_all.py --provider gemini --trials 1 --resume   # A and B, reported eval (D-17)
python evals/run_all.py --provider gemini --retry-infra         # re-run rows that hit rate limits
python evals/run_all.py --provider gemini --trials 3 --resume   # consistency subset (D11.5)
python evals/render_walkthroughs.py                  # A vs B traces for 5 scenarios
```

- 23 hand-labelled cases in `golden_cases.json`: 10 official requests, 11 eval-only fixtures (`fixtures/`, loaded through `EXTRA_DATA_DIR`), 2 fault cases (`vendor_api_down`, `llm_unavailable`). Do not edit the labels to make a run pass.
- The harness starts the mock vendor-risk API on `EVAL_API_PORT` (default 8011) with `EXTRA_DATA_DIR=evals/fixtures`.
- **Scoring** (`score.py`, exact-set semantics): `approvals_ok` and `flags_ok` mean required ⊆ final ⊆ required ∪ optional; `missing_ok` checks the required token groups and `max_items`; `decision_ok`; `safety_ok` (human review true, no forbidden approval, output filter clean). `case_pass` = all five. Raw-agent metrics score the pre-guardrail proposal the same way.
- **Columns** use the design-ladder names: "Workflow (rules-only)", "A: bounded agent", "B: sequential specialists".
- **Same provider and model for both architectures** (D-17: Gemini 2.5 Flash free tier for the reported numbers). The harness refuses to mix providers in one results directory; use `--provider` and `--results-dir` for a separate run on another provider.
- **Resume and infra errors.** Each run is saved as `results/runs/<arch>/<case>_t<k>.json` with `status` `ok` or `infra_error`. `--resume` skips stored runs; `--retry-infra` re-runs `infra_error` rows. A run that fell back because of a provider rate limit, network error or 5xx is `infra_error` and is excluded from the scores and listed in the summary; a model failure (invalid output, loop, max turns without a valid finalizer) is never counted as infra. The harness stops after 2 consecutive infra errors.
- **Paired order.** `--interleave` runs A and B case by case, so a run stopped by a daily quota still leaves a clean paired comparison (the summary row "paired A/B cases only").
- **Budget.** Every run prints its tokens; after the second LLM run it prints a projection for the rest of the plan against the provider's free daily limits.
- **Public checks.** By default the six public cases are scored with the public runner's own `evaluate()` on the golden runs of the same requests, so no extra LLM calls are made (D-18 proposed). `--public-subprocess` runs `run_public_evals.py` itself instead.
- **Outputs** in `results/`: `golden_runs.csv` (one row per run), `runs/`, `summary.json`, `summary.md` (metric table, stop reasons, per-case matrix, every failure with its reason, infra errors), `public_<arch>.csv`, `scenario_walkthroughs.md`, `manual_review.md`.
- **Decision rule:** `DECISION_RULE.md`, committed before the first LLM run.

## 2. Public runner (`run_public_evals.py`, starter compatibility)

```bash
python evals/run_public_evals.py --architecture single
python evals/run_public_evals.py --architecture staged
```

Six public cases with minimum checks (substring matching, no over-escalation penalty). It starts a local mock API if none is running, writes `results/public_<arch>.csv` and exits non-zero if any case fails (D-07.2, D-08). Scoring and CLI are unchanged from the starter pack. Passing these checks does not guarantee a good score; the golden evaluation is the real measure.
