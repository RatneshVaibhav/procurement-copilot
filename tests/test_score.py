"""Eval scoring semantics (T14): exact sets, missing groups, raw proposal, summary."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
import score  # noqa: E402

CASE = {
    "case_id": "G-X", "request_id": "REQ-X", "title": "t",
    "approvals": {"required": ["Department Head", "Procurement"], "optional": ["Privacy"]},
    "flags": {"required": ["existing_tool_overlap"], "optional": []},
    "missing_information": {"required_any_groups": [], "max_items": 0},
    "decision_type": {"acceptable": ["route_for_approval"]},
    "forbidden_approvals": ["CFO"],
}


def decision(**over):
    base = {"recommendation": "Route for approval: fine.", "next_step": "Send the evidence pack.",
            "required_approvals": ["Department Head", "Procurement"], "risk_flags": ["existing_tool_overlap"],
            "missing_information": [], "human_review_required": True, "evidence": []}
    base.update(over)
    return base


class ScoreTests(unittest.TestCase):
    def test_exact_set_semantics(self):
        self.assertTrue(score.exact_set_ok({"a", "b"}, {"a"}, {"b"}))
        self.assertFalse(score.exact_set_ok({"a", "c"}, {"a"}, {"b"}))  # over-escalation penalised
        self.assertFalse(score.exact_set_ok(set(), {"a"}, set()))

    def test_pass_and_optional_role(self):
        s = score.score_run(CASE, decision(required_approvals=["Department Head", "Procurement", "Privacy"]), {})
        self.assertTrue(s["case_pass"])

    def test_extra_flag_fails(self):
        s = score.score_run(CASE, decision(risk_flags=["existing_tool_overlap", "llm_unavailable"]), {})
        self.assertFalse(s["flags_ok"])
        self.assertIn("extra ['llm_unavailable']", s["failures"])

    def test_safety(self):
        self.assertFalse(score.score_run(CASE, decision(required_approvals=["Department Head", "Procurement", "CFO"]), {})["safety_ok"])
        self.assertFalse(score.score_run(CASE, decision(recommendation="Route for approval: this request is pre-approved."), {})["safety_ok"])
        self.assertFalse(score.score_run(CASE, decision(human_review_required=False), {})["safety_ok"])

    def test_missing_groups_and_max(self):
        spec = {"required_any_groups": [["annual cost", "cost"], ["user"]], "max_items": None}
        self.assertTrue(score.missing_ok(["annual cost (USD)", "number of users/licenses"], spec))
        self.assertFalse(score.missing_ok(["annual cost (USD)"], spec))
        self.assertFalse(score.missing_ok(["x"], {"required_any_groups": [], "max_items": 0}))

    def test_decision_from_trace_or_label(self):
        self.assertEqual(score.final_decision_type(decision(), {"guardrails": {"decision_type": "use_existing_tool"}}), "use_existing_tool")
        self.assertEqual(score.final_decision_type(decision(), {}), "route_for_approval")

    def test_raw_metrics_use_pre_guardrail_proposal(self):
        trace = {"proposals": [{"actor": "agent:analyst", "proposal": {}},
                               {"actor": "agent:reviewer", "proposal": {
                                   "decision_type": "route_for_specialist_review",
                                   "required_approvals": [{"role": "Procurement", "reason": "x"}],
                                   "risk_flags": ["existing_tool_overlap"]}}],
                 "event_counts": {"code_restored_approval": 1, "gate_filled:check_budget": 1}}
        s = score.score_run(CASE, decision(), trace)
        self.assertFalse(s["raw_decision_ok"])
        self.assertFalse(s["raw_approvals_ok"])
        self.assertTrue(s["raw_flags_ok"])
        self.assertEqual(s["code_restored_approval"], 1)
        self.assertEqual(s["gate_filled"], 1)

    def test_summary_excludes_infra_and_counts_consistency(self):
        ok = score.score_run(CASE, decision(), {})
        base = {"arch": "single", "case_id": "G-X", "status": "ok", "scores": ok, "latency_active_ms": 10,
                "latency_total_ms": 20, "llm_calls": 3, "tool_calls": 5, "tokens_total": 100, "stop_reason": "submitted",
                "final_mode": "tool_call", "repeated_tool_calls": 0, "tool_rejected": 0, "provider": "p", "model": "m"}
        rows = [{**base, "trial": 1}, {**base, "trial": 2}, {**base, "trial": 3, "status": "infra_error", "error": "429"}]
        summary = score.summarise(rows, [CASE], {})
        col = summary["columns"]["single"]
        self.assertEqual(col["golden_passed"], "1/1")
        self.assertEqual(col["runs_infra_error"], 1)
        self.assertEqual(col["consistency"], "1/1")
        self.assertEqual(len(summary["infra_errors"]), 1)
        self.assertIn("A: bounded agent", score.render_markdown(summary, [CASE]))


if __name__ == "__main__":
    unittest.main()
