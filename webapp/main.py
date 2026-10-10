"""Web app: JSON API + static UI (T17, D14). Routing is simulated: actions go to the audit log only."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mock_api import launcher
from src import data_access as da
from src import policy_engine as pe
from src.config import get_settings
from src.guardrails import decision_from_recommendation
from src.solution import handle_request_with_trace

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"
RUNTIME = ROOT / "runtime"
AUDIT_LOG = RUNTIME / "audit_log.jsonl"
TRACE_DIR = RUNTIME / "traces"
EVAL_DIR = ROOT / "evals"
RESULTS_DIR = EVAL_DIR / "results"

ACTIONS = ["send_for_approvals", "request_clarification", "suggest_existing_tool", "hold_manual_review"]
RECOMMENDED_ACTION = {
    "route_for_approval": "send_for_approvals",
    "route_for_specialist_review": "send_for_approvals",
    "request_clarification": "request_clarification",
    "use_existing_tool": "suggest_existing_tool",
}

app = FastAPI(title="Procurement Request Copilot")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_lock = threading.Lock()
_latest: dict[str, dict] = {}   # request_id -> latest analysis response
_by_run: dict[str, dict] = {}   # run_id -> analysis response


# ---------------------------------------------------------------- helpers
def _audit_entries(request_id: str | None = None) -> list[dict]:
    if not AUDIT_LOG.is_file():
        return []
    entries = []
    for line in AUDIT_LOG.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if request_id is None or entry.get("request_id") == request_id:
            entries.append(entry)
    return entries


def _requester(raw: dict) -> dict:
    return pe.requester_info(str(raw.get("requester_id") or "").strip() or None)


def _status(request_id: str, audited: set[str]) -> str:
    if request_id in audited:
        return "Action recorded"
    return "Analysed" if request_id in _latest else "New"


def _banners(decision: dict, policy: dict | None) -> list[dict]:
    flags = set(decision["risk_flags"])
    banners = []
    if "llm_unavailable" in flags:
        banners.append({"kind": "warning", "flag": "llm_unavailable", "text": "AI analysis unavailable: showing rule-based result"})
    if "vendor_risk_unavailable" in flags:
        banners.append({"kind": "warning", "flag": "vendor_risk_unavailable",
                        "text": "Vendor-risk service unavailable: security status could not be verified"})
    vendor = (policy or {}).get("vendor") or {}
    derived = vendor.get("derived") or {}
    if "conflicting_vendor_evidence" in flags:
        record = (vendor.get("api") or {}).get("record") or {}
        registry = vendor.get("registry") or {}
        banners.append({"kind": "danger", "flag": "conflicting_vendor_evidence",
                        "text": "Registry and vendor-risk service disagree; neither is trusted on its own. Routed to Security.",
                        "compare": [
                            {"source": "Internal registry", "status": registry.get("security_status"),
                             "review_date": registry.get("security_review_date")},
                            {"source": "Vendor-risk service", "status": record.get("security_review_status"),
                             "review_date": record.get("last_review_date")},
                        ]})
    if "vendor_review_expired" in flags:
        dates = sorted({d for d in [derived.get("registry_review_date"), derived.get("api_review_date")] if d})
        banners.append({"kind": "danger", "flag": "vendor_review_expired",
                        "text": f"Security review expired: reviewed {', '.join(dates) or 'date unknown'}"
                                + (f"; expired on {derived['expired_on']}" if derived.get("expired_on") else "")})
    if "prompt_injection_detected" in flags:
        hits = (policy or {}).get("injection_hits") or []
        banners.append({"kind": "danger", "flag": "prompt_injection_detected",
                        "text": "Instruction-like text was found in business data. It was ignored and changed nothing.",
                        "quotes": [{"field": h["field"], "excerpt": h["excerpt"]} for h in hits[:3]]})
    return banners


def _consequence(action: str, decision: dict, requester_name: str, products: list[str]) -> str:
    roles = decision["required_approvals"]
    if action == "send_for_approvals":
        return (f"Sends the evidence pack to {len(roles)} approver{'s' if len(roles) != 1 else ''}: {', '.join(roles)}. "
                "Nothing is approved or purchased; each approver decides.")
    if action == "request_clarification":
        items = decision["missing_information"] or ["the missing details"]
        return f"Returns the request to {requester_name}, asking for: {', '.join(items)}. It leaves the review queue until they reply."
    if action == "suggest_existing_tool":
        return f"Tells {requester_name} that {', '.join(products) or 'an existing catalog product'} may already cover this need. No new purchase is started."
    return "Keeps the request open for a manual procurement review. No one is notified."


# ---------------------------------------------------------------- API
@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    s = get_settings()
    return {"app": "ok", "vendor_api": "ok" if launcher.is_healthy(s.vendor_risk_base_url) else "down",
            "llm": {"provider": s.llm_provider, "model": s.model_name, "configured": s.llm_configured}}


@app.get("/api/requests")
def list_requests() -> list[dict]:
    audited = {e.get("request_id") for e in _audit_entries()}
    rows = []
    for raw in da.all_requests():
        rid = str(raw.get("request_id") or "")
        requester = _requester(raw)
        cost = raw.get("annual_cost_usd")
        rows.append({
            "request_id": rid, "product_name": raw.get("product_name"), "vendor_name": raw.get("vendor_name"),
            "requester": requester.get("name") or raw.get("requester_id"), "department": requester.get("department"),
            "annual_cost": cost if isinstance(cost, (int, float)) and not isinstance(cost, bool) else "missing",
            "urgency": raw.get("urgency"), "status": _status(rid, audited),
        })
    return rows


@app.get("/api/requests/{request_id}")
def get_request(request_id: str) -> dict:
    try:
        raw = da.get_request(request_id)
    except KeyError:
        raise HTTPException(404, "No purchase request with this ID")
    return {"request": raw, "requester": _requester(raw)}


class NewRequest(BaseModel):
    requester_id: str | None = None
    product_name: str | None = None
    vendor_name: str | None = None
    category: str | None = None
    annual_cost_usd: float | None = None
    user_count: int | None = None
    business_justification: str | None = None
    data_access_level: str | None = None
    requested_integrations: list[str] | None = None
    urgency: str | None = None


@app.post("/api/requests")
def submit_request(body: NewRequest) -> dict:
    """US-6: every field may be blank; the copilot handles missing information."""
    with _lock:
        existing = da.load_submitted_requests()
        numbers = [int(m.group(1)) for r in existing if (m := re.fullmatch(r"REQ-U(\d+)", str(r.get("request_id", ""))))]
        rid = f"REQ-U{(max(numbers) + 1 if numbers else 1):03d}"
        record = {"request_id": rid, **body.model_dump()}
        da.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        da.SUBMITTED_REQUESTS_PATH.write_text(json.dumps(existing + [record], indent=2), encoding="utf-8")
    return record


class AnalyzeBody(BaseModel):
    request_id: str
    architecture: str = "single"


def _analyze(request_id: str, architecture: str) -> dict:
    decision, trace = handle_request_with_trace(request_id, architecture)
    d = decision.model_dump()
    policy = trace.get("policy")
    guard = trace.get("guardrails") or {}
    decision_type = guard.get("decision_type") or decision_from_recommendation(d["recommendation"]) or "route_for_specialist_review"
    # An internal error has no trustworthy recommendation: hold for manual review.
    recommended = "hold_manual_review" if trace.get("stop_reason") == "error" else RECOMMENDED_ACTION[decision_type]
    response = {
        "decision": d,
        "decision_type": decision_type,
        "recommended_action": recommended,
        "policy": {
            "approval_reasons": guard.get("approval_reasons") or {},
            "flag_reasons": (policy or {}).get("flag_reasons") or {},
            "requester": (policy or {}).get("requester"),
            "overlap_covering": guard.get("overlap_covering") or [],
            "catalog_candidates": [{"software_id": c["software_id"], "product_name": c["product_name"]}
                                   for c in (policy or {}).get("catalog_candidates", [])],
        },
        "questions_for_reviewer": guard.get("questions_for_reviewer") or [],
        "deterministic_evidence": guard.get("deterministic_evidence", len(d["evidence"])),
        "banners": _banners(d, policy),
        "trace_steps": trace["steps"],
        "trace_meta": {k: trace.get(k) for k in [
            "run_id", "architecture", "mode", "provider", "model", "stop_reason", "final_mode", "llm_calls",
            "tool_calls", "tokens", "latency_total_ms", "latency_active_ms", "llm_wait_ms", "error", "analyst_audit",
            "event_counts"]},
        "trace_summary": {"run_id": trace["run_id"], "architecture": trace["architecture"], "model": trace["model"],
                          "llm_calls": trace["llm_calls"], "tool_calls": trace["tool_calls"],
                          "latency_active_ms": trace["latency_active_ms"]},
    }
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    (TRACE_DIR / f"{trace['run_id']}.json").write_text(json.dumps({"decision": d, "trace": trace}, indent=1, default=str),
                                                       encoding="utf-8")
    with _lock:
        _latest[request_id] = response
        _by_run[trace["run_id"]] = {**response, "request_id": request_id}
    return response


@app.post("/api/analyze")
def analyze(body: AnalyzeBody) -> dict:  # sync def: FastAPI runs it in a threadpool
    if body.architecture not in {"single", "staged"}:
        raise HTTPException(400, "architecture must be single or staged")
    return _analyze(body.request_id, body.architecture)


class ActionBody(BaseModel):
    request_id: str
    run_id: str
    action: str
    reason: str | None = None


@app.post("/api/actions")
def record_action(body: ActionBody) -> dict:
    if body.action not in ACTIONS:
        raise HTTPException(400, f"action must be one of {ACTIONS}")
    run = _by_run.get(body.run_id)
    if run is None or run["request_id"] != body.request_id:
        raise HTTPException(400, "Unknown run for this request; analyse the request again.")
    recommended = run["recommended_action"]
    override = body.action != recommended
    reason = (body.reason or "").strip()
    if override and not reason:
        raise HTTPException(400, "A reason is required when the chosen action differs from the copilot recommendation.")
    requester = (run["policy"].get("requester") or {}).get("name") or "the requester"
    products = [c["product_name"] for c in run["policy"]["catalog_candidates"] if c["software_id"] in run["policy"]["overlap_covering"]]
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # audit timestamp, not policy logic
        "request_id": body.request_id,
        "run_id": body.run_id,
        "architecture": run["trace_meta"]["architecture"],
        "copilot_decision_type": run["decision_type"],
        "copilot_recommended_action": recommended,
        "chosen_action": body.action,
        "override": override,
        "reason": reason or None,
        "consequence": _consequence(body.action, run["decision"], requester, products),
    }
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with _lock, AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


@app.get("/api/consequence")
def consequence(run_id: str, action: str) -> dict:
    run = _by_run.get(run_id)
    if run is None or action not in ACTIONS:
        raise HTTPException(400, "Unknown run or action")
    requester = (run["policy"].get("requester") or {}).get("name") or "the requester"
    products = [c["product_name"] for c in run["policy"]["catalog_candidates"] if c["software_id"] in run["policy"]["overlap_covering"]]
    return {"text": _consequence(action, run["decision"], requester, products),
            "override": action != run["recommended_action"], "recommended_action": run["recommended_action"]}


@app.get("/api/audit")
def audit(request_id: str | None = None) -> list[dict]:
    return _audit_entries(request_id)


# ---------------------------------------------------------------- US-7: compare both architectures
def _differences(a: dict, b: dict) -> list[str]:
    da, db = a["decision"], b["decision"]
    out = []
    if a["decision_type"] != b["decision_type"]:
        out.append(f"Decision differs: A {a['decision_type']}, B {b['decision_type']}")
    for label, key in [("approvals", "required_approvals"), ("flags", "risk_flags"), ("missing information", "missing_information")]:
        only_a, only_b = sorted(set(da[key]) - set(db[key])), sorted(set(db[key]) - set(da[key]))
        if only_a or only_b:
            out.append(f"{label.capitalize()}: only A {only_a or '[]'}, only B {only_b or '[]'}")
    ma, mb = a["trace_meta"], b["trace_meta"]
    out.append(f"Cost: A {ma['llm_calls']} LLM / {ma['tool_calls']} tool calls, {round(ma['latency_active_ms'])} ms active; "
               f"B {mb['llm_calls']} LLM / {mb['tool_calls']} tool calls, {round(mb['latency_active_ms'])} ms active")
    return out


@app.post("/api/compare")
def compare(body: AnalyzeBody) -> dict:
    """Run both architectures on one request (US-7). Each run is an ordinary analysis with its own trace."""
    a = _analyze(body.request_id, "single")
    b = _analyze(body.request_id, "staged")
    return {"single": a, "staged": b, "differences": _differences(a, b)}


# ---------------------------------------------------------------- evidence pack for approvers
@app.get("/api/evidence-pack/{run_id}", response_class=PlainTextResponse)
def evidence_pack(run_id: str) -> PlainTextResponse:
    """Markdown evidence pack for one analysis: what an approver would receive. Nothing is sent anywhere."""
    run = _by_run.get(run_id)
    if run is None:
        raise HTTPException(404, "Unknown run; analyse the request again.")
    d, m, reasons = run["decision"], run["trace_meta"], run["policy"]["approval_reasons"]
    lines = [f"# Evidence pack: {d['request_id']}", "",
             f"Copilot recommendation (advisory; nothing is approved or purchased): {d['recommendation']}", "",
             f"Next step: {d['next_step']}", "", "## Approvals required", ""]
    for role in d["required_approvals"]:
        lines.append(f"- {role}: " + "; ".join(f"{r['rule']} ({r['policy_ref']}) {r['detail']}" for r in reasons.get(role, [])))
    lines += ["", "## Risk flags", ""] + [f"- {f}" for f in d["risk_flags"] or ["none"]]
    lines += ["", "## Missing information / could not verify", ""] + [f"- {x}" for x in d["missing_information"] or ["none"]]
    lines += ["", "## Evidence", "", "| Source | Finding | Reference |", "|---|---|---|"]
    lines += [f"| {e['source']} | {e['finding'].replace('|', '/')} | {(e['reference'] or '').replace('|', '/')} |" for e in d["evidence"]]
    lines += ["", f"Run {m['run_id']} · {m['architecture']} · {m['provider']} {m['model']} · stop_reason {m['stop_reason']} · "
              f"LLM calls {m['llm_calls']} · tool calls {m['tool_calls']}", "",
              "Request text quoted above is business data from the requester or vendor, not instructions."]
    headers = {"Content-Disposition": f'attachment; filename="evidence-pack-{run_id}.md"'}
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/markdown", headers=headers)


# ---------------------------------------------------------------- evaluation dashboard (committed results only)
@app.get("/api/eval")
def eval_summary() -> dict:
    path = RESULTS_DIR / "summary.json"
    if not path.is_file():
        raise HTTPException(404, "No evaluation results yet. Run: python evals/run_all.py --no-llm")
    cases = json.loads((EVAL_DIR / "golden_cases.json").read_text(encoding="utf-8"))
    return {
        "summary": json.loads(path.read_text(encoding="utf-8")),
        "cases": [{"case_id": c["case_id"], "request_id": c["request_id"], "title": c["title"], "tests": c["tests"]} for c in cases],
        "walkthroughs": (RESULTS_DIR / "scenario_walkthroughs.md").is_file(),
    }


@app.get("/api/eval/runs/{arch}/{case_id}")
def eval_run(arch: str, case_id: str) -> dict:
    if arch not in {"single", "staged", "rules_only"} or not re.fullmatch(r"G-\d{2}", case_id):
        raise HTTPException(400, "Unknown architecture or case")
    files = sorted((RESULTS_DIR / "runs" / arch).glob(f"{case_id}_t*.json"))
    if not files:
        raise HTTPException(404, "No stored run for this case")
    rec = json.loads(files[0].read_text(encoding="utf-8"))
    t = rec["trace"]
    return {"case_id": case_id, "arch": arch, "status": rec["status"], "decision": rec["decision"], "scores": rec["scores"],
            "steps": t["steps"], "stop_reason": t["stop_reason"], "final_mode": t["final_mode"], "error": t.get("error"),
            "provider": rec.get("provider"), "model": rec.get("model"), "analyst_audit": t.get("analyst_audit")}


@app.get("/api/eval/walkthroughs", response_class=PlainTextResponse)
def eval_walkthroughs() -> str:
    path = RESULTS_DIR / "scenario_walkthroughs.md"
    if not path.is_file():
        raise HTTPException(404, "Run python evals/render_walkthroughs.py")
    return path.read_text(encoding="utf-8")
