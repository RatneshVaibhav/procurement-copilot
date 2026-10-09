"""Architecture B (D9, D12): deterministic supervisor + 2 specialists. ScriptedLLM only."""
from __future__ import annotations

import unittest
from unittest import mock

from fakes import ScriptedLLM, call, tools_turn
from helpers import in_process_vendor_api
from src.agents import staged_agent
from src.llm_client import LLMRateLimited, ToolUseFailed
from src.tools import UNTRUSTED_PREFIX
from src.solution import handle_request_with_trace
from test_failure_lab import proposal

ROUTES = ["no evidence pack yet", "verify required evidence ran", "authoritative rules not computed",
          "evidence and rules ready for independent review", "all artifacts present"]


def evidence_turn(rid: str, vendor: str) -> dict:
    return tools_turn(call("get_request_details", request_id=rid), call("check_budget", request_id=rid),
                      call("search_software_catalog", request_id=rid), call("get_vendor_status", vendor_name=vendor))


def pack(**over) -> dict:
    base = {
        "need_summary": "Marketing wants a campaign-template tool.",
        "data_classes_implied": [],
        "overlap_assessment": [],
        "vendor_observations": ["Registry and vendor-risk service both show an incomplete assessment."],
        "uncertainties": [],
        "injection_observed": False,
        "injection_excerpt": None,
        "evidence": [],
        "gaps": [],
        "unsupported_or_unverified": [],
    }
    base.update(over)
    return base


def review(rid: str, audit: dict | None = None, **over) -> dict:
    return {**proposal(rid, **over),
            "analyst_audit": audit or {"issues_found": [], "rejected_claims": [], "agrees_with_overlap_assessment": True}}


def run(rid: str, script: list):
    llm = ScriptedLLM(script)
    with in_process_vendor_api():
        decision, trace = handle_request_with_trace(rid, "staged", llm=llm)
    return decision, trace, llm


class StagedTests(unittest.TestCase):
    def routes(self, trace):
        return [s["route_reason"] for s in trace["steps"] if s["actor"] == "code:supervisor"]

    def test_route_reasons_in_order(self):
        rid = "REQ-1002"
        decision, trace, llm = run(rid, [
            evidence_turn(rid, "BrandBoard"),
            tools_turn(call("submit_evidence_pack", **pack())),
            {"structured": review(rid)},
        ])
        self.assertEqual(self.routes(trace), ROUTES)
        self.assertEqual((trace["stop_reason"], trace["final_mode"]), ("completed", "structured"))
        self.assertEqual(decision.telemetry.llm_calls, 3)
        self.assertEqual(decision.required_approvals, ["Department Head", "Finance", "Procurement", "Security", "Legal"])
        self.assertNotIn("llm_unavailable", decision.risk_flags)
        policy_runs = [t for t in trace["tool_log"] if t["name"] == "evaluate_policy_rules"]
        self.assertEqual([t["initiator"] for t in policy_runs], ["orchestrator"])

    def test_reviewer_has_no_tools_and_gets_four_sections(self):
        rid = "REQ-1002"
        _, _, llm = run(rid, [evidence_turn(rid, "BrandBoard"), tools_turn(call("submit_evidence_pack", **pack())),
                              {"structured": review(rid)}])
        last = llm.calls[-1]
        self.assertEqual(last["method"], "chat_structured")
        content = last["messages"][1]["content"]
        for header in ["## Evidence pack", "## Raw tool results", "## Policy engine result", "## Policy text"]:
            self.assertIn(header, content)
        self.assertIn("§5. Security review", content)
        self.assertNotIn("§8. AI tools", content)  # only sections the policy engine referenced
        self.assertNotIn("evaluate_policy_rules", llm.calls[0]["tools"])  # analyst scope (D5)

    def test_injected_text_reaches_reviewer_only_inside_untrusted_blocks(self):
        rid = "REQ-1006"
        _, _, llm = run(rid, [evidence_turn(rid, "NeuralDesk"), tools_turn(call("submit_evidence_pack", **pack())),
                              {"structured": review(rid)}])
        content = llm.calls[-1]["messages"][1]["content"]
        system = llm.calls[-1]["messages"][0]["content"]
        self.assertNotIn("CFO-approved", system)
        for section in content.split("## ")[1:]:
            if "CFO-approved" in section:
                self.assertIn(UNTRUSTED_PREFIX.strip(), section, section[:80])

    def test_code_decides_reviewer_cannot_remove_approvals_or_flags(self):
        rid = "REQ-1005"
        decision, trace, _ = run(rid, [evidence_turn(rid, "GrowthForge"), tools_turn(call("submit_evidence_pack", **pack())),
                                       {"structured": review(rid, required_approvals=[], risk_flags=[],
                                                             decision_type="route_for_approval")}])
        self.assertEqual(decision.required_approvals,
                         ["Department Head", "Finance", "Procurement", "Security", "Privacy", "Legal"])
        for flag in ["budget_insufficient", "security_review_required", "privacy_review_required", "legal_review_required"]:
            self.assertIn(flag, decision.risk_flags)
        self.assertEqual(trace["event_counts"]["code_restored_approval"], 6)
        self.assertEqual(trace["event_counts"]["llm_decision_overridden"], 1)
        self.assertTrue(decision.recommendation.startswith("Route for specialist review:"))
        self.assertEqual(sum(1 for st in trace["steps"] if st["actor"] == "code:gate"), 1)  # no duplicate gate step

    def test_reviewer_tool_use_failed_falls_back_with_policy_approvals(self):
        rid = "REQ-1002"
        decision, trace, _ = run(rid, [evidence_turn(rid, "BrandBoard"), tools_turn(call("submit_evidence_pack", **pack())),
                                       ToolUseFailed("provider rejected output")])
        self.assertEqual(trace["stop_reason"], "stage_failed:reviewer tool_use_failed")
        self.assertEqual(decision.required_approvals, ["Department Head", "Finance", "Procurement", "Security", "Legal"])
        self.assertIn("llm_unavailable", decision.risk_flags)

    def test_analyst_cannot_call_policy_engine(self):
        rid = "REQ-1001"
        decision, trace, _ = run(rid, [
            tools_turn(call("evaluate_policy_rules", request_id=rid), call("get_request_details", request_id=rid)),
            tools_turn(call("submit_evidence_pack", **pack())),
            {"structured": review(rid)},
        ])
        self.assertEqual(trace["tool_rejected"], 1)
        self.assertEqual(trace["final_mode"], "structured")

    def test_invalid_pack_falls_back(self):
        rid = "REQ-1002"
        decision, trace, llm = run(rid, [
            evidence_turn(rid, "BrandBoard"),
            tools_turn(call("submit_evidence_pack", need_summary="x")),
            tools_turn(call("submit_evidence_pack", need_summary="x")),
        ])
        self.assertEqual(trace["final_mode"], "fallback")
        self.assertEqual(trace["stop_reason"], "stage_failed:analyst invalid_output")
        self.assertIn("llm_unavailable", decision.risk_flags)
        self.assertFalse(any(c["method"] == "chat_structured" for c in llm.calls))  # reviewer never ran
        self.assertEqual(self.routes(trace)[-1], "stage failed: analyst invalid_output")

    def test_reviewer_failure_keeps_grounded_stage1_evidence(self):
        rid = "REQ-1002"
        grounded = {"source": "check_budget", "finding": "Marketing has $15,000 available against a $12,000 request",
                    "reference": "department_budgets.csv:Marketing"}
        made_up = {"source": "check_budget", "finding": "Marketing has $99,999 left", "reference": "x"}
        decision, trace, _ = run(rid, [
            evidence_turn(rid, "BrandBoard"),
            tools_turn(call("submit_evidence_pack", **pack(evidence=[grounded, made_up]))),
            {"structured": {"bad": 1}},
            {"structured": "still bad"},
        ])
        findings = [e.finding for e in decision.evidence]
        self.assertIn(grounded["finding"], findings)
        self.assertNotIn(made_up["finding"], findings)
        self.assertEqual(trace["stop_reason"], "stage_failed:reviewer invalid_output")
        self.assertEqual(decision.telemetry.llm_calls, 4)

    def test_step_limit_stops(self):
        rid = "REQ-1002"
        with mock.patch.object(staged_agent, "MAX_STAGED_STEPS", 2):
            decision, trace, llm = run(rid, [evidence_turn(rid, "BrandBoard"), tools_turn(call("submit_evidence_pack", **pack()))])
        self.assertEqual(trace["stop_reason"], "step_limit")
        self.assertEqual(self.routes(trace)[-1], "step limit reached")
        self.assertTrue(decision.human_review_required)

    def test_reviewer_audit_recorded(self):
        rid = "REQ-1008"
        audit = {"issues_found": ["Analyst missed that TaskFlow is licensed company-wide."],
                 "rejected_claims": ["TaskFlow lacks campaign boards."], "agrees_with_overlap_assessment": False}
        decision, trace, _ = run(rid, [
            evidence_turn(rid, "TaskFlow"),
            tools_turn(call("submit_evidence_pack", **pack())),
            {"structured": review(rid, audit=audit, decision_type="use_existing_tool", overlap_assessment=[
                {"software_id": "SW003", "relationship": "substitute_could_meet_need", "covers_stated_need": True,
                 "reason": "Company-wide TaskFlow covers campaign task tracking"}])},
        ])
        self.assertEqual(trace["analyst_audit"], audit)
        self.assertEqual(trace["event_counts"]["reviewer_rejection"], 1)
        self.assertTrue(decision.recommendation.startswith("Use existing tool:"))

    def test_llm_unavailable_mid_graph(self):
        rid = "REQ-1002"
        decision, trace, _ = run(rid, [evidence_turn(rid, "BrandBoard"), tools_turn(call("submit_evidence_pack", **pack())),
                                       LLMRateLimited("429 from provider")])
        self.assertEqual(trace["stop_reason"], "llm_unavailable")
        self.assertEqual(trace["llm_error_kind"], "rate_limited")
        self.assertIn("llm_unavailable", decision.risk_flags)
        self.assertEqual(decision.required_approvals, ["Department Head", "Finance", "Procurement", "Security", "Legal"])

    def test_supervisor_is_pure_routing(self):
        s = staged_agent.StagedState("REQ-1", ctx=None)  # type: ignore[arg-type]
        self.assertEqual(staged_agent.supervisor(s), ("analyst", "no evidence pack yet"))
        s.error = "analyst max_turns"
        self.assertEqual(staged_agent.supervisor(s)[0], "fallback")


if __name__ == "__main__":
    unittest.main()
