"""All 23 golden cases through the deterministic engine (PLAN P1 task 9).

Exact-set semantics for approvals and flags; missing-information groups and max_items.
Skips only each case's requires_ai aspects and the llm_unavailable flag.
"""
from __future__ import annotations

import unittest

from helpers import GOLDEN, in_process_vendor_api
from src import policy_engine as pe
from src.tools import RunContext


def exact_set_ok(final: set, required: set, optional: set) -> bool:
    return required <= final <= required | optional


class GoldenDeterministicTests(unittest.TestCase):
    def test_all_cases(self):
        self.assertEqual(len(GOLDEN), 23)
        for case in GOLDEN:
            skip = set(case.get("requires_ai", []))
            with self.subTest(case=case["case_id"]), in_process_vendor_api(down=case["fault"] == "vendor_api_down"):
                result = pe.evaluate(case["request_id"], RunContext(case["request_id"]))
                roles, flags = set(result.required_approvals), set(result.flags)
                if "approvals" not in skip:
                    self.assertTrue(exact_set_ok(roles, set(case["approvals"]["required"]), set(case["approvals"]["optional"])),
                                    f"approvals {sorted(roles)}")
                if "flags" not in skip:
                    required = set(case["flags"]["required"]) - {"llm_unavailable"}
                    self.assertTrue(exact_set_ok(flags, required, set(case["flags"]["optional"])), f"flags {sorted(flags)}")
                items = [m.casefold() for m in result.missing_information]
                for group in case["missing_information"]["required_any_groups"]:
                    self.assertTrue(any(tok.casefold() in it for it in items for tok in group), f"missing group {group}")
                max_items = case["missing_information"]["max_items"]
                if max_items is not None:
                    self.assertLessEqual(len(items), max_items)
                if "decision" not in skip:
                    self.assertIn(result.rules_decision_type, case["decision_type"]["acceptable"])
                self.assertFalse(set(case["forbidden_approvals"]) & roles)


if __name__ == "__main__":
    unittest.main()
