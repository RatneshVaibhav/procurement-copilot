from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from helpers import fixed_vendor_fetch, in_process_vendor_api
from src import data_access as da
from src import policy_engine as pe
from src.normalize import normalize_request
from src.tools import RunContext

REF = date(2026, 9, 30)
VENDOR_FIELDS = ["vendor_id", "vendor_name", "procurement_status", "security_status", "security_review_date",
                 "legal_terms_status", "notes"]


def make_request(**over) -> dict:
    base = {
        "request_id": "REQ-T001",
        "requester_id": "E001",  # Marketing, available $15,000
        "product_name": "Testtool",
        "vendor_name": "Testvendor",
        "category": "Test Category",
        "annual_cost_usd": 5000,
        "user_count": 5,
        "business_justification": "A test need.",
        "data_access_level": "internal",
        "requested_integrations": [],
        "urgency": "normal",
    }
    base.update(over)
    return base


def make_vendor(**over) -> dict:
    base = {"vendor_id": "V-T1", "vendor_name": "Testvendor", "procurement_status": "Approved",
            "security_status": "Approved", "security_review_date": "2026-06-01", "legal_terms_status": "Approved",
            "notes": "Standard vendor"}
    base.update(over)
    return base


API_OK = {"risk_level": "low", "security_review_status": "approved", "last_review_date": "2026-06-01",
          "processes_personal_data": False, "stores_data_outside_region": False, "notes": "Current assessment."}


def evaluate_synthetic(request: dict, vendor: dict | None = None, api_outcome: str = "ok", api_record: dict | None = None):
    """Run the full engine on a synthetic request via a temporary EXTRA_DATA_DIR."""
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "requests.json").write_text(json.dumps([request]), encoding="utf-8")
        if vendor is not None:
            with Path(tmp, "vendors.csv").open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=VENDOR_FIELDS)
                writer.writeheader()
                writer.writerow(vendor)
        record = API_OK if api_record is None and api_outcome == "ok" else api_record
        with mock.patch.dict(os.environ, {"EXTRA_DATA_DIR": tmp}):
            ctx = RunContext(request["request_id"], vendor_fetch=fixed_vendor_fetch(api_outcome, record))
            return pe.evaluate(request["request_id"], ctx)


class TierTests(unittest.TestCase):
    def test_boundaries(self):
        cases = [
            (1000, ["Manager"]),
            (1000.01, ["Department Head", "Procurement"]),
            (10000, ["Department Head", "Procurement"]),
            (10000.01, ["Department Head", "Finance", "Procurement"]),
            (25000, ["Department Head", "Finance", "Procurement"]),
            (25000.01, ["Department Head", "Finance", "CFO", "Procurement"]),
            (None, ["Procurement"]),
        ]
        for cost, roles in cases:
            with self.subTest(cost=cost):
                self.assertEqual(pe.tier(cost)[1], roles)


class BudgetTests(unittest.TestCase):
    def test_equal_is_within_budget(self):
        result = pe.budget_check("Marketing", 15000)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["within_budget"])
        self.assertEqual(result["remaining_after_usd"], 0)

    def test_over_budget(self):
        result = pe.budget_check("Marketing", 15000.01)
        self.assertEqual(result["status"], "insufficient")
        self.assertFalse(result["within_budget"])

    def test_no_budget_row(self):
        result = pe.budget_check("Go To Market", 500)
        self.assertEqual(result["status"], "unverified")

    def test_not_checked_without_cost(self):
        self.assertEqual(pe.budget_check("Marketing", None)["status"], "not_checked")

    def test_engine_budget_flags(self):
        over = evaluate_synthetic(make_request(annual_cost_usd=15000.01), make_vendor())
        self.assertIn("budget_insufficient", over.flags)
        self.assertIn("Finance", over.required_approvals)
        no_row = evaluate_synthetic(make_request(requester_id="E007", annual_cost_usd=500), make_vendor())
        self.assertIn("budget_unverified", no_row.flags)
        self.assertIn("Finance", no_row.required_approvals)
        self.assertIn(pe.GAP_NO_BUDGET, no_row.missing_information)
        self.assertNotIn("missing_information", no_row.flags)


class ReviewAgeTests(unittest.TestCase):
    def _registry(self, days_old: int) -> dict:
        return make_vendor(security_review_date=(REF - timedelta(days=days_old)).isoformat())

    def _api(self, days_old: int) -> dict:
        return {"outcome": "ok", "record": {**API_OK, "last_review_date": (REF - timedelta(days=days_old)).isoformat()}}

    def test_365_is_current(self):
        d = pe.derive_vendor(self._registry(365), self._api(365), REF)
        self.assertTrue(d.registry_current)
        self.assertFalse(d.expired)
        self.assertTrue(d.cleared)

    def test_366_is_expired(self):
        d = pe.derive_vendor(self._registry(366), self._api(366), REF)
        self.assertFalse(d.registry_current)
        self.assertTrue(d.expired)
        self.assertFalse(d.cleared)
        self.assertEqual(d.expired_on, (REF - timedelta(days=1)).isoformat())

    def test_blank_or_future_registry_date_not_current_not_expired(self):  # D-07.4
        for review_date in ["", (REF + timedelta(days=3)).isoformat()]:
            with self.subTest(review_date=review_date):
                d = pe.derive_vendor(make_vendor(security_review_date=review_date), {"outcome": "unavailable"}, REF)
                self.assertFalse(d.registry_current)
                self.assertFalse(d.expired)
                self.assertFalse(d.cleared)
        result = evaluate_synthetic(make_request(), make_vendor(security_review_date=""), api_outcome="unavailable")
        self.assertIn("Security", result.required_approvals)
        self.assertNotIn("vendor_review_expired", result.flags)


class ConflictMatrixTests(unittest.TestCase):
    REGISTRY = {"approved": "Approved", "pending": "Pending", "expired": "Expired", "unknown": "Unknown"}
    API = {"approved": "approved", "expired": "expired", "pending": "not_completed", "unknown": "weird"}

    def test_all_cells(self):
        for r_cls, r_raw in self.REGISTRY.items():
            for a_cls, a_raw in self.API.items():
                with self.subTest(registry=r_cls, api=a_cls):
                    d = pe.derive_vendor(
                        make_vendor(security_status=r_raw),
                        {"outcome": "ok", "record": {**API_OK, "security_review_status": a_raw}},
                        REF,
                    )
                    self.assertEqual(d.registry_class, r_cls)
                    self.assertEqual(d.api_class, a_cls)
                    expected = (r_cls == "approved") != (a_cls == "approved")
                    self.assertEqual(d.conflict, expected)

    def test_both_approved_dates_differ(self):
        d = pe.derive_vendor(make_vendor(), {"outcome": "ok", "record": {**API_OK, "last_review_date": "2026-05-01"}}, REF)
        self.assertTrue(d.conflict)
        same = pe.derive_vendor(make_vendor(), {"outcome": "ok", "record": API_OK}, REF)
        self.assertFalse(same.conflict)

    def test_no_conflict_without_api_record_or_registry(self):
        for outcome in ["not_found", "unavailable"]:
            self.assertFalse(pe.derive_vendor(make_vendor(), {"outcome": outcome}, REF).conflict)
        self.assertFalse(pe.derive_vendor(None, {"outcome": "ok", "record": API_OK}, REF).conflict)

    def test_conflict_routes_to_security_and_shows_both_values(self):
        result = evaluate_synthetic(make_request(), make_vendor(),
                                    api_record={**API_OK, "security_review_status": "expired"})
        self.assertIn("conflicting_vendor_evidence", result.flags)
        self.assertIn("Security", result.required_approvals)
        conflict = [e.finding for e in result.evidence if "Conflicting" in e.finding][0]
        self.assertIn("Approved", conflict)
        self.assertIn("expired", conflict)


class VendorOutcomeTests(unittest.TestCase):
    def test_registered_vendor_404_adds_security_and_gap(self):  # D-01
        result = evaluate_synthetic(make_request(), make_vendor(), api_outcome="not_found")
        self.assertIn("Security", result.required_approvals)
        self.assertIn(pe.GAP_NOT_FOUND, result.missing_information)
        self.assertNotIn("conflicting_vendor_evidence", result.flags)
        self.assertNotIn("vendor_risk_unavailable", result.flags)
        self.assertTrue(any("no record for a registered vendor" in r.detail for r in result.role_reasons("Security")))

    def test_unavailable_registry_current_not_sensitive(self):  # Assumption 13
        result = evaluate_synthetic(make_request(), make_vendor(), api_outcome="unavailable")
        self.assertIn("vendor_risk_unavailable", result.flags)
        self.assertNotIn("Security", result.required_approvals)
        self.assertIn(pe.GAP_UNAVAILABLE, result.missing_information)
        self.assertIn(pe.GAP_RESIDENCY, result.missing_information)

    def test_unregistered_vendor(self):
        result = evaluate_synthetic(make_request(), None, api_outcome="not_found")
        self.assertIn("vendor_not_registered", result.flags)
        self.assertIn("Security", result.required_approvals)
        self.assertIn("Legal", result.required_approvals)
        self.assertNotIn("vendor_risk_unavailable", result.flags)


class LegalTests(unittest.TestCase):
    def test_new_vendor_boundary(self):
        new = make_vendor(procurement_status="New")
        below = evaluate_synthetic(make_request(annual_cost_usd=9999.99), new)
        at = evaluate_synthetic(make_request(annual_cost_usd=10000), new)
        self.assertNotIn("Legal", below.required_approvals)
        self.assertIn("Legal", at.required_approvals)
        self.assertIn("legal_review_required", at.flags)

    def test_unapproved_terms(self):
        result = evaluate_synthetic(make_request(), make_vendor(legal_terms_status="Draft"))
        self.assertIn("Legal", result.required_approvals)


class CrossRegionTests(unittest.TestCase):
    OUTSIDE = {**API_OK, "stores_data_outside_region": True}

    def test_pii_outside_region_adds_privacy_and_legal(self):
        result = evaluate_synthetic(make_request(data_access_level="customer_pii"), make_vendor(), api_record=self.OUTSIDE)
        for role in ["Security", "Privacy", "Legal"]:
            self.assertIn(role, result.required_approvals)

    def test_not_sensitive_outside_region_no_review(self):
        result = evaluate_synthetic(make_request(), make_vendor(), api_record=self.OUTSIDE)
        for role in ["Security", "Privacy", "Legal"]:
            self.assertNotIn(role, result.required_approvals)

    def test_unavailable_with_confidential_documents_adds_privacy_only(self):
        result = evaluate_synthetic(make_request(data_access_level="confidential_documents"), make_vendor(),
                                    api_outcome="unavailable")
        self.assertIn("Privacy", result.required_approvals)
        self.assertNotIn("Legal", result.required_approvals)

    def test_residency_missing_in_api_record_adds_privacy(self):  # D-14 (proposed)
        record = {k: v for k, v in API_OK.items() if k != "stores_data_outside_region"}
        result = evaluate_synthetic(make_request(data_access_level="confidential_documents"), make_vendor(), api_record=record)
        self.assertIn("Privacy", result.required_approvals)
        self.assertNotIn("Legal", result.required_approvals)

    def test_not_found_with_confidential_documents_adds_privacy(self):  # D-14 (proposed)
        result = evaluate_synthetic(make_request(data_access_level="confidential_documents"), make_vendor(),
                                    api_outcome="not_found")
        self.assertIn("Privacy", result.required_approvals)


class DataClassTests(unittest.TestCase):
    def test_level_table(self):
        table = {
            "none": [], "internal": [], "internal_documents": [], "internal_marketing": [], "public": [],
            "source_code": ["source_code"], "customer_pii": ["customer_pii"], "employee_pii": ["employee_pii"],
            "confidential_documents": ["confidential_documents"], "production_telemetry": ["production_access"],
            "production_data": ["production_access"], "production_access": ["production_access"],
            "credentials": ["credentials"], "secrets": ["credentials"],
        }
        for level, classes in table.items():
            with self.subTest(level=level):
                self.assertEqual(pe.level_classes(level), (classes, False))

    def test_keyword_fallback(self):
        self.assertEqual(pe.level_classes("personal_data")[0], ["customer_pii"])
        self.assertEqual(pe.level_classes("employee_personal_records")[0], ["employee_pii"])
        self.assertEqual(pe.level_classes("hr_pii")[0], ["employee_pii"])
        self.assertEqual(pe.level_classes("code_snippets")[0], ["source_code"])
        self.assertEqual(pe.level_classes("confidential")[0], ["confidential_documents"])
        self.assertEqual(pe.level_classes("cloud_admin")[0], ["production_access"])
        self.assertEqual(pe.level_classes("password_vault")[0], ["credentials"])

    def test_fallback_matches_whole_tokens_only(self):
        for level in ["product_usage", "productivity", "reporting", "financial_reports", "personalization_settings"]:
            with self.subTest(level=level):
                self.assertEqual(pe.level_classes(level), ([], True))

    def test_unrecognized_level_adds_security(self):
        self.assertEqual(pe.level_classes("blue"), ([], True))
        result = evaluate_synthetic(make_request(data_access_level="blue"), make_vendor())
        self.assertIn("unrecognized_data_access_level", result.flags)
        self.assertIn("Security", result.required_approvals)

    def test_integration_keywords(self):
        cases = {
            "Document repository": "confidential_documents",
            "Google Drive": "confidential_documents",
            "Git repositories": "source_code",
            "GitHub": "source_code",
            "Production cloud account": "production_access",
            "AWS": "production_access",
            "Product analytics": None,
            "HRIS (Workday)": "employee_pii",
            "Payroll": "employee_pii",
            "CRM": "customer_pii",
            "Help Desk": "customer_pii",
            "HelpDeskly": "customer_pii",
            "Zendesk": "customer_pii",
            "Support tickets": "customer_pii",
            "Vault": "credentials",
            "SSO": None,
            "Slack": None,
        }
        for integration, cls in cases.items():
            with self.subTest(integration=integration):
                self.assertEqual(pe.integration_class(integration), cls)

    def test_pii_integration_adds_privacy(self):
        result = evaluate_synthetic(make_request(requested_integrations=["HRIS (Workday)"]), make_vendor())
        self.assertIn("Security", result.required_approvals)
        self.assertIn("Privacy", result.required_approvals)


class RequiredFieldTests(unittest.TestCase):
    def test_empty_list_vs_none(self):
        self.assertEqual(normalize_request(make_request(requested_integrations=[])).requested_integrations, [])
        self.assertIsNone(normalize_request(make_request(requested_integrations=None)).requested_integrations)
        raw = make_request()
        del raw["requested_integrations"]
        self.assertIsNone(normalize_request(raw).requested_integrations)
        clean = evaluate_synthetic(make_request(requested_integrations=[]), make_vendor())
        self.assertNotIn(pe.LABEL_INTEGRATIONS, clean.missing_information)
        missing = evaluate_synthetic(make_request(requested_integrations=None), make_vendor())
        self.assertIn(pe.LABEL_INTEGRATIONS, missing.missing_information)
        self.assertEqual(missing.rules_decision_type, "request_clarification")

    def test_label_order(self):
        raw = make_request(requester_id="E999", product_name=None, annual_cost_usd=None, user_count=None,
                           business_justification="  ", data_access_level="unknown", requested_integrations=None)
        result = evaluate_synthetic(raw, make_vendor())
        self.assertEqual(result.missing_information[:8], [
            pe.LABEL_REQUESTER, pe.LABEL_DEPARTMENT, pe.LABEL_PRODUCT, pe.LABEL_COST,
            pe.LABEL_USERS, pe.LABEL_PURPOSE, pe.LABEL_DATA, pe.LABEL_INTEGRATIONS,
        ])
        self.assertIn("missing_information", result.flags)

    def test_invalid_cost(self):
        req = normalize_request(make_request(annual_cost_usd=-5))
        self.assertIsNone(req.annual_cost_usd)
        self.assertIn("annual cost (invalid value)", req.notes)
        self.assertIsNone(normalize_request(make_request(annual_cost_usd="lots")).annual_cost_usd)

    def test_user_count(self):
        self.assertEqual(normalize_request(make_request(user_count=3)).user_count, 3)
        self.assertIsNone(normalize_request(make_request(user_count=0)).user_count)

    def test_urgency_never_changes_rules(self):
        normal = evaluate_synthetic(make_request(urgency="normal"), make_vendor())
        urgent = evaluate_synthetic(make_request(urgency="URGENT!!"), make_vendor())
        self.assertEqual(normal.required_approvals, urgent.required_approvals)
        self.assertEqual(normal.flags, urgent.flags)


class NameNormalisationTests(unittest.TestCase):
    def test_norm_key(self):
        self.assertEqual(da.norm_key("  Signal   Watch "), "signal watch")
        self.assertEqual(da.find_vendor(" signalwatch ")["vendor_name"], "SignalWatch")
        self.assertIsNone(da.find_vendor("Nobody Inc"))
        self.assertEqual(da.find_employee(" e001 ")["name"], "Sarah Lee")

    def test_department_head_hint_walks_up(self):
        self.assertEqual(pe.requester_info("E003")["department_head_hint"], "Robert King")  # Sales has no Director
        self.assertEqual(pe.requester_info("E001")["department_head_hint"], "David Chen")


class OfficialTableTests(unittest.TestCase):
    """The T5 expected-output table for all 10 official requests."""
    DH, FIN, PROC, SEC, PRIV, LEG = "Department Head", "Finance", "Procurement", "Security", "Privacy", "Legal"
    O, S, P, L = "existing_tool_overlap", "security_review_required", "privacy_review_required", "legal_review_required"
    TABLE = {
        "REQ-1001": (["Manager"], [O]),
        "REQ-1002": ([DH, FIN, PROC, SEC, LEG], [O, S, L]),
        "REQ-1003": ([DH, FIN, PROC, SEC], [O, S]),
        "REQ-1004": ([DH, PROC, SEC, PRIV, LEG], [O, S, P, L]),
        "REQ-1005": ([DH, FIN, PROC, SEC, PRIV, LEG], ["budget_insufficient", S, P, L]),
        "REQ-1006": ([PROC], ["missing_information", "prompt_injection_detected", O]),
        "REQ-1007": ([DH, FIN, PROC, SEC], [O, S, "vendor_review_expired", "conflicting_vendor_evidence"]),
        "REQ-1008": ([DH, PROC], [O]),
        "REQ-1009": ([DH, FIN, PROC, SEC, PRIV, LEG], [S, P, L, "vendor_risk_unavailable"]),
        "REQ-1010": (["Manager"], []),
    }

    def test_table(self):
        for rid, (roles, flags) in self.TABLE.items():
            with self.subTest(request=rid), in_process_vendor_api(extra_data_dir=None):
                result = pe.evaluate(rid, RunContext(rid))
                self.assertEqual(result.required_approvals, roles)
                self.assertEqual(sorted(result.flags), sorted(flags))
                self.assertTrue(result.evidence)


if __name__ == "__main__":
    unittest.main()
