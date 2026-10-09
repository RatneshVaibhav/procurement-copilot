"""Run one request end to end and print the decision, raw proposal and trace.

    python scripts/run_one.py REQ-1006 --arch single
    python scripts/run_one.py REQ-1006 --arch staged --mode rules_only

Starts the mock vendor-risk API if it is local and not running. Saves the trace to
runtime/traces/<run_id>.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mock_api import launcher  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.solution import handle_request_with_trace  # noqa: E402

TRACE_DIR = ROOT / "runtime" / "traces"


def ensure_mock():
    base = get_settings().vendor_risk_base_url
    if launcher.is_healthy(base) or not launcher.is_local(base):
        return None
    proc = launcher.start(launcher.port_of(base), quiet=True)
    launcher.wait_for_api(f"{base}/health", proc, label="Mock vendor-risk API")
    return proc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("request_id")
    parser.add_argument("--arch", choices=["single", "staged"], default="single")
    parser.add_argument("--mode", choices=["llm", "rules_only"], default="llm")
    args = parser.parse_args()

    proc = ensure_mock()
    try:
        decision, trace = handle_request_with_trace(args.request_id, args.arch, mode=args.mode)
    finally:
        launcher.stop(proc)

    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    path = TRACE_DIR / f"{trace['run_id']}.json"
    path.write_text(json.dumps({"decision": decision.model_dump(), "trace": trace}, indent=2, default=str), encoding="utf-8")

    print(f"== {args.request_id}  arch={args.arch}  mode={args.mode}  provider={trace['provider']}  model={trace['model']}")
    print(f"stop_reason={trace['stop_reason']}  final_mode={trace['final_mode']}  error={trace['error']}")
    print(f"llm_calls={trace['llm_calls']}  tool_calls={trace['tool_calls']}  tokens={trace['tokens']}")
    print(f"latency total={trace['latency_total_ms']:.0f} ms  active={trace['latency_active_ms']:.0f} ms  wait={trace['llm_wait_ms']:.0f} ms")
    print("\n-- Steps")
    for s in trace["steps"]:
        route = f"  [route: {s['route_reason']}]" if s.get("route_reason") else ""
        print(f"{s['n']:>2}. {s['actor']:<20} {s['action']:<28} {s['summary_out']}{route}")
    print("\n-- Raw proposal(s) (pre-guardrail)")
    for p in trace["proposals"]:
        print(json.dumps(p, indent=1)[:3000])
    if trace.get("analyst_audit"):
        print("\n-- Reviewer's analyst audit\n" + json.dumps(trace["analyst_audit"], indent=1))
    print("\n-- Guardrail events")
    print(json.dumps({k: v for k, v in trace["event_counts"].items()}, indent=1))
    if trace["guardrails"].get("ungrounded_evidence"):
        print("ungrounded evidence removed:", json.dumps(trace["guardrails"]["ungrounded_evidence"], indent=1))
    print("\n-- Final decision")
    print(decision.model_dump_json(indent=1))
    print(f"\nTrace saved: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
