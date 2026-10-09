from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from helpers import in_process_vendor_api
from src.solution import handle_request_with_trace
from src.tracing import ACTORS, Trace


class TraceTests(unittest.TestCase):
    def assert_trace(self, trace: dict):
        self.assertTrue(trace["steps"])
        self.assertTrue(trace["stop_reason"])
        self.assertIn(trace["final_mode"], {"tool_call", "finalizer", "fallback"})
        for step in trace["steps"]:
            self.assertIn(step["actor"], ACTORS)
            self.assertLessEqual(len(step["summary_in"]), 300)
            self.assertLessEqual(len(step["summary_out"]), 300)
        json.dumps(trace)  # serialisable
        self.assertGreaterEqual(trace["latency_total_ms"], trace["latency_active_ms"])

    def test_trace_has_steps_and_stop_reason(self):
        with in_process_vendor_api():
            for mode in ["rules_only", "llm"]:
                with mock.patch.dict(os.environ, {"LLM_SIMULATE_OUTAGE": "1"}):
                    _, trace = handle_request_with_trace("REQ-1007", "staged", mode=mode)
                self.assert_trace(trace)
                self.assertTrue(trace["tool_log"])
                self.assertIsNotNone(trace["policy"])
        _, trace = handle_request_with_trace("REQ-NOPE", "single")
        self.assert_trace(trace)
        self.assertEqual(trace["stop_reason"], "unknown_request")

    def test_unknown_actor_rejected(self):
        with self.assertRaises(ValueError):
            Trace("REQ-1", "single", "llm").step("agent:third", "x")

    def test_run_id_is_path_safe(self):
        run_id = Trace("../../etc/x", "single", "llm").run_id
        self.assertNotIn("/", run_id)
        self.assertNotIn("..", run_id)

    def test_summaries_are_clipped(self):
        t = Trace("REQ-1", "single", "llm")
        t.step("code:gate", "x", "a" * 1000, "b" * 1000)
        self.assertEqual(len(t.steps[0]["summary_in"]), 300)


if __name__ == "__main__":
    unittest.main()
