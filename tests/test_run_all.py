"""Eval harness logic (run_all.py): status classification, resume, provider guard, env restore.
handle_request_with_trace is stubbed: no network, no LLM."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
import run_all  # noqa: E402

from src.contracts import ProcurementDecision  # noqa: E402

GOLDEN = {c["case_id"]: c for c in json.loads((ROOT / "evals" / "golden_cases.json").read_text(encoding="utf-8"))}


def stub_run(kind=None, seen=None):
    def run(request_id, arch, mode):
        if seen is not None:
            seen.append({k: os.environ.get(k) for k in ["VENDOR_RISK_BASE_URL", "LLM_SIMULATE_OUTAGE"]})
        decision = ProcurementDecision(request_id=request_id, recommendation="Route for approval: x", next_step="y",
                                       required_approvals=["Manager"], risk_flags=[], human_review_required=True)
        trace = {"llm_error_kind": kind, "mode": mode, "provider": "p", "model": "m", "error": kind, "tokens": {},
                 "llm_calls": 0, "tool_calls": 0, "stop_reason": "x", "final_mode": "fallback", "proposals": [],
                 "event_counts": {}, "guardrails": {}}
        return decision, trace
    return run


class RunAllTests(unittest.TestCase):
    def test_status_classification(self):
        g01, g22 = GOLDEN["G-01"], GOLDEN["G-22"]
        self.assertEqual(run_all.run_status({"llm_error_kind": "rate_limited"}, g01), "infra_error")
        self.assertEqual(run_all.run_status({"llm_error_kind": "server"}, g01), "infra_error")
        self.assertEqual(run_all.run_status({"llm_error_kind": "auth"}, g01), "config_error")
        self.assertEqual(run_all.run_status({"llm_error_kind": "not_configured"}, g01), "config_error")
        self.assertEqual(run_all.run_status({"llm_error_kind": "simulated"}, g01), "ok")
        self.assertEqual(run_all.run_status({"llm_error_kind": "bad_request"}, g01), "ok")  # model/request failure is scored
        self.assertEqual(run_all.run_status({"llm_error_kind": "rate_limited"}, g22), "ok")  # the fault case itself
        self.assertEqual(run_all.run_status({}, g01), "ok")

    def test_resume_rules(self):
        ok, infra, cfg = {"status": "ok"}, {"status": "infra_error"}, {"status": "config_error"}
        self.assertTrue(run_all.should_skip(ok, True, False))
        self.assertTrue(run_all.should_skip(infra, True, False))
        self.assertFalse(run_all.should_skip(infra, True, True))
        self.assertFalse(run_all.should_skip(cfg, True, False))  # config errors always re-run
        self.assertFalse(run_all.should_skip(ok, False, False))
        self.assertFalse(run_all.should_skip(None, True, True))

    def test_provider_guard_across_architectures(self):
        records = [{"arch": "single", "provider": "gemini", "model": "gemini-2.5-flash", "status": "ok"},
                   {"arch": "rules_only", "provider": None, "model": None, "status": "ok"}]
        run_all.check_provider(records, "gemini", "gemini-2.5-flash")
        with self.assertRaises(SystemExit):
            run_all.check_provider(records, "groq", "openai/gpt-oss-20b")  # B on groq next to A on gemini

    def test_fault_env_is_applied_then_restored(self):
        before = {k: os.environ.get(k) for k in ["VENDOR_RISK_BASE_URL", "LLM_SIMULATE_OUTAGE"]}
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            for cid in ["G-21", "G-22"]:
                rec = run_all.run_case(GOLDEN[cid], "single", 1, Path(tmp), run=stub_run(seen=seen))
                self.assertTrue(Path(tmp, "runs", "single", f"{cid}_t1.json").is_file())
                self.assertEqual(rec["status"], "ok")
        self.assertEqual(seen[0]["VENDOR_RISK_BASE_URL"], run_all.DOWN_URL)
        self.assertEqual(seen[1]["LLM_SIMULATE_OUTAGE"], "1")
        self.assertEqual({k: os.environ.get(k) for k in before}, before)

    def test_config_error_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = run_all.run_case(GOLDEN["G-01"], "single", 1, Path(tmp), run=stub_run(kind="not_configured"))
        self.assertEqual(rec["status"], "config_error")

    def test_provider_org_id_is_redacted_in_stored_runs(self):
        fake = "Rate limit reached in organization `org_01abcdefghijklmnopqrst` on tokens per day"
        with tempfile.TemporaryDirectory() as tmp:
            rec = run_all.run_case(GOLDEN["G-01"], "single", 1, Path(tmp), run=stub_run(kind=fake))
            stored = run_all.run_path(Path(tmp), "single", "G-01", 1).read_text(encoding="utf-8")
        self.assertNotIn("org_01abcdefghijklmnopqrst", stored)
        self.assertIn("org_[redacted]", rec["error"])

    def test_reasoning_effort_off_clears_the_setting(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"LLM_REASONING_EFFORT": "low"}), \
                mock.patch.object(sys, "argv", ["run_all.py", "--reasoning-effort", "off", "--summary-only", "--results-dir", tmp]):
            run_all.main()
            self.assertEqual(os.environ["LLM_REASONING_EFFORT"], "")


if __name__ == "__main__":
    unittest.main()
