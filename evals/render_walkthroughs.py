"""Render A vs B step traces side by side for 5 representative scenarios (D11.8).

    python evals/render_walkthroughs.py [--results-dir evals/results]

Reads stored run files only (no LLM calls) and writes results/scenario_walkthroughs.md.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = [
    ("G-02", "Overlap + new vendor"),
    ("G-06", "Incomplete request + prompt injection"),
    ("G-07", "Conflicting + expired vendor evidence"),
    ("G-08", "Existing tool already meets the need"),
    ("G-23", "PII implied only by the justification text"),
]
ARCHS = [("single", "A: bounded agent"), ("staged", "B: sequential specialists")]


def cell(text: object) -> str:
    return " ".join(str(text or "").split()).replace("|", "\\|")


def load(results: Path, arch: str, case_id: str) -> dict | None:
    paths = (results / "runs" / arch).glob(f"{case_id}_t*.json")
    for path in sorted(paths, key=lambda p: int(p.stem.rsplit("_t", 1)[1])):
        rec = json.loads(path.read_text(encoding="utf-8"))
        if rec["status"] == "ok":
            return rec
    return None


def step_text(step: dict) -> str:
    route = f" (route: {step['route_reason']})" if step.get("route_reason") else ""
    return cell(f"{step['actor']}: {step['action']} → {step['summary_out']}{route}")


def render(results: Path) -> str:
    golden = {c["case_id"]: c for c in json.loads((ROOT / "evals" / "golden_cases.json").read_text(encoding="utf-8"))}
    out = ["# Scenario walkthroughs: A vs B", "",
           "Rendered from `evals/results/runs/` by `evals/render_walkthroughs.py` (first trial with status ok).", ""]
    for case_id, title in SCENARIOS:
        case = golden[case_id]
        recs = {arch: load(results, arch, case_id) for arch, _ in ARCHS}
        out += [f"## {case_id} ({case['request_id']}): {title}", "",
                f"Expected decision: {', '.join(case['decision_type']['acceptable'])}. "
                f"Required approvals: {', '.join(case['approvals']['required'])}.", ""]
        out += ["| | " + " | ".join(label for _, label in ARCHS) + " |", "|---|---|---|"]
        for label, fn in [
            ("Case passed", lambda r: "PASS" if r["scores"]["case_pass"] else f"FAIL: {r['scores']['failures']}"),
            ("Final decision", lambda r: r["scores"]["decision_type"]),
            ("Approvals", lambda r: ", ".join(r["decision"]["required_approvals"])),
            ("Flags", lambda r: ", ".join(r["decision"]["risk_flags"])),
            ("stop_reason / final_mode", lambda r: f"{r['trace']['stop_reason']} / {r['trace']['final_mode']}"),
            ("LLM calls / tool calls", lambda r: f"{r['trace']['llm_calls']} / {r['trace']['tool_calls']}"),
            ("Active / total latency (ms)", lambda r: f"{r['trace']['latency_active_ms']:.0f} / {r['trace']['latency_total_ms']:.0f}"),
            ("Recommendation", lambda r: r["decision"]["recommendation"]),
            ("Guardrail events", lambda r: ", ".join(f"{k}={v}" for k, v in sorted(r["trace"]["event_counts"].items())
                                                    if not k.startswith(("gate_filled", "repeated")) ) or "none"),
        ]:
            out.append(f"| {label} | " + " | ".join(cell(fn(recs[a])) if recs[a] else "not run" for a, _ in ARCHS) + " |")
        out += ["", "Step trace:", "", "| Step | " + " | ".join(label for _, label in ARCHS) + " |", "|---|---|---|"]
        steps = {a: (recs[a]["trace"]["steps"] if recs[a] else []) for a, _ in ARCHS}
        for i in range(max((len(v) for v in steps.values()), default=0)):
            out.append(f"| {i + 1} | " + " | ".join(step_text(steps[a][i]) if i < len(steps[a]) else "" for a, _ in ARCHS) + " |")
        audit = recs["staged"]["trace"].get("analyst_audit") if recs["staged"] else None
        if audit:
            out += ["", f"B reviewer's audit of the analyst: issues {cell(audit['issues_found']) or 'none'}; "
                        f"rejected claims {cell(audit['rejected_claims']) or 'none'}; "
                        f"agrees with overlap assessment: {audit['agrees_with_overlap_assessment']}."]
        out.append("")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default=str(ROOT / "evals" / "results"))
    args = parser.parse_args()
    results = Path(args.results_dir)
    path = results / "scenario_walkthroughs.md"
    path.write_text(render(results), encoding="utf-8")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
