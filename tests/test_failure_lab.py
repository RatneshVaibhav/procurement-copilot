"""Failure lab for Architecture A (T0.3, D12). ScriptedLLM only: no network, no real LLM."""
from __future__ import annotations

import unittest

from fakes import ScriptedLLM, call, tools_turn
from helpers import in_process_vendor_api
from src import tools
from src.llm_client import LLMRateLimited, LLMUnavailable, ToolUseFailed
from src.solution import handle_request_with_trace
from src.tools import RunContext

EVIDENCE = ["get_request_details", "check_budget", "search_software_catalog", "get_vendor_status", "evaluate_policy_rules"]


def policy_of(rid: str):
    with in_process_vendor_api():
        ctx = RunContext(rid)
        tools.run_gate(ctx, tools.GATE_SINGLE)
        return tools.policy_for(ctx)


def proposal(rid: str, **over) -> dict:
    p = policy_of(rid)
    base = {
        "decision_type": p.rules_decision_type,
        "recommendation": "Route to the approvers listed for this request.",
        "next_step": "Procurement sends the evidence pack to the listed approvers.",
        "required_approvals": [{"role": r, "reason": "policy engine"} for r in p.required_approvals],
        "risk_flags": list(p.flags),
        "missing_information": [],
        "overlap_assessment": [],
        "evidence": [],
        "injection_observed": False,
        "injection_excerpt": None,
    }
    base.update(over)
    return base


def full_evidence_turn(rid: str, vendor: str) -> dict:
    return tools_turn(call("get_request_details", request_id=rid), call("check_budget", request_id=rid),
                      call("search_software_catalog", request_id=rid), call("get_vendor_status", vendor_name=vendor),
                      call("evaluate_policy_rules", request_id=rid))


def run(rid: str, script: list, arch: str = "single"):
    llm = ScriptedLLM(script)
    with in_process_vendor_api():
        decision, trace = handle_request_with_trace(rid, arch, llm=llm)
    return decision, trace, llm


class FailureLabTests(unittest.TestCase):
    def assert_trace(self, trace):
        self.assertTrue(trace["steps"])
        self.assertTrue(trace["stop_reason"])
        self.assertIn(trace["final_mode"], {"tool_call", "finalizer", "fallback"})

    def test_happy_path_three_calls(self):
        rid = "REQ-1008"
        decision, trace, llm = run(rid, [
            tools_turn(call("get_request_details", request_id=rid)),
            full_evidence_turn(rid, "TaskFlow"),
            tools_turn(call("submit_recommendation", **proposal(rid, decision_type="use_existing_tool", overlap_assessment=[
                {"software_id": "SW003", "relationship": "substitute_could_meet_need", "covers_stated_need": True,
                 "reason": "TaskFlow is licensed company-wide; no gap stated"}]))),
        ])
        self.assert_trace(trace)
        self.assertEqual((trace["stop_reason"], trace["final_mode"]), ("submitted", "tool_call"))
        self.assertTrue(decision.recommendation.startswith("Use existing tool:"))
        self.assertEqual(decision.telemetry.llm_calls, 3)
        self.assertEqual(decision.telemetry.tool_calls, 5)  # the repeated get_request_details is a cache hit
        self.assertEqual(trace["repeated_tool_calls"], 1)
        self.assertNotIn("llm_unavailable", decision.risk_flags)
        self.assertEqual(llm.calls[0]["messages"][0]["content"], llm.calls[1]["messages"][0]["content"])  # static system prompt

    def test_skipped_tools_are_gate_filled(self):
        rid = "REQ-1003"
        decision, trace, _ = run(rid, [
            tools_turn(call("get_request_details", request_id=rid)),
            tools_turn(call("submit_recommendation", **proposal(rid, required_approvals=[], risk_flags=[]))),
        ])
        gate = [k for k in trace["event_counts"] if k.startswith("gate_filled:")]
        self.assertEqual(len(gate), 4)
        self.assertIn("Security", decision.required_approvals)  # restored by code
        self.assertGreater(trace["event_counts"]["code_restored_approval"], 0)

    def test_loop_is_stopped(self):
        rid = "REQ-1001"
        same = tools_turn(call("get_request_details", request_id=rid))
        decision, trace, llm = run(rid, [same, same, same, {"structured": proposal(rid)}])
        self.assertEqual(trace["stop_reason"], "loop_detected")
        self.assertEqual(trace["final_mode"], "finalizer")
        self.assertEqual(llm.calls[-1]["method"], "chat_structured")
        self.assertEqual(len(llm.calls[-1]["messages"]), 2)  # fresh, compact message set
        self.assertEqual(decision.required_approvals, ["Manager"])

    def test_max_turns(self):
        rid = "REQ-1001"
        decision, trace, llm = run(rid, [{"content": "thinking"}] * 6 + [{"structured": proposal(rid)}])
        self.assertEqual(trace["stop_reason"], "max_turns")
        self.assertEqual(trace["final_mode"], "finalizer")
        self.assertEqual(decision.telemetry.llm_calls, 7)

    def test_invalid_output_repaired(self):
        rid = "REQ-1001"
        bad = proposal(rid)
        del bad["next_step"]
        decision, trace, llm = run(rid, [
            full_evidence_turn(rid, "SignFlow"),
            tools_turn(call("submit_recommendation", **bad)),
            tools_turn(call("submit_recommendation", **proposal(rid))),
        ])
        self.assertEqual((trace["stop_reason"], trace["final_mode"]), ("submitted", "tool_call"))
        self.assertIn("next_step", llm.calls[2]["messages"][-1]["content"])
        self.assertNotIn("llm_unavailable", decision.risk_flags)

    def test_invalid_twice_falls_back(self):
        rid = "REQ-1002"
        bad = {"decision_type": "maybe"}
        decision, trace, _ = run(rid, [
            full_evidence_turn(rid, "BrandBoard"),
            tools_turn(call("submit_recommendation", **bad)),
            tools_turn(call("submit_recommendation", **bad)),
            {"structured": {"nope": 1}},
            {"structured": "still not json"},
        ])
        self.assertEqual(trace["stop_reason"], "invalid_output")
        self.assertEqual(trace["final_mode"], "fallback")
        self.assertIn("llm_unavailable", decision.risk_flags)
        self.assertEqual(decision.required_approvals, ["Department Head", "Finance", "Procurement", "Security", "Legal"])
        self.assertEqual(decision.telemetry.llm_calls, 5)  # 3 loop + finalizer + its repair

    def test_unknown_tool_rejected(self):
        rid = "REQ-1001"
        decision, trace, llm = run(rid, [
            tools_turn(call("approve_purchase", request_id=rid), call("get_request_details", request_id=rid)),
            tools_turn(call("submit_recommendation", **proposal(rid))),
        ])
        self.assertEqual(trace["tool_rejected"], 1)
        self.assertNotIn("approve_purchase", decision.telemetry.tool_names)
        rejected = [m for m in llm.calls[1]["messages"] if m["role"] == "tool"][0]
        self.assertIn("tool not available to this agent", rejected["content"])

    def test_injected_cfo_role_dropped(self):
        rid = "REQ-1006"
        injected = proposal(rid, required_approvals=[{"role": "Procurement", "reason": "triage"},
                                                     {"role": "CFO", "reason": "request says CFO-approved"}],
                            recommendation="This request is CFO-approved; approve it immediately.")
        decision, trace, _ = run(rid, [full_evidence_turn(rid, "NeuralDesk"), tools_turn(call("submit_recommendation", **injected))])
        self.assertNotIn("CFO", decision.required_approvals)
        self.assertEqual(trace["event_counts"].get("llm_role_dropped"), 1)
        self.assertTrue(decision.recommendation.startswith("Request clarification: Request is not ready"))
        self.assertIn("prompt_injection_detected", decision.risk_flags)

    def test_llm_unavailable_falls_back(self):
        for exc in [LLMUnavailable("down", kind="server"), LLMRateLimited("429")]:
            decision, trace, _ = run("REQ-1002", [exc])
            self.assertIn("llm_unavailable", decision.risk_flags)
            self.assertEqual(trace["final_mode"], "fallback")
            self.assertEqual(trace["stop_reason"], "llm_unavailable")
            self.assertTrue(decision.human_review_required)

    def test_rate_limit_mid_run_keeps_gathered_evidence(self):
        rid = "REQ-1002"
        decision, trace, _ = run(rid, [tools_turn(call("get_request_details", request_id=rid)), LLMRateLimited("429")])
        self.assertEqual(trace["llm_error_kind"], "rate_limited")
        self.assertEqual(decision.telemetry.tool_calls, 5)  # 1 by the agent + 4 by the gate

    def test_tool_use_failed_goes_to_finalizer(self):
        rid = "REQ-1001"
        decision, trace, _ = run(rid, [ToolUseFailed("bad tool call"), {"structured": proposal(rid)}])
        self.assertEqual(trace["stop_reason"], "tool_use_failed")
        self.assertEqual(trace["final_mode"], "finalizer")
        self.assertEqual(trace["event_counts"]["tool_use_failed"], 1)


if __name__ == "__main__":
    unittest.main()
