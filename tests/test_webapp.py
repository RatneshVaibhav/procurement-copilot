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

    def test_static_ui_never_uses_innerhtml(self):
        for path in STATIC.glob("*.js"):
            text = path.read_text(encoding="utf-8")
            for banned in ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("]:
                self.assertNotIn(banned, text)
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertFalse(re.search(r"<script(?![^>]*src=)", html), "no inline scripts")


if __name__ == "__main__":
    unittest.main()
