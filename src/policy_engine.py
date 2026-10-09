"""Deterministic policy engine: rules R0–R12 (T5) with DECISIONS.md D-01, D-02, D-07.4,
D-07.5 and D-14 (proposed).

Code decides: approval thresholds, budget, review currency, registry/API conflicts,
Security/Privacy/Legal triggers, required fields and the injection scan. Nothing here
depends on request IDs, vendor names or product names.

`ctx` is duck-typed: it needs `.vendor_api(name) -> classified dict` (cached per run,
see src/tools.py RunContext) and `.reference_date`.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from src import data_access as da
from src import injection
from src.config import get_policy_version
from src.contracts import EvidenceItem
from src.normalize import NormalizedRequest, normalize_request
from src.schemas import (
    FLAG_ORDER,
    ROLE_FLAGS,
    ROLE_ORDER,
    PolicyResult,
    Reason,
    RoleApproval,
    VendorDerived,
    VendorStatus,
)

REVIEW_VALID_DAYS = 365
NEW_VENDOR_LEGAL_THRESHOLD = 10000.0

# R1 exact labels, in order
LABEL_REQUESTER = "requester (unknown employee ID)"
LABEL_DEPARTMENT = "department"
LABEL_PRODUCT = "product or vendor name"
LABEL_COST = "annual cost (USD)"
LABEL_USERS = "number of users/licenses"
LABEL_PURPOSE = "business purpose"
LABEL_DATA = "data access level"
LABEL_INTEGRATIONS = "required integrations"
GAP_UNAVAILABLE = "vendor security assessment (vendor-risk service unavailable)"
GAP_RESIDENCY = "vendor data-residency status (unverified)"
GAP_NOT_FOUND = "vendor-risk record (not found)"
GAP_NO_BUDGET = "department software budget (no budget record)"

# R7 data_access_level mapping (casefolded)
LEVEL_MAP: dict[str, list[str]] = {
    "none": [],
    "internal": [],
    "internal_documents": [],
    "internal_marketing": [],
    "public": [],
    "source_code": ["source_code"],
    "customer_pii": ["customer_pii"],
    "employee_pii": ["employee_pii"],
    "confidential_documents": ["confidential_documents"],
    "production_telemetry": ["production_access"],
    "production_data": ["production_access"],
    "production_access": ["production_access"],
    "credentials": ["credentials"],
    "secrets": ["credentials"],
}

# R7 integration keywords, checked in this order; first match wins per integration.
# Rule 5 uses the generic stem help\s?desk\w* (D-02), never a product name.
INTEGRATION_RULES: list[tuple[re.Pattern, str | None]] = [
    (re.compile(r"\b(document|drive|sharepoint|dropbox)\b"), "confidential_documents"),
    (re.compile(r"\b(git|github|gitlab|bitbucket|repo|repository|repositories|source code)\b"), "source_code"),
    (re.compile(r"\b(production|prod|cloud|aws|gcp|azure|kubernetes|k8s|database)\b"), "production_access"),
    (re.compile(r"\b(hris|workday|payroll|hr system|bamboohr|employee directory)\b"), "employee_pii"),
    (re.compile(r"\b(crm|salesforce|hubspot|help\s?desk\w*|zendesk|support tickets?)\b"), "customer_pii"),
    (re.compile(r"\b(vault|secrets?|credentials?|passwords?)\b"), "credentials"),
    (re.compile(r"\b(sso|okta|saml|slack|email)\b"), None),
]

PII_CLASSES = {"employee_pii", "customer_pii"}


# ---------------------------------------------------------------- formatting helpers
def usd(amount: float | None) -> str:
    if amount is None:
        return "missing"
    if float(amount).is_integer():
        return f"${int(amount):,}"
    return f"${amount:,.2f}"


def _num(value: object) -> float | None:
    try:
        text = str(value).strip()
        return float(text) if text else None
    except ValueError:
        return None


def _int_or_none(value: object) -> int | None:
    number = _num(value)
    return int(number) if number is not None and number.is_integer() else None


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


def review_age(value: object, reference: date) -> int | None:
    parsed = _parse_date(value)
    return None if parsed is None else (reference - parsed).days


def is_current(age: int | None) -> bool:
    return age is not None and 0 <= age <= REVIEW_VALID_DAYS


# ---------------------------------------------------------------- R2 requester
def requester_info(employee_id: str | None) -> dict:
    employee = da.find_employee(employee_id)
    if employee is None:
        return {"id": employee_id, "known": False, "name": None, "department": None, "level": None,
                "manager_hint": None, "department_head_hint": None}
    employees = da.records(da.load_employees())
    by_id = {da.norm_key(e["employee_id"]): e for e in employees}
    manager = by_id.get(da.norm_key(employee["manager_id"])) if employee["manager_id"] else None
    department = employee["department"].strip() or None
    head = None
    if department:
        head = next(
            (e for e in employees if da.norm_key(e["department"]) == da.norm_key(department) and e["level"] == "Director"),
            None,
        )
    if head is None:  # walk up the reporting line to the nearest Director/VP
        seen, current = set(), manager
        while current is not None and current["employee_id"] not in seen:
            seen.add(current["employee_id"])
            if current["level"] in {"Director", "VP"}:
                head = current
                break
            current = by_id.get(da.norm_key(current["manager_id"])) if current["manager_id"] else None
    return {
        "id": employee["employee_id"],
        "known": True,
        "name": employee["name"],
        "department": department,
        "level": employee["level"],
        "manager_hint": manager["name"] if manager else None,
        "department_head_hint": head["name"] if head else None,
    }


# ---------------------------------------------------------------- R1 required fields
def missing_request_fields(req: NormalizedRequest, requester: dict) -> list[str]:
    missing = []
    if not requester["known"]:
        missing.append(LABEL_REQUESTER)
    if not requester["department"]:
        missing.append(LABEL_DEPARTMENT)
    if req.product_name is None or req.vendor_name is None:
        missing.append(LABEL_PRODUCT)
    if req.annual_cost_usd is None:
        missing.append(LABEL_COST)
    if req.user_count is None:
        missing.append(LABEL_USERS)
    if req.business_justification is None:
        missing.append(LABEL_PURPOSE)
    if req.data_access_level is None:
        missing.append(LABEL_DATA)
    if req.requested_integrations is None:
        missing.append(LABEL_INTEGRATIONS)
    return missing


def request_facts(raw: dict) -> dict:
    """Facts for get_request_details: normalized values, requester, completeness, injection scan."""
    req = normalize_request(raw)
    requester = requester_info(req.requester_id)
    missing = missing_request_fields(req, requester)
    hits = injection.scan(raw, "request")
    return {
        "request_id": req.request_id,
        "facts": {
            "requester_id": req.requester_id,
            "annual_cost_usd": req.annual_cost_usd,
            "user_count": req.user_count,
            "data_access_level": req.data_access_level,
            "requested_integrations": req.requested_integrations,
            "urgency": req.urgency,
            "notes": req.notes,
        },
        "untrusted_text": {
            "product_name": req.product_name,
            "vendor_name": req.vendor_name,
            "category": req.category,
            "business_justification": req.business_justification,
        },
        "requester": requester,
        "field_completeness": {"complete": not missing, "missing": missing},
        "injection_scan": {"detected": bool(hits), "hits": hits},
    }


# ---------------------------------------------------------------- R3 budget
def budget_check(department: str | None, cost: float | None) -> dict:
    result = {
        "department": department,
        "annual_cost": cost,
        "available_usd": None,
        "committed_usd": None,
        "annual_budget_usd": None,
        "within_budget": None,
        "remaining_after_usd": None,
        "status": "not_checked",
        "reference": "department_budgets.csv",
    }
    if not department or cost is None:
        result["reason"] = "department unknown" if not department else "annual cost missing"
        return result
    row = da.find_budget(department)
    if row is None:
        result["status"] = "unverified"
        result["reason"] = "no budget record for this department"
        return result
    available = _num(row["available_usd"])
    result.update(
        available_usd=available,
        committed_usd=_num(row["committed_usd"]),
        annual_budget_usd=_num(row["annual_software_budget_usd"]),
        reference=f"department_budgets.csv:{row['department']}",
    )
    if available is None:
        result["status"] = "unverified"
        result["reason"] = "budget record has no available amount"
        return result
    result["within_budget"] = cost <= available  # equal counts as within budget
    result["remaining_after_usd"] = available - cost
    result["status"] = "ok" if result["within_budget"] else "insufficient"
    return result


# ---------------------------------------------------------------- R4 tier
def tier(cost: float | None) -> tuple[str, list[str]]:
    if cost is None:
        return "undetermined (annual cost missing)", ["Procurement"]
    if cost <= 1000:
        return "up to $1,000", ["Manager"]
    if cost <= 10000:
        return "$1,000.01 to $10,000", ["Department Head", "Procurement"]
    if cost <= 25000:
        return "$10,000.01 to $25,000", ["Department Head", "Finance", "Procurement"]
    return "above $25,000", ["Department Head", "Finance", "CFO", "Procurement"]


# ---------------------------------------------------------------- R5 catalog
def catalog_search(req: NormalizedRequest, keywords: list[str] | None = None) -> dict:
    keywords = [k.strip() for k in (keywords or []) if isinstance(k, str) and len(k.strip()) >= 3][:5]
    history = da.records(da.load_purchase_history())
    candidates, flag_ids = [], []
    for row in da.records(da.load_software_catalog()):
        match = []
        if req.category and da.norm_key(row["category"]) == da.norm_key(req.category):
            match.append("same_category")
        if req.vendor_name and da.norm_key(row["vendor_name"]) == da.norm_key(req.vendor_name):
            match.append("same_vendor")
        if req.product_name and da.norm_key(row["product_name"]) == da.norm_key(req.product_name):
            match.append("identical_product")
        haystack = " ".join([row["product_name"], row["notes"], row["category"]]).casefold()
        match += [f"keyword:{k}" for k in keywords if k.casefold() in haystack]
        if not match:
            continue
        flagged = "same_category" in match or "identical_product" in match
        if flagged:
            flag_ids.append(row["software_id"])
        purchases = [
            {
                "purchase_id": p["purchase_id"],
                "purchase_date": p["purchase_date"],
                "department": p["department"],
                "annual_amount_usd": _num(p["annual_amount_usd"]),
                "status": p["status"],
                "untrusted_text": {"notes": p["notes"]},
            }
            for p in history
            if da.norm_key(p["product_name"]) == da.norm_key(row["product_name"])
        ]
        candidates.append(
            {
                "software_id": row["software_id"],
                "product_name": row["product_name"],
                "category": row["category"],
                "vendor_name": row["vendor_name"],
                "status": row["status"],
                "annual_cost_usd": _num(row["annual_cost_usd"]),
                "licensed_seats": _int_or_none(row["licensed_seats"]),
                "scope": row["scope"],
                "match": match,
                "overlap_flag": flagged,
                "purchase_history": purchases,
                "untrusted_text": {"notes": row["notes"]},
            }
        )
    hits = injection.scan([{"notes": c["untrusted_text"]["notes"],
                            "purchase_notes": [p["untrusted_text"]["notes"] for p in c["purchase_history"]]}
                           for c in candidates], "catalog")
    return {
        "candidates": candidates,
        "overlap_flag_candidates": flag_ids,
        "keywords_used": keywords,
        "reference": "software_catalog.csv",
        "injection_scan": {"detected": bool(hits), "hits": hits},
    }


# ---------------------------------------------------------------- R6 vendor
def registry_class(value: str | None) -> str:
    v = (value or "").strip().casefold()
    return {"approved": "approved", "pending": "pending", "expired": "expired"}.get(v, "unknown")


def api_class(value: str | None) -> str:
    v = (value or "").strip().casefold()
    if v == "approved":
        return "approved"
    if v == "expired":
        return "expired"
    if v in {"not_completed", "pending", "in_progress"}:
        return "pending"
    return "unknown"


def _bool_or_none(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def derive_vendor(registry: dict | None, api: dict, reference: date) -> VendorDerived:
    outcome = api.get("outcome", "not_checked")
    record = api.get("record") or {}
    d = VendorDerived(registered=registry is not None, api_outcome=outcome)
    if registry is not None:
        d.registry_class = registry_class(registry.get("security_status"))
        d.registry_review_date = (registry.get("security_review_date") or "").strip() or None
        d.registry_age_days = review_age(d.registry_review_date, reference)
        # D-07.4: Approved with a blank or future date is not current (Security), but not expired.
        d.registry_current = d.registry_class == "approved" and is_current(d.registry_age_days)
        d.procurement_status = (registry.get("procurement_status") or "").strip() or None
        d.legal_terms_status = (registry.get("legal_terms_status") or "").strip() or None
    d.new_vendor = registry is None or (d.procurement_status or "").casefold() == "new"
    d.legal_terms_approved = registry is not None and (d.legal_terms_status or "").casefold() == "approved"
    if outcome == "ok":
        d.api_class = api_class(record.get("security_review_status"))
        d.api_review_date = (record.get("last_review_date") or None) if isinstance(record.get("last_review_date"), str) else None
        d.api_age_days = review_age(d.api_review_date, reference)
        d.api_current = d.api_class == "approved" and is_current(d.api_age_days)
        d.stores_data_outside_region = _bool_or_none(record.get("stores_data_outside_region"))
        d.processes_personal_data = _bool_or_none(record.get("processes_personal_data"))

    expired_dates: list[date] = []
    registry_expired = d.registry_class == "approved" and d.registry_age_days is not None and d.registry_age_days > REVIEW_VALID_DAYS
    api_expired = d.api_class == "expired" or (
        d.api_class == "approved" and d.api_age_days is not None and d.api_age_days > REVIEW_VALID_DAYS
    )
    if registry_expired:
        expired_dates.append(_parse_date(d.registry_review_date))
    if api_expired and _parse_date(d.api_review_date):
        expired_dates.append(_parse_date(d.api_review_date))
    d.expired = registry_expired or api_expired
    if expired_dates:
        d.expired_on = (min(expired_dates) + timedelta(days=REVIEW_VALID_DAYS)).isoformat()

    if d.registered and outcome == "ok":
        one_approved = (d.registry_class == "approved") != (d.api_class == "approved")
        both_approved_dates_differ = (
            d.registry_class == "approved" and d.api_class == "approved" and d.registry_review_date != d.api_review_date
        )
        d.conflict = one_approved or both_approved_dates_differ

    api_ok_for_clearance = d.api_current or outcome in {"unavailable", "not_found"}
    d.cleared = d.registry_current and not d.conflict and not d.expired and api_ok_for_clearance
    return d


def vendor_status(vendor_name: str | None, ctx) -> VendorStatus:
    """Registry + external vendor-risk API, reconciled against the reference date."""
    name = (vendor_name or "").strip() or None
    registry = da.find_vendor(name) if name else None
    canonical = registry["vendor_name"] if registry else name
    if name is None:
        api = {"outcome": "not_checked", "status_code": None, "record": None,
               "error": "vendor name missing from the request", "attempts": 0, "duration_ms": 0, "endpoint": None}
    else:
        api = ctx.vendor_api(canonical)
    derived = derive_vendor(registry, api, ctx.reference_date)
    registry_block = {"registered": registry is not None}
    if registry is not None:
        registry_block.update({k: registry[k] for k in
                               ["vendor_id", "vendor_name", "procurement_status", "security_status",
                                "security_review_date", "legal_terms_status"]})
    record = dict(api.get("record") or {})
    api_notes = {k: v for k, v in record.items() if isinstance(v, str) and k not in {"vendor_name", "security_review_status", "last_review_date", "risk_level"}}
    untrusted = {"registry_notes": registry.get("notes") if registry else None, "api_text": api_notes,
                 "api_error_detail": api.get("detail")}
    hits = (injection.scan({"registry_notes": untrusted["registry_notes"]}, "vendor")
            + injection.scan({**api_notes, "error_detail": api.get("detail")}, "vendor_api"))
    api_block = {
        "outcome": api.get("outcome"),
        "status_code": api.get("status_code"),
        "endpoint": api.get("endpoint"),
        "attempts": api.get("attempts"),
        "error": api.get("error"),
        "record": {k: v for k, v in record.items() if k not in api_notes} if record else None,
    }
    return VendorStatus(
        vendor_name=name,
        canonical_name=canonical,
        registry=registry_block,
        api=api_block,
        derived=derived,
        untrusted_text=untrusted,
        injection_scan={"detected": bool(hits), "hits": hits},
    )


# ---------------------------------------------------------------- R7 data classes
def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.casefold()) if t]


def level_classes(level: str | None) -> tuple[list[str], bool]:
    """(classes, unrecognized) for a casefolded data_access_level; None means missing."""
    if level is None:
        return [], False
    if level in LEVEL_MAP:
        return list(LEVEL_MAP[level]), False
    # Whole tokens only (plurals allowed): "product_usage" is not "prod", "reporting" is not "repo".
    tokens = {t[:-1] if t.endswith("s") and len(t) > 3 else t for t in _tokens(level)}
    has = lambda *keys: bool(tokens & set(keys))  # noqa: E731
    classes = []
    if has("pii", "personal"):
        classes.append("employee_pii" if has("employee", "hr") else "customer_pii")
    if has("source", "code", "repo", "repository", "repositorie"):
        classes.append("source_code")
    if has("confidential"):
        classes.append("confidential_documents")
    if has("prod", "production", "cloud"):
        classes.append("production_access")
    if has("credential", "secret", "password"):
        classes.append("credentials")
    return classes, not classes


def integration_class(integration: str) -> str | None:
    text = integration.casefold()
    for pattern, cls in INTEGRATION_RULES:
        if pattern.search(text):
            return cls
    return None


def data_classes(req: NormalizedRequest) -> tuple[list[dict], bool]:
    found: list[dict] = []
    classes, unrecognized = level_classes(req.data_access_level)
    found += [{"class": c, "source": f"data_access_level '{req.data_access_level}'"} for c in classes]
    for integration in req.requested_integrations or []:
        cls = integration_class(integration)
        if cls:
            found.append({"class": cls, "source": f"integration '{integration}'"})
    return found, unrecognized


# ---------------------------------------------------------------- R0–R12 assembly
class _Builder:
    def __init__(self):
        self.roles: dict[str, list[Reason]] = {}
        self.flags: dict[str, list[Reason]] = {}

    def role(self, role: str, rule: str, ref: str, detail: str) -> None:
        self.roles.setdefault(role, []).append(Reason(rule=rule, policy_ref=ref, detail=detail))

    def flag(self, flag: str, rule: str, ref: str, detail: str) -> None:
        self.flags.setdefault(flag, []).append(Reason(rule=rule, policy_ref=ref, detail=detail))


def _join(items: list[str]) -> str:
    return ", ".join(items)


def evaluate(request_id: str, ctx) -> PolicyResult:
    """Run rules R0–R12 for one request. Raises KeyError for an unknown request_id."""
    raw = da.get_request(request_id)
    req = normalize_request(raw)
    ref_date: date = ctx.reference_date
    b = _Builder()
    evidence: list[EvidenceItem] = []

    # R2 requester, R1 required fields
    requester = requester_info(req.requester_id)
    department = requester["department"]
    missing_fields = missing_request_fields(req, requester)
    missing_info = list(missing_fields)
    if missing_fields:
        b.flag("missing_information", "R1", "§1", f"Missing: {_join(missing_fields)}")
        evidence.append(EvidenceItem(source="get_request_details",
                                     finding=f"Required request information missing: {_join(missing_fields)}",
                                     reference="policy §1"))
    if req.notes:
        evidence.append(EvidenceItem(source="get_request_details",
                                     finding="The annual cost in the request is not a valid non-negative number",
                                     reference="policy §1"))

    # R10 injection (never changes any other rule output)
    hits = injection.scan(raw, "request")

    # R4 tier
    cost = req.annual_cost_usd
    tier_label, tier_roles = tier(cost)
    for role in tier_roles:
        if cost is None:
            detail = "Annual cost missing: Procurement triages until it is provided (financial tier undetermined)"
        else:
            detail = f"Annual cost {usd(cost)} is in the {tier_label} tier"
        b.role(role, "R4", "§4", detail)
    evidence.append(EvidenceItem(
        source="evaluate_policy_rules",
        finding=(f"Annual cost {usd(cost)} → tier {tier_label}: {_join(tier_roles)}" if cost is not None
                 else f"Annual cost missing → financial tier undetermined; {_join(tier_roles)} triages"),
        reference="policy §4"))

    # R3 budget
    budget = budget_check(department, cost)
    if budget["status"] == "unverified":
        b.role("Finance", "R3", "§2", f"No software budget record for department {department}: budget cannot be verified")
        b.flag("budget_unverified", "R3", "§2", f"No software budget record for department {department}")
        missing_info.append(GAP_NO_BUDGET)
        evidence.append(EvidenceItem(source="check_budget",
                                     finding=f"No software budget record for department {department}; budget could not be verified",
                                     reference="department_budgets.csv"))
    elif budget["status"] == "insufficient":
        shortfall = cost - budget["available_usd"]
        detail = f"Annual cost {usd(cost)} exceeds {department} available software budget {usd(budget['available_usd'])}"
        b.role("Finance", "R3", "§2", detail + ": budget exception review")
        b.flag("budget_insufficient", "R3", "§2", detail)
        evidence.append(EvidenceItem(source="check_budget",
                                     finding=f"{department} available software budget {usd(budget['available_usd'])}; request {usd(cost)} → exceeds budget by {usd(shortfall)}",
                                     reference=budget["reference"]))
    elif budget["status"] == "ok":
        evidence.append(EvidenceItem(source="check_budget",
                                     finding=f"{department} available software budget {usd(budget['available_usd'])}; request {usd(cost)} → within budget ({usd(budget['remaining_after_usd'])} left)",
                                     reference=budget["reference"]))
    else:
        evidence.append(EvidenceItem(source="check_budget", finding=f"Budget not checked: {budget['reason']}",
                                     reference="department_budgets.csv"))

    # R5 catalog
    catalog = catalog_search(req)
    flagged = [c for c in catalog["candidates"] if c["overlap_flag"]]
    vendor_only = [c for c in catalog["candidates"] if not c["overlap_flag"]]
    if flagged:
        listing = "; ".join(f"{c['software_id']} {c['product_name']} ({c['category']}, {c['licensed_seats']} seats, {c['scope']})" for c in flagged)
        b.flag("existing_tool_overlap", "R5", "§3", f"Same category or identical product in catalog: {_join([c['software_id'] for c in flagged])}")
        evidence.append(EvidenceItem(source="search_software_catalog",
                                     finding=f"Existing catalog products with the same category or product name: {listing}",
                                     reference="software_catalog.csv:" + ",".join(c["software_id"] for c in flagged)))
    if vendor_only:
        listing = "; ".join(f"{c['software_id']} {c['product_name']} ({c['category']})" for c in vendor_only)
        evidence.append(EvidenceItem(source="search_software_catalog",
                                     finding=f"Same vendor already in the catalog, different category (no overlap flag): {listing}",
                                     reference="software_catalog.csv:" + ",".join(c["software_id"] for c in vendor_only)))
    if not catalog["candidates"]:
        evidence.append(EvidenceItem(source="search_software_catalog",
                                     finding="No catalog product shares this request's category, vendor or product name",
                                     reference="software_catalog.csv"))
    hits += catalog["injection_scan"]["hits"]

    # R6 vendor
    vs = vendor_status(req.vendor_name, ctx)
    vd = vs.derived
    hits += vs.injection_scan["hits"]
    endpoint = vs.api.get("endpoint") or "vendor-risk API"
    if vd.registered:
        r = vs.registry
        age = f" ({vd.registry_age_days} days before {ref_date.isoformat()})" if vd.registry_age_days is not None else ""
        evidence.append(EvidenceItem(
            source="get_vendor_status",
            finding=(f"Registry: {r['vendor_name']} procurement {r['procurement_status'] or 'blank'}, security {r['security_status'] or 'blank'}, "
                     f"review date {r['security_review_date'] or 'none'}{age}, legal terms {r['legal_terms_status'] or 'blank'}"),
            reference=f"vendors.csv:{r['vendor_id']}"))
    elif req.vendor_name:
        b.flag("vendor_not_registered", "R6", "§5, §7", "Vendor is not in the internal registry")
        evidence.append(EvidenceItem(source="get_vendor_status",
                                     finding=f"Vendor '{req.vendor_name}' is not in the internal registry: treated as a new vendor with unknown terms",
                                     reference="vendors.csv"))
    if vd.api_outcome == "ok":
        rec = vs.api["record"] or {}
        outside = {True: "yes", False: "no"}.get(vd.stores_data_outside_region, "unknown")
        evidence.append(EvidenceItem(
            source="get_vendor_status",
            finding=(f"Vendor-risk API: security_review_status {rec.get('security_review_status')}, last review "
                     f"{rec.get('last_review_date') or 'none'}, stores data outside region: {outside}"),
            reference=endpoint))
    elif vd.api_outcome == "not_found":
        missing_info.append(GAP_NOT_FOUND)  # D-07.5
        evidence.append(EvidenceItem(source="get_vendor_status",
                                     finding=f"Vendor-risk API has no record for this vendor (HTTP {vs.api.get('status_code')})",
                                     reference=endpoint))
    elif vd.api_outcome == "unavailable":
        b.flag("vendor_risk_unavailable", "R6", "§10", f"Vendor-risk service unavailable ({vs.api.get('error')})")
        missing_info += [GAP_UNAVAILABLE, GAP_RESIDENCY]  # D-07.5
        evidence.append(EvidenceItem(source="get_vendor_status",
                                     finding=f"Vendor-risk service unavailable: security status could not be verified ({vs.api.get('error')})",
                                     reference=endpoint))
    if vd.conflict:
        detail = (f"Registry security {vs.registry.get('security_status')} (review {vd.registry_review_date or 'none'}) vs "
                  f"vendor-risk API {vs.api['record'].get('security_review_status')} (review {vd.api_review_date or 'none'})")
        b.flag("conflicting_vendor_evidence", "R6", "§5", detail)
        evidence.append(EvidenceItem(source="get_vendor_status", finding=f"Conflicting vendor evidence: {detail}",
                                     reference=f"vendors.csv:{vs.registry.get('vendor_id')} vs {endpoint}"))
    if vd.expired:
        when = f"; expired on {vd.expired_on}" if vd.expired_on else ""
        detail = f"Security review is older than {REVIEW_VALID_DAYS} days or reported expired{when}"
        b.flag("vendor_review_expired", "R6", "§5", detail)
        dates = sorted({d for d in [vd.registry_review_date, vd.api_review_date] if d})
        evidence.append(EvidenceItem(source="get_vendor_status",
                                     finding=f"Security review dated {', '.join(dates) or 'unknown'} is not current (valid {REVIEW_VALID_DAYS} days){when}",
                                     reference="policy §5"))
    if not vd.cleared:
        specifics = []
        if not vd.registered:
            specifics.append("vendor not registered" if req.vendor_name else "vendor not named")
        elif vd.registry_class != "approved":
            specifics.append(f"registry security status {vs.registry.get('security_status') or 'blank'}")
        elif vd.registry_age_days is None:
            specifics.append("registry review date missing or invalid")
        elif vd.registry_age_days < 0:
            specifics.append("registry review date is after the reference date")
        elif not vd.registry_current:
            specifics.append(f"registry review is {vd.registry_age_days} days old")
        if vd.api_outcome == "ok" and not vd.api_current:
            specifics.append(f"vendor-risk API status {(vs.api['record'] or {}).get('security_review_status')}")
        if vd.conflict:
            specifics.append("registry and vendor-risk API disagree")
        if vd.expired:
            specifics.append("review expired")
        b.role("Security", "R6", "§5",
               "Vendor security assessment missing, expired, not completed or conflicting"
               + (f": {_join(specifics)}" if specifics else ""))
    if vd.registered and vd.api_outcome == "not_found":  # D-01
        b.role("Security", "R6", "§5, §10",
               "Vendor-risk service has no record for a registered vendor; assessment cannot be verified")

    # R7 data classes
    classes, unrecognized = data_classes(req)
    class_names = list(dict.fromkeys(c["class"] for c in classes))
    if unrecognized:
        b.flag("unrecognized_data_access_level", "R7", "§5", f"Data access level '{req.data_access_level}' is not recognized")
        b.role("Security", "R7", "§5", f"Unrecognized data access level '{req.data_access_level}': sensitive data cannot be ruled out")
    for c in classes:
        b.role("Security", "R7", "§5", f"Data class {c['class']} ({c['source']})")
        if c["class"] in PII_CLASSES:
            b.role("Privacy", "R7", "§6", f"{c['class']} ({c['source']})")
    if classes:
        evidence.append(EvidenceItem(source="evaluate_policy_rules",
                                     finding="Sensitive data classes: " + "; ".join(f"{c['class']} from {c['source']}" for c in classes),
                                     reference="policy §5, §6"))
    elif unrecognized:
        evidence.append(EvidenceItem(source="evaluate_policy_rules",
                                     finding=f"Data access level '{req.data_access_level}' is not recognized; Security review added",
                                     reference="policy §5"))

    # R8 cross-region (plus D-14 proposed: 404 with sensitive data -> residency unverified)
    sensitive = [c for c in class_names if c in PII_CLASSES or c == "confidential_documents"]
    if sensitive and vd.api_outcome == "ok" and vd.stores_data_outside_region is True:
        detail = f"Vendor stores data outside the region and the request involves {_join(sensitive)}: material cross-region issue"
        b.role("Privacy", "R8", "§6", detail)
        b.role("Legal", "R8", "§7", detail)
        evidence.append(EvidenceItem(source="get_vendor_status", finding=detail, reference="policy §6, §7"))
    elif sensitive and (vd.api_outcome in {"unavailable", "not_found"} or vd.stores_data_outside_region is None):
        why = {"unavailable": "vendor-risk service unavailable", "not_found": "vendor-risk service has no record",
               "ok": "vendor-risk record does not state residency"}.get(vd.api_outcome, "vendor-risk service not queried")
        b.role("Privacy", "R8", "§6, §10", f"Data residency unverified ({why}) for {_join(sensitive)}")

    # R9 legal
    if vd.new_vendor and cost is not None and cost >= NEW_VENDOR_LEGAL_THRESHOLD:
        b.role("Legal", "R9", "§7", f"New vendor with annual spend {usd(cost)} (≥ $10,000)")
    if not vd.legal_terms_approved:
        if vd.registered:
            b.role("Legal", "R9", "§7", f"Legal terms status {vd.legal_terms_status or 'blank'} (not approved/standard)")
        else:
            b.role("Legal", "R9", "§7", "Vendor not in the registry: legal terms unknown")

    # R10 evidence + flag
    if hits:
        b.flag("prompt_injection_detected", "R10", "§9", f"Instruction-like text in {_join([h['field'] for h in hits])}")
        for h in hits[:3]:
            evidence.append(EvidenceItem(source="injection_scan",
                                         finding=f"Instruction-like text in {h['field']} was ignored: \"{h['excerpt']}\"",
                                         reference="policy §9"))

    # R11 approvals assembly; specialist flags follow the roles
    approvals = []
    for role in ROLE_ORDER:
        if role in b.roles:
            hint = requester["manager_hint"] if role == "Manager" else requester["department_head_hint"] if role == "Department Head" else None
            approvals.append(RoleApproval(role=role, reasons=b.roles[role], hint=hint))
            if role in ROLE_FLAGS:
                for reason in b.roles[role]:
                    b.flag(ROLE_FLAGS[role], reason.rule, reason.policy_ref, reason.detail)
    flags = [f for f in FLAG_ORDER if f in b.flags]
    roles = [a.role for a in approvals]

    # R12 decision precedence (rules only: step 2 needs the agent's overlap assessment)
    if missing_fields:
        decision = "request_clarification"
    elif {"Security", "Privacy", "Legal"} & set(roles) or {"budget_insufficient", "budget_unverified", "conflicting_vendor_evidence"} & set(flags):
        decision = "route_for_specialist_review"
    else:
        decision = "route_for_approval"

    return PolicyResult(
        request_id=request_id,
        reference_date=ref_date.isoformat(),
        policy_version=get_policy_version(),
        requester=requester,
        department=department,
        annual_cost_usd=cost,
        tier=tier_label,
        tier_roles=tier_roles,
        approvals=approvals,
        flags=flags,
        flag_reasons={f: b.flags[f] for f in flags},
        missing_information=list(dict.fromkeys(missing_info)),
        missing_request_fields=missing_fields,
        request_fields_missing=bool(missing_fields),
        data_classes=classes,
        budget=budget,
        catalog_candidates=[{k: v for k, v in c.items() if k != "untrusted_text"} for c in catalog["candidates"]],
        overlap_flag_candidates=catalog["overlap_flag_candidates"],
        vendor=vs,
        injection_hits=hits,
        evidence=evidence,
        rules_decision_type=decision,
        notes=req.notes,
    )
