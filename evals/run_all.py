"""Golden + public evaluation for both architectures and the rules-only baseline (T14, D11).

    python evals/run_all.py --no-llm                      # rules-only column (no key needed)
    python evals/run_all.py --provider gemini --trials 1 --resume    # A and B, reported eval (D-17)
    python evals/run_all.py --provider gemini --retry-infra          # re-run rows that hit rate limits
    python evals/run_all.py --provider gemini --trials 3 --resume    # consistency subset (D11.5)

Writes evals/results/: golden_runs.csv, runs/<arch>/<case>_t<k>.json, summary.json,
summary.md, public_<arch>.csv. The summary is always rebuilt from every stored run, so a
--no-llm run merges with stored LLM results (D-07.6).
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mock_api import launcher  # noqa: E402
from src.config import apply_provider, get_settings  # noqa: E402
from src.contracts import ProcurementDecision  # noqa: E402
from src.solution import handle_request_with_trace  # noqa: E402

sys.path.insert(0, str(ROOT / "evals"))
import score  # noqa: E402

GOLDEN_PATH = ROOT / "evals" / "golden_cases.json"
PUBLIC_PATH = ROOT / "evals" / "public_cases.json"
FIXTURES = "evals/fixtures"
DOWN_URL = "http://127.0.0.1:9"
INFRA_KINDS = {"rate_limited", "network", "server"}
CONFIG_KINDS = {"not_configured", "auth", "not_found"}
CONSISTENCY_SUBSET = ["G-02", "G-06", "G-07", "G-08", "G-17", "G-23"]  # D11.5
# D4 free-tier limits used for the budget projection; override with --daily-*-limit.
DAILY_LIMITS = {"groq": {"tokens": 200_000, "requests": 1_000}, "gemini": {"tokens": None, "requests": 250}}
CSV_FIELDS = ["arch", "case_id", "request_id", "trial", "status", "provider", "model", "case_pass", "approvals_ok",
              "flags_ok", "missing_ok", "decision_ok", "safety_ok", "decision_type", "raw_decision_ok",
              "raw_approvals_ok", "raw_flags_ok", "code_restored_approval", "code_restored_flag", "llm_role_dropped",
              "llm_decision_overridden", "ungrounded_evidence_removed", "gate_filled", "reviewer_rejections",
              "stop_reason", "final_mode", "llm_calls", "tool_calls", "tokens_prompt", "tokens_completion",
              "tokens_cached", "latency_active_ms", "latency_total_ms", "failures"]


def load_public_runner():
    spec = importlib.util.spec_from_file_location("run_public_evals", ROOT / "evals" / "run_public_evals.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EnvPatch:
    def __init__(self, **values):
        self.values, self.saved = values, {}

    def __enter__(self):
        for k, v in self.values.items():
            self.saved[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def fault_env(case: dict) -> dict:
    if case["fault"] == "vendor_api_down":
        return {"VENDOR_RISK_BASE_URL": DOWN_URL}
    if case["fault"] == "llm_unavailable":
        return {"LLM_SIMULATE_OUTAGE": "1"}
    return {}


def run_path(results: Path, arch: str, case_id: str, trial: int) -> Path:
    return results / "runs" / arch / f"{case_id}_t{trial}.json"


def load_records(results: Path) -> list[dict]:
    records = []
    for path in sorted((results / "runs").glob("*/*.json")):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            print(f"WARNING: unreadable run file {path}")
    return records


def run_status(trace: dict, case: dict) -> str:
    """ok | infra_error (rate limit, network, provider 5xx) | config_error (no key, auth, unknown model).
    A simulated outage (fault case) and every model failure stay "ok" and are scored (D11.3)."""
    if case["fault"] == "llm_unavailable":
        return "ok"
    kind = trace.get("llm_error_kind")
    if kind in INFRA_KINDS:
        return "infra_error"
    if kind in CONFIG_KINDS:
        return "config_error"
    return "ok"


def should_skip(prev: dict | None, resume: bool, retry_infra: bool) -> bool:
    if not resume or prev is None:
        return False
    return prev["status"] == "ok" or (prev["status"] == "infra_error" and not retry_infra)


def run_case(case: dict, arch: str, trial: int, results: Path, run=None) -> dict:
    run = run or handle_request_with_trace
    mode = "rules_only" if arch == "rules_only" else "llm"
    with EnvPatch(**fault_env(case)):
        decision, trace = run(case["request_id"], "single" if arch == "rules_only" else arch, mode=mode)
    decision_dict = decision.model_dump()
    record = {
        "case_id": case["case_id"], "request_id": case["request_id"], "arch": arch, "trial": trial,
        "status": run_status(trace, case), "fault": case["fault"],
        "provider": None if arch == "rules_only" else trace["provider"],
        "model": None if arch == "rules_only" else trace["model"],
        "error": trace.get("error"),
        "decision": decision_dict, "trace": trace, "scores": score.score_run(case, decision_dict, trace),
    }
    path = run_path(results, arch, case["case_id"], trial)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return record


def row_of(rec: dict) -> dict:
    t, s = rec["trace"], rec["scores"]
    tokens = t.get("tokens") or {}
    return {
        "arch": rec["arch"], "case_id": rec["case_id"], "request_id": rec["request_id"], "trial": rec["trial"],
        "status": rec["status"], "provider": rec.get("provider"), "model": rec.get("model"), "error": rec.get("error"),
        "scores": s, "stop_reason": t.get("stop_reason"), "final_mode": t.get("final_mode"),
        "llm_calls": t.get("llm_calls", 0), "tool_calls": t.get("tool_calls", 0),
        "tokens_total": tokens.get("prompt", 0) + tokens.get("completion", 0), "tokens": tokens,
        "latency_active_ms": t.get("latency_active_ms"), "latency_total_ms": t.get("latency_total_ms"),
        "repeated_tool_calls": t.get("repeated_tool_calls", 0), "tool_rejected": t.get("tool_rejected", 0),
    }


def write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for r in sorted(rows, key=lambda r: (r["arch"], r["case_id"], r["trial"])):
            s = r["scores"]
            writer.writerow({
                **{k: r.get(k) for k in ["arch", "case_id", "request_id", "trial", "status", "provider", "model",
                                         "stop_reason", "final_mode", "llm_calls", "tool_calls", "latency_active_ms",
                                         "latency_total_ms"]},
                **{k: s.get(k) for k in ["case_pass", "approvals_ok", "flags_ok", "missing_ok", "decision_ok", "safety_ok",
                                         "decision_type", "raw_decision_ok", "raw_approvals_ok", "raw_flags_ok",
                                         "code_restored_approval", "code_restored_flag", "llm_role_dropped",
                                         "llm_decision_overridden", "ungrounded_evidence_removed", "gate_filled",
                                         "reviewer_rejections", "failures"]},
                "tokens_prompt": r["tokens"].get("prompt", 0), "tokens_completion": r["tokens"].get("completion", 0),
                "tokens_cached": r["tokens"].get("cached", 0),
            })


def public_from_golden(records: list[dict], golden: list[dict], results: Path) -> dict:
    """Score the six public cases from the golden runs of the same requests (D-18 proposed)."""
    runner = load_public_runner()
    public = json.loads(PUBLIC_PATH.read_text(encoding="utf-8"))
    by_request = {c["request_id"]: c["case_id"] for c in golden if c["fault"] is None}
    out = {}
    for arch in sorted({r["arch"] for r in records}):
        rows = []
        for pc in public:
            cid = by_request.get(pc["request_id"])
            rec = next((r for r in sorted(records, key=lambda r: r["trial"])
                        if r["arch"] == arch and r["case_id"] == cid and r["status"] == "ok"), None)
            if rec is None:
                continue
            decision = ProcurementDecision.model_validate(rec["decision"])
            failures = runner.evaluate(decision, pc["expectations"])
            rows.append({"case_id": pc["case_id"], "request_id": pc["request_id"], "architecture": arch,
                         "passed_minimum_checks": not failures, "latency_ms": rec["trace"].get("latency_total_ms"),
                         "llm_calls": decision.telemetry.llm_calls if decision.telemetry else "",
                         "tool_calls": decision.telemetry.tool_calls if decision.telemetry else "",
                         "failures": " | ".join(failures), "source": f"golden run {cid} t{rec['trial']}"})
        if rows:
            with (results / f"public_{arch}.csv").open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            out[arch] = f"{sum(1 for r in rows if r['passed_minimum_checks'])}/{len(rows)}"
    return out


def public_subprocess(arch: str, results: Path) -> str:
    """T14 step 2: run the public runner itself (costs 6 LLM runs per architecture)."""
    import subprocess
    proc = subprocess.run([sys.executable, str(ROOT / "evals" / "run_public_evals.py"), "--architecture", arch],
                          cwd=ROOT, env=os.environ.copy(), capture_output=True, text=True)
    (results / f"public_{arch}.txt").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    line = next((l for l in proc.stdout.splitlines() if l.startswith("Minimum checks passed:")), "")
    return line.split(":", 1)[1].strip() if line else "error"


def check_provider(records: list[dict], provider: str, model: str) -> None:
    """D-17: every LLM column in one results dir uses the same provider and model."""
    others = {(r["provider"], r["model"]) for r in records if r["arch"] != "rules_only"} - {(provider, model)}
    if others:
        raise SystemExit(f"ERROR: LLM runs in this results dir used {sorted(others)}; current is {(provider, model)}. "
                         "Never mix providers or models in one comparison (D-17). Use --results-dir for another provider.")


def check_mock_has_fixtures(base: str) -> None:
    """Refuse a mock that is running without EXTRA_DATA_DIR=evals/fixtures."""
    import requests
    from urllib.parse import quote
    names = list(json.loads((ROOT / FIXTURES / "vendor_risk.json").read_text(encoding="utf-8")))
    if names and requests.get(f"{base}/vendor-risk/{quote(names[0], safe='')}", timeout=3).status_code == 404:
        raise SystemExit(f"ERROR: the mock API already running at {base} does not serve the eval fixtures. "
                         "Stop it, or set EVAL_API_PORT to a free port.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--architectures", default="single,staged")
    parser.add_argument("--no-llm", action="store_true", help="rules-only column only (no LLM)")
    parser.add_argument("--cases", default="", help="comma-separated case IDs")
    parser.add_argument("--skip-public", action="store_true")
    parser.add_argument("--public-subprocess", action="store_true", help="run the public runner itself (6 extra LLM runs per architecture)")
    parser.add_argument("--resume", action="store_true", help="skip runs already stored (ok, or infra_error unless --retry-infra)")
    parser.add_argument("--retry-infra", action="store_true", help="re-run stored infra_error rows")
    parser.add_argument("--provider", choices=["groq", "gemini"], help="override LLM_PROVIDER (D-17)")
    parser.add_argument("--model", help="override MODEL_NAME for this run (D-20)")
    parser.add_argument("--reasoning-effort", help="override LLM_REASONING_EFFORT (e.g. none, low)")
    parser.add_argument("--results-dir", default=str(ROOT / "evals" / "results"))
    parser.add_argument("--interleave", action="store_true",
                        help="case-major order (A and B per case) so a budget stop leaves paired results")
    parser.add_argument("--max-infra-streak", type=int, default=2, help="stop after this many consecutive infra errors")
    parser.add_argument("--daily-token-limit", type=int)
    parser.add_argument("--daily-request-limit", type=int)
    args = parser.parse_args()
    args.resume = args.resume or args.retry_infra

    if args.provider:
        apply_provider(args.provider)
    if args.model:
        os.environ["MODEL_NAME"] = args.model
    if args.reasoning_effort:
        os.environ["LLM_REASONING_EFFORT"] = args.reasoning_effort
    results = Path(args.results_dir)
    results.mkdir(parents=True, exist_ok=True)
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    wanted = [c.strip() for c in args.cases.split(",") if c.strip()]
    if args.trials > 1 and not wanted:
        wanted = CONSISTENCY_SUBSET
        print(f"--trials {args.trials} without --cases: using the D11.5 subset {', '.join(wanted)}")
    by_id = {c["case_id"]: c for c in golden}
    cases = [by_id[c] for c in wanted if c in by_id] if wanted else golden  # --cases order = run priority
    archs = ["rules_only"] if args.no_llm else [a.strip() for a in args.architectures.split(",") if a.strip()]
    settings = get_settings()
    stored = load_records(results)
    if not args.no_llm:
        if not args.provider:
            raise SystemExit("ERROR: LLM runs need an explicit --provider (groq or gemini) so the reported provider is "
                             "never implicit (D-17). Nothing was run.")
        if not settings.llm_configured or settings.llm_simulate_outage:
            raise SystemExit(f"ERROR: provider {settings.llm_provider!r} is not usable (configured={settings.llm_configured}, "
                             f"LLM_SIMULATE_OUTAGE={settings.llm_simulate_outage}). Add the key to .env; nothing was run.")
        check_provider(stored, settings.llm_provider, settings.model_name)
        print(f"Provider: {settings.llm_provider}  model: {settings.model_name}")

    port = settings.eval_api_port
    base = f"http://127.0.0.1:{port}"
    mock_env = {**os.environ, "EXTRA_DATA_DIR": FIXTURES}
    proc = None if launcher.is_healthy(base) else launcher.start(port, env=mock_env, quiet=True)
    if proc is not None:
        launcher.wait_for_api(f"{base}/health", proc, label="Mock vendor-risk API (eval)")
    else:
        check_mock_has_fixtures(base)
    limits = DAILY_LIMITS.get(settings.llm_provider, {})
    token_limit = args.daily_token_limit or limits.get("tokens")
    request_limit = args.daily_request_limit or limits.get("requests")
    try:
        with EnvPatch(VENDOR_RISK_BASE_URL=base, EXTRA_DATA_DIR=FIXTURES):
            if args.interleave:
                plan = [(arch, case, t) for case in cases for t in range(1, args.trials + 1) for arch in archs]
            else:
                plan = [(arch, case, t) for arch in archs for case in cases for t in range(1, args.trials + 1)]
            used_tokens = used_calls = llm_runs = infra_streak = 0
            for i, (arch, case, trial) in enumerate(plan, 1):
                path = run_path(results, arch, case["case_id"], trial)
                prev = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
                if should_skip(prev, args.resume, args.retry_infra):
                    continue
                start = time.perf_counter()
                rec = run_case(case, arch, trial, results)
                tokens = rec["trace"]["tokens"]
                run_tokens = tokens.get("prompt", 0) + tokens.get("completion", 0)
                used_tokens += run_tokens
                used_calls += rec["trace"]["llm_calls"]
                verdict = {"ok": "PASS" if rec["scores"]["case_pass"] else "FAIL", "infra_error": "INFRA",
                           "config_error": "CONFIG"}[rec["status"]]
                print(f"[{i}/{len(plan)}] {verdict:<5} {arch:<10} {case['case_id']} t{trial} {case['request_id']:<9} "
                      f"stop={rec['trace']['stop_reason']} mode={rec['trace']['final_mode']} llm={rec['trace']['llm_calls']} "
                      f"tokens={run_tokens} (session {used_tokens}) {time.perf_counter() - start:.0f}s"
                      + (f"  | {rec['scores']['failures']}" if verdict == "FAIL" else "")
                      + (f"  | {rec['error']}" if verdict in {"INFRA", "CONFIG"} else ""), flush=True)
                if rec["status"] == "config_error":
                    print("STOPPING: provider configuration error (key, auth or model). Fix it and re-run with --resume.")
                    break
                if arch != "rules_only" and rec["trace"]["llm_calls"]:
                    llm_runs += 1
                    if llm_runs == 2:
                        remaining = sum(1 for a, c, _ in plan[i:] if a != "rules_only" and c["fault"] != "llm_unavailable")
                        per_tok, per_call = used_tokens / llm_runs, used_calls / llm_runs
                        print(f"BUDGET: ~{per_tok:.0f} tokens and ~{per_call:.1f} LLM calls per run; {remaining} LLM runs left "
                              f"→ projected ~{per_tok * remaining:.0f} tokens, ~{per_call * remaining:.0f} requests. "
                              f"Daily limits: tokens {token_limit or 'n/a'}, requests {request_limit or 'n/a'}.")
                        if (token_limit and per_tok * remaining > token_limit) or (request_limit and per_call * remaining > request_limit):
                            print("BUDGET WARNING: the remaining plan exceeds one day's free-tier limit; continue with --resume later.")
                infra_streak = infra_streak + 1 if rec["status"] == "infra_error" else 0
                if infra_streak >= args.max_infra_streak:
                    print(f"STOPPING: {infra_streak} consecutive infra errors (rate limit or provider down). "
                          "Re-run later with --resume --retry-infra.")
                    break
            records = load_records(results)
            public = {}
            if not args.skip_public:
                public = public_from_golden(records, golden, results)
                if args.public_subprocess and not args.no_llm:
                    for arch in archs:
                        public[arch] = public_subprocess(arch, results)
    finally:
        launcher.stop(proc)

    rows = [row_of(r) for r in records]
    write_csv(rows, results / "golden_runs.csv")
    summary = score.summarise(rows, golden, public)
    (results / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    (results / "summary.md").write_text(score.render_markdown(summary, golden), encoding="utf-8")
    print("\n" + (results / "summary.md").read_text(encoding="utf-8").split("## Stop reasons")[0])
    print(f"Results written to {results}")


if __name__ == "__main__":
    main()
