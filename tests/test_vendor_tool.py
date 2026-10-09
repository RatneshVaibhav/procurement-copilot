from __future__ import annotations

import os
import unittest
from unittest import mock

import requests

from helpers import in_process_vendor_api
from src import vendor_client
from src.tools import RunContext, execute


class VendorClientTests(unittest.TestCase):
    def test_ok(self):
        with in_process_vendor_api():
            r = vendor_client.get_vendor_risk_classified("CodeMate")
        self.assertEqual(r["outcome"], "ok")
        self.assertEqual(r["record"]["security_review_status"], "approved")
        self.assertEqual(r["attempts"], 1)

    def test_404_not_found_no_retry(self):
        with in_process_vendor_api():
            r = vendor_client.get_vendor_risk_classified("ChurnRadar Inc")
        self.assertEqual(r["outcome"], "not_found")
        self.assertEqual(r["status_code"], 404)
        self.assertEqual(r["attempts"], 1)

    def test_503_unavailable_after_one_retry(self):
        with in_process_vendor_api():
            r = vendor_client.get_vendor_risk_classified("NimbusAI")
        self.assertEqual(r["outcome"], "unavailable")
        self.assertEqual(r["status_code"], 503)
        self.assertEqual(r["attempts"], 2)
        self.assertEqual(r["error"], "HTTP 503")  # code-derived; server text only in "detail"
        self.assertTrue(r["detail"])

    def test_connection_refused_closed_port(self):
        with mock.patch.dict(os.environ, {"VENDOR_RISK_BASE_URL": "http://127.0.0.1:9"}), \
                mock.patch.object(vendor_client, "RETRY_BACKOFF_SECONDS", 0):
            r = vendor_client.get_vendor_risk_classified("CodeMate")
        self.assertEqual(r["outcome"], "unavailable")
        self.assertEqual(r["attempts"], 2)
        self.assertIn("connection error", r["error"])

    def test_timeout(self):
        with mock.patch.object(vendor_client.requests, "get", side_effect=requests.Timeout("slow")), \
                mock.patch.object(vendor_client, "RETRY_BACKOFF_SECONDS", 0):
            r = vendor_client.get_vendor_risk_classified("CodeMate")
        self.assertEqual(r["outcome"], "unavailable")
        self.assertIn("timeout", r["error"])

    def test_never_raises_on_unexpected_error(self):
        with mock.patch.object(vendor_client.requests, "get", side_effect=requests.RequestException("boom")), \
                mock.patch.object(vendor_client, "RETRY_BACKOFF_SECONDS", 0):
            self.assertEqual(vendor_client.get_vendor_risk_classified("X")["outcome"], "unavailable")


class VendorToolTests(unittest.TestCase):
    def test_casing_and_whitespace_resolve_to_registry_name(self):
        with in_process_vendor_api():
            ctx = RunContext("REQ-X104")
            result = execute("get_vendor_status", {"vendor_name": " signalwatch "}, ctx, actor="single")
        self.assertEqual(result["canonical_name"], "SignalWatch")
        self.assertEqual(result["api"]["outcome"], "ok")
        self.assertTrue(result["derived"]["conflict"])
        self.assertTrue(result["derived"]["expired"])

    def test_server_error_text_stays_out_of_engine_output(self):
        from src import policy_engine as pe
        with in_process_vendor_api():
            result = pe.evaluate("REQ-1009", RunContext("REQ-1009"))
        detail = "temporarily unavailable"
        self.assertFalse(any(detail in e.finding for e in result.evidence))
        self.assertFalse(any(detail in r.detail for rs in result.flag_reasons.values() for r in rs))
        self.assertIn(detail, result.vendor.untrusted_text["api_error_detail"])

    def test_unavailable_is_never_favorable(self):
        with in_process_vendor_api(down=True):
            ctx = RunContext("REQ-1001")
            result = execute("get_vendor_status", {"vendor_name": "SignFlow"}, ctx, actor="single")
        self.assertEqual(result["api"]["outcome"], "unavailable")
        self.assertIsNone(result["api"]["record"])
        self.assertIsNone(result["derived"]["api_class"])

    def test_api_called_once_per_run(self):
        calls = []

        def fetch(name):
            calls.append(name)
            return {"outcome": "unavailable", "status_code": 503, "record": None, "error": "x",
                    "attempts": 2, "duration_ms": 0, "endpoint": "e"}

        ctx = RunContext("REQ-1001", vendor_fetch=fetch)
        execute("get_vendor_status", {"vendor_name": "SignFlow"}, ctx, actor="single")
        execute("evaluate_policy_rules", {"request_id": "REQ-1001"}, ctx, actor="single")
        self.assertEqual(calls, ["SignFlow"])

    def test_injection_in_api_notes_is_untrusted_and_scanned(self):
        with in_process_vendor_api():
            ctx = RunContext("REQ-X107")
            result = execute("get_vendor_status", {"vendor_name": "LedgerLens"}, ctx, actor="single")
        self.assertTrue(result["injection_scan"]["detected"])
        self.assertIn("notes", result["untrusted_text"]["api_text"])
        self.assertNotIn("notes", result["api"]["record"])


if __name__ == "__main__":
    unittest.main()
