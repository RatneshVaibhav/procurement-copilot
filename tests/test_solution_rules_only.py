"""T15: with LLM_SIMULATE_OUTAGE=1, handle_request returns a valid ProcurementDecision for
all official and fixture requests, matching golden except requires_ai aspects and the
extra llm_unavailable flag."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from helpers import GOLDEN, in_process_vendor_api
from src import guardrails
from src.contracts import ProcurementDecision
from src.solution import handle_request, handle_request_with_trace


class RulesOnlySolutionTests(unittest.TestCase):
    def test_golden_cases_under_llm_outage(self):
        for case in GOLDEN:
            skip = set(case.get("requires_ai", []))
            with self.subTest(case=case["case_id"]), mock.patch.dict(os.environ, {"LLM_SIMULATE_OUTAGE": "1"}), \
                    in_process_vendor_api(down=case["fault"] == "vendor_api_down"):
                for arch in ["single", "staged"]:
                    decision = handle_request(case["request_id"], arch)
                    self.assertIsInstance(decision, ProcurementDecision)
                    ProcurementDecision.model_validate(decision.model_dump())
                    self.assertTrue(decision.human_review_required)
                    self.assertIn("llm_unavailable", decision.risk_flags)
                    roles, flags = set(decision.required_approvals), set(decision.risk_flags) - {"llm_unavailable"}
                    if "approvals" not in skip:
                        req, opt = set(case["approvals"]["required"]), set(case["approvals"]["optional"])
                        self.assertTrue(req <= roles <= req | opt, f"{arch} approvals {sorted(roles)}")
                    if "flags" not in skip:
                        req = set(case["flags"]["required"]) - {"llm_unavailable"}
                        opt = set(case["flags"]["optional"])
                        self.assertTrue(req <= flags <= req | opt, f"{arch} flags {sorted(flags)}")
                    if "decision" not in skip:
                        self.assertIn(guardrails.decision_from_recommendation(decision.recommendation),
                                      case["decision_type"]["acceptable"])
                    self.assertFalse(set(case["forbidden_approvals"]) & roles)
                    self.assertFalse(guardrails.output_filter_hit(decision.recommendation))
                    self.assertFalse(guardrails.output_filter_hit(decision.next_step))

    def test_rules_only_mode_has_no_llm_flag(self):
        with in_process_vendor_api():
            decision, trace = handle_request_with_trace("REQ-1002", "single", mode="rules_only")
        self.assertNotIn("llm_unavailable", decision.risk_flags)
        self.assertEqual(trace["mode"], "rules_only")
        self.assertEqual(decision.telemetry.llm_calls, 0)
        self.assertEqual(decision.telemetry.tool_calls, 5)

    def test_unknown_request_returns_clarification(self):  # D-07.8
        decision = handle_request("REQ-DOES-NOT-EXIST", "single")
        self.assertTrue(decision.recommendation.startswith("Request clarification:"))
        self.assertTrue(decision.human_review_required)

    def test_odd_request_ids_and_setup_failures_still_return_decisions(self):
        for rid in [None, 1001, "../../etc/passwd"]:
            with self.subTest(rid=rid):
                decision = handle_request(rid, "single")  # type: ignore[arg-type]
                self.assertIsInstance(decision, ProcurementDecision)
        with mock.patch("src.solution.get_reference_date", side_effect=RuntimeError("no date")), \
                self.assertLogs("src.solution", level="ERROR"):
            decision = handle_request("REQ-1001", "single")
        self.assertTrue(decision.human_review_required)
        with mock.patch("src.solution.da.get_request", side_effect=ValueError("bad json")), \
                self.assertLogs("src.solution", level="ERROR"):
            self.assertIsInstance(handle_request("REQ-1001", "staged"), ProcurementDecision)

    def test_unknown_architecture_still_returns_decision(self):
        with in_process_vendor_api():
            decision = handle_request("REQ-1001", "triple")  # type: ignore[arg-type]
        self.assertIsInstance(decision, ProcurementDecision)

    def test_internal_error_still_returns_decision(self):
        with in_process_vendor_api(), mock.patch("src.fallback.tools.policy_for", side_effect=RuntimeError("boom")), \
                self.assertLogs("src.solution", level="ERROR"):
            decision, trace = handle_request_with_trace("REQ-1001", "single", mode="rules_only")
        self.assertTrue(decision.human_review_required)
        self.assertEqual(trace["stop_reason"], "error")
        self.assertIn("Procurement", decision.required_approvals)


if __name__ == "__main__":
    unittest.main()
