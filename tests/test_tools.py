from __future__ import annotations

import unittest

from helpers import in_process_vendor_api
from src import tools
from src.tools import ALLOWLISTS, TOOLS, RunContext, execute, run_gate, tool_definitions


class ScopingTests(unittest.TestCase):
    def test_allowlists_match_d5(self):
        self.assertEqual(len(ALLOWLISTS["single"]), 6)
        self.assertEqual(len(ALLOWLISTS["analyst"]), 5)
        self.assertNotIn("evaluate_policy_rules", ALLOWLISTS["analyst"])
        self.assertEqual(ALLOWLISTS["reviewer"], [])

    def test_out_of_scope_call_is_rejected_not_executed(self):
        ctx = RunContext("REQ-1001")
        result = execute("evaluate_policy_rules", {"request_id": "REQ-1001"}, ctx, actor="analyst")
        self.assertEqual(result, {"status": "error", "error": "tool not available to this agent"})
        self.assertEqual(ctx.tool_log, [])
        self.assertEqual(ctx.count("tool_rejected"), 1)

    def test_unknown_or_action_tool_is_rejected(self):
        ctx = RunContext("REQ-1001")
        for name in ["approve_purchase", "send_email", "update_budget", "accept_terms"]:
            self.assertEqual(execute(name, {}, ctx, actor="single")["status"], "error")
        self.assertEqual(ctx.count("tool_rejected"), 4)
        self.assertEqual(ctx.tool_calls, 0)

    def test_no_consequential_action_tools_exist(self):
        for name in TOOLS:
            self.assertFalse(any(w in name for w in ["approve", "purchase", "notify", "email", "budget_update", "accept"]))


class ExecutionTests(unittest.TestCase):
    def test_cache_log_and_corpus(self):
        with in_process_vendor_api():
            ctx = RunContext("REQ-1002")
            first = execute("check_budget", {"request_id": "REQ-1002"}, ctx, actor="single")
            second = execute("check_budget", {"request_id": " REQ-1002 "}, ctx, actor="single")
        self.assertIs(first, second)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(ctx.tool_calls, 1)
        self.assertEqual(ctx.count("repeated_tool_call"), 1)
        self.assertEqual([t["cache_hit"] for t in ctx.tool_log], [False, True])
        self.assertIn("15000", ctx.evidence_corpus)

    def test_other_request_id_is_an_error(self):
        ctx = RunContext("REQ-1002")
        result = execute("get_request_details", {"request_id": "REQ-1001"}, ctx, actor="single")
        self.assertEqual(result["status"], "error")
        self.assertIn("REQ-1002", result["error"])

    def test_errors_never_raise(self):
        ctx = RunContext("REQ-NOPE")
        result = execute("get_request_details", {"request_id": "REQ-NOPE"}, ctx, actor="single")
        self.assertEqual(result["status"], "error")
        self.assertEqual(execute("lookup_policy_section", {"section": 99}, ctx, actor="single")["status"], "error")
        self.assertEqual(execute("get_vendor_status", {}, ctx, actor="single")["status"], "error")

    def test_request_details_shape(self):
        ctx = RunContext("REQ-1006")
        result = execute("get_request_details", {"request_id": "REQ-1006"}, ctx, actor="single")
        self.assertTrue(result["injection_scan"]["detected"])
        self.assertIn("business_justification", result["untrusted_text"])
        self.assertFalse(result["field_completeness"]["complete"])
        self.assertEqual(result["requester"]["department"], "Marketing")

    def test_policy_sections(self):
        sections = tools.policy_sections()
        self.assertEqual(sorted(sections), list(range(1, 12)))
        ctx = RunContext("REQ-1001")
        result = execute("lookup_policy_section", {"section": "5"}, ctx, actor="single")
        self.assertEqual(result["title"], "Security review")
        self.assertIn("365 days", result["text"])

    def test_llm_sees_compact_policy_view(self):
        with in_process_vendor_api():
            ctx = RunContext("REQ-1007")
            result = execute("evaluate_policy_rules", {"request_id": "REQ-1007"}, ctx, actor="single")
        self.assertIn("required_approvals", result)
        self.assertNotIn("catalog_candidates", result)
        self.assertLess(len(tools.tool_message_content(result)), 3000)
        self.assertEqual(ctx.policies["REQ-1007"].required_approvals, [a["role"] for a in result["required_approvals"]])

    def test_message_content_has_untrusted_prefix(self):
        self.assertTrue(tools.tool_message_content({"a": 1}).startswith(tools.UNTRUSTED_PREFIX))


class DefinitionTests(unittest.TestCase):
    def test_static_and_described(self):
        self.assertEqual(tool_definitions("single"), tool_definitions("single"))
        self.assertIs(tool_definitions("single")[0], tool_definitions("single")[0])  # same objects, fixed order (D3)
        for tool in TOOLS.values():
            with self.subTest(tool=tool.name):
                sentences = [s for s in tool.description.split(". ") if s]
                self.assertTrue(1 <= len(sentences) <= 4)
                for param in tool.parameters["properties"].values():
                    self.assertTrue(param.get("description"))


class GateTests(unittest.TestCase):
    def test_gate_fills_skipped_tools(self):
        with in_process_vendor_api():
            ctx = RunContext("REQ-X104")
            execute("get_request_details", {"request_id": "REQ-X104"}, ctx, actor="single")
            execute("get_vendor_status", {"vendor_name": "SignalWatch"}, ctx, actor="single")  # canonical form counts
            filled = run_gate(ctx, tools.GATE_SINGLE)
        self.assertEqual(filled, ["check_budget", "search_software_catalog", "evaluate_policy_rules"])
        self.assertEqual(ctx.count("gate_filled:check_budget"), 1)
        self.assertTrue(all(t["initiator"] == "gate" for t in ctx.tool_log[2:]))
        self.assertIn("REQ-X104", ctx.policies)

    def test_wrong_vendor_does_not_satisfy_gate(self):
        with in_process_vendor_api():
            ctx = RunContext("REQ-1001")
            execute("get_vendor_status", {"vendor_name": "TaskFlow"}, ctx, actor="single")
            filled = run_gate(ctx, ["get_vendor_status"])
        self.assertEqual(filled, ["get_vendor_status"])


if __name__ == "__main__":
    unittest.main()
