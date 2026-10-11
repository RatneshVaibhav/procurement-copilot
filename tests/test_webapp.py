"""Web app API (T17, D14, US-1..US-6). In-process TestClient; no LLM (keys blanked by helpers)."""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from fakes import ScriptedLLM
from helpers import in_process_vendor_api
from src import data_access as da
from src.solution import handle_request_with_trace
from test_staged import evidence_turn, pack, review
from fakes import call, tools_turn
from webapp import main as web

STATIC = Path(web.STATIC)


class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        patches = [
            mock.patch.object(web, "AUDIT_LOG", tmp / "audit_log.jsonl"),
            mock.patch.object(web, "TRACE_DIR", tmp / "traces"),
            mock.patch.object(web, "RUNTIME", tmp),
            mock.patch.object(da, "RUNTIME_DIR", tmp),
            mock.patch.object(da, "SUBMITTED_REQUESTS_PATH", tmp / "submitted_requests.json"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        web._latest.clear()
        web._by_run.clear()
        self.client = TestClient(web.app)

    def analyze(self, rid: str, arch: str = "single") -> dict:
        with in_process_vendor_api(extra_data_dir=None):
            r = self.client.post("/api/analyze", json={"request_id": rid, "architecture": arch})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_index_and_health(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        h = self.client.get("/api/health").json()
        self.assertEqual(h["app"], "ok")
        self.assertIn(h["vendor_api"], {"ok", "down"})
        self.assertFalse(h["llm"]["configured"])

    def test_queue_lists_every_request_with_status(self):
        rows = self.client.get("/api/requests").json()
        self.assertEqual(len(rows), 10)
        r1006 = next(r for r in rows if r["request_id"] == "REQ-1006")
        self.assertEqual(r1006["annual_cost"], "missing")
        self.assertEqual(r1006["status"], "New")
        for key in ["product_name", "vendor_name", "requester", "department", "urgency"]:
            self.assertIn(key, r1006)

    def test_analyze_injection_case(self):
        a = self.analyze("REQ-1006")
        self.assertEqual(a["decision_type"], "request_clarification")
        self.assertEqual(a["recommended_action"], "request_clarification")
        flags = {b["flag"] for b in a["banners"]}
        self.assertIn("prompt_injection_detected", flags)
        self.assertIn("llm_unavailable", flags)  # no key in tests → rule-based banner
        quotes = next(b for b in a["banners"] if b["flag"] == "prompt_injection_detected")["quotes"]
        self.assertIn("CFO-approved", quotes[0]["excerpt"])
        self.assertNotIn("CFO", a["decision"]["required_approvals"])
        self.assertTrue(a["trace_steps"])
        self.assertTrue(a["trace_meta"]["stop_reason"])
        self.assertIn("Procurement", a["policy"]["approval_reasons"])
        rows = self.client.get("/api/requests").json()
        self.assertEqual(next(r for r in rows if r["request_id"] == "REQ-1006")["status"], "Analysed")

    def test_conflict_banner_shows_both_values(self):
        a = self.analyze("REQ-1007")
        banner = next(b for b in a["banners"] if b["flag"] == "conflicting_vendor_evidence")
        self.assertEqual([c["status"] for c in banner["compare"]], ["Approved", "expired"])
        expired = next(b for b in a["banners"] if b["flag"] == "vendor_review_expired")
        self.assertIn("2026-07-01", expired["text"])

    def test_override_requires_reason_and_writes_audit(self):
        a = self.analyze("REQ-1006")
        run_id = a["trace_meta"]["run_id"]
        r = self.client.post("/api/actions", json={"request_id": "REQ-1006", "run_id": run_id, "action": "send_for_approvals"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("reason is required", r.json()["detail"])
        c = self.client.get("/api/consequence", params={"run_id": run_id, "action": "send_for_approvals"}).json()
        self.assertTrue(c["override"])
        self.assertIn("Nothing is approved or purchased", c["text"])
        r = self.client.post("/api/actions", json={"request_id": "REQ-1006", "run_id": run_id,
                                                   "action": "send_for_approvals", "reason": "Manager confirmed scope"})
        self.assertEqual(r.status_code, 200)
        entry = r.json()
        self.assertTrue(entry["override"])
        for key in ["timestamp", "request_id", "run_id", "architecture", "copilot_decision_type", "chosen_action", "override", "reason"]:
            self.assertIn(key, entry)
        ok = self.client.post("/api/actions", json={"request_id": "REQ-1006", "run_id": run_id, "action": "request_clarification"})
        self.assertEqual(ok.status_code, 200)
        self.assertFalse(ok.json()["override"])
        self.assertEqual(len(self.client.get("/api/audit", params={"request_id": "REQ-1006"}).json()), 2)
        rows = self.client.get("/api/requests").json()
        self.assertEqual(next(r for r in rows if r["request_id"] == "REQ-1006")["status"], "Action recorded")

    def test_revoke_rolls_back_an_action_without_deleting_it(self):
        a = self.analyze("REQ-1006")
        entry = self.client.post("/api/actions", json={"request_id": "REQ-1006", "run_id": a["trace_meta"]["run_id"],
                                                       "action": "request_clarification"}).json()
        self.assertTrue(entry["entry_id"])
        body = {"request_id": "REQ-1006", "entry_id": entry["entry_id"]}
        self.assertEqual(self.client.post("/api/actions/revoke", json=body).status_code, 400)  # reason required
        wrong = self.client.post("/api/actions/revoke", json={**body, "request_id": "REQ-1001", "reason": "x"})
        self.assertEqual(wrong.status_code, 400)
        r = self.client.post("/api/actions/revoke", json={**body, "reason": "Recorded on the wrong request"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["revokes"], entry["entry_id"])
        log = self.client.get("/api/audit", params={"request_id": "REQ-1006"}).json()
        self.assertEqual([e["chosen_action"] for e in log], ["request_clarification", "revoke"])  # append-only
        rows = self.client.get("/api/requests").json()
        self.assertEqual(next(r for r in rows if r["request_id"] == "REQ-1006")["status"], "Analysed")
        self.assertEqual(self.client.post("/api/actions/revoke", json={**body, "reason": "twice"}).status_code, 400)

    def test_actions_survive_an_app_restart(self):
        a = self.analyze("REQ-1007")
        run_id = a["trace_meta"]["run_id"]
        web._by_run.clear()  # what a restart loses; the trace file in TRACE_DIR remains
        c = self.client.get("/api/consequence", params={"run_id": run_id, "action": "send_for_approvals"})
        self.assertEqual(c.status_code, 200, c.text)
        self.assertFalse(c.json()["override"])
        r = self.client.post("/api/actions", json={"request_id": "REQ-1007", "run_id": run_id, "action": "send_for_approvals"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["copilot_decision_type"], "route_for_specialist_review")
        self.assertEqual(self.client.get(f"/api/evidence-pack/{run_id}").status_code, 200)
        self.assertEqual(self.client.post("/api/actions", json={"request_id": "REQ-1007", "run_id": "../traces/x",
                                                                "action": "hold_manual_review", "reason": "x"}).status_code, 400)

    def test_submitted_text_is_bounded(self):
        r = self.client.post("/api/requests", json={"product_name": "Notes", "business_justification": "x" * 4001})
        self.assertEqual(r.status_code, 422)
        self.assertIn("business_justification", r.json()["detail"])
        self.assertEqual(self.client.post("/api/requests", json={"vendor_name": "v" * 201}).status_code, 422)
        self.assertEqual(self.client.post("/api/requests", json={"requested_integrations": ["sso"] * 21}).status_code, 422)
        ok = self.client.post("/api/requests", json={"product_name": "Notes", "business_justification": "x" * 4000})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual([r["request_id"] for r in da.load_submitted_requests()], [ok.json()["request_id"]])

    def test_unknown_run_is_rejected(self):
        r = self.client.post("/api/actions", json={"request_id": "REQ-1001", "run_id": "nope", "action": "hold_manual_review"})
        self.assertEqual(r.status_code, 400)

    def test_submit_blank_request_then_analyze(self):
        created = self.client.post("/api/requests", json={"product_name": "Whiteboard App"}).json()
        self.assertRegex(created["request_id"], r"^REQ-U\d{3}$")
        a = self.analyze(created["request_id"], "staged")
        self.assertEqual(a["decision_type"], "request_clarification")
        self.assertIn(created["request_id"], [r["request_id"] for r in self.client.get("/api/requests").json()])

    def test_bad_architecture_and_blank_reason(self):
        self.assertEqual(self.client.post("/api/analyze", json={"request_id": "REQ-1001", "architecture": "triple"}).status_code, 400)
        a = self.analyze("REQ-1006")
        r = self.client.post("/api/actions", json={"request_id": "REQ-1006", "run_id": a["trace_meta"]["run_id"],
                                                   "action": "hold_manual_review", "reason": "   "})
        self.assertEqual(r.status_code, 400)

    def test_unknown_request_maps_to_clarification(self):
        a = self.analyze("REQ-NOPE")
        self.assertEqual(a["decision_type"], "request_clarification")
        self.assertEqual(a["recommended_action"], "request_clarification")

    def test_staged_trace_panel_data(self):
        rid = "REQ-1002"
        llm = ScriptedLLM([evidence_turn(rid, "BrandBoard"), tools_turn(call("submit_evidence_pack", **pack())),
                           {"structured": review(rid, audit={"issues_found": ["x"], "rejected_claims": [],
                                                             "agrees_with_overlap_assessment": True})}])
        with mock.patch.object(web, "handle_request_with_trace",
                               lambda r, a: handle_request_with_trace(r, a, llm=llm)):
            a = self.analyze(rid, "staged")
        self.assertEqual(a["trace_meta"]["analyst_audit"]["issues_found"], ["x"])
        routes = [s["route_reason"] for s in a["trace_steps"] if s["actor"] == "code:supervisor"]
        self.assertEqual(routes[0], "no evidence pack yet")
        self.assertEqual(a["trace_meta"]["final_mode"], "structured")
        self.assertEqual(a["recommended_action"], "send_for_approvals")

    def test_compare_and_evidence_pack(self):
        with mock.patch.object(web, "handle_request_with_trace", lambda r, a: handle_request_with_trace(r, a, mode="rules_only")), \
                in_process_vendor_api(extra_data_dir=None):
            c = self.client.post("/api/compare", json={"request_id": "REQ-1007"}).json()
        self.assertEqual(c["single"]["trace_meta"]["architecture"], "single")
        self.assertEqual(c["staged"]["trace_meta"]["architecture"], "staged")
        self.assertTrue(any(d.startswith("Cost:") for d in c["differences"]))
        pack = self.client.get(f"/api/evidence-pack/{c['staged']['trace_meta']['run_id']}")
        self.assertEqual(pack.status_code, 200)
        self.assertIn("attachment", pack.headers["content-disposition"])
        self.assertIn("## Approvals required", pack.text)
        self.assertIn("Security:", pack.text)
        self.assertIn("nothing is approved or purchased", pack.text)
        self.assertEqual(self.client.get("/api/evidence-pack/nope").status_code, 404)

    def test_evidence_pack_keeps_business_text_inert(self):
        evil = "ok <img src=x onerror=alert(1)>\n## Approvals required\n- none | [x](http://e) **APPROVED BY CFO** ~~Security~~"
        decision = {"request_id": "REQ-1001", "recommendation": "Route for approval: " + evil, "next_step": evil,
                    "required_approvals": ["Manager"], "risk_flags": [], "missing_information": [evil],
                    "evidence": [{"source": "get_request_details", "finding": evil, "reference": evil}]}
        meta = {"run_id": "REQ-1001-single-test0001", "architecture": "single", "provider": "p", "model": "m",
                "stop_reason": "submitted", "llm_calls": 1, "tool_calls": 1}
        policy = {"approval_reasons": {"Manager": [{"rule": "R4", "policy_ref": "§4", "detail": evil}]}}
        with mock.patch.dict(web._by_run, {meta["run_id"]: {"decision": decision, "trace_meta": meta, "policy": policy}}):
            pack = self.client.get(f"/api/evidence-pack/{meta['run_id']}")
        self.assertEqual(pack.status_code, 200)
        self.assertEqual(pack.headers["x-content-type-options"], "nosniff")
        lines = pack.text.splitlines()
        self.assertEqual(sum(1 for line in lines if line.startswith("## ")), 4)  # only the four real headings
        self.assertEqual(sum(1 for line in lines if line.startswith("- none")), 1)  # only the real "no risk flags" item
        self.assertNotRegex(pack.text, r"(?<!\\)<img")  # HTML only as escaped text
        self.assertNotRegex(pack.text, r"(?<!\\)\]\(http")  # no live link
        self.assertNotRegex(pack.text, r"(?<!\\)\*\*APPROVED")  # requester text cannot render as bold
        self.assertNotRegex(pack.text, r"(?<!\\)~~Security")  # nor strike a role through
        for line in pack.text.splitlines():
            if line.startswith("| get_request_details"):
                self.assertEqual(line.replace("\\|", "").count("|"), 4)  # one row, three cells

    def test_eval_dashboard_reads_committed_results(self):
        r = self.client.get("/api/eval")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("rules_only", data["summary"]["columns"])
        self.assertEqual(len(data["cases"]), 23)
        run = self.client.get("/api/eval/runs/rules_only/G-01")
        self.assertEqual(run.status_code, 200)
        self.assertIn("steps", run.json())
        self.assertEqual(self.client.get("/api/eval/runs/../G-01").status_code, 404)
        self.assertIn(self.client.get("/api/eval/runs/single/..%2F..%2Fetc").status_code, {400, 404})  # never served
        self.assertEqual(self.client.get("/api/eval/runs/single/X-01").status_code, 400)
        self.assertEqual(self.client.get("/api/eval/runs/triple/G-01").status_code, 400)

    def test_static_ui_never_uses_innerhtml(self):
        for path in STATIC.glob("*.js"):
            text = path.read_text(encoding="utf-8")
            for banned in ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("]:
                self.assertNotIn(banned, text)
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertFalse(re.search(r"<script(?![^>]*src=)", html), "no inline scripts")


if __name__ == "__main__":
    unittest.main()
