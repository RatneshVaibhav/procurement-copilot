"""Internal schemas: policy-engine result, vendor status (T5, T6) and the
LLM-facing proposal schemas (T8 + D6)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.contracts import EvidenceItem

DecisionType = Literal["route_for_approval", "route_for_specialist_review", "request_clarification", "use_existing_tool"]
Role = Literal["Manager", "Department Head", "Finance", "CFO", "Procurement", "Security", "Privacy", "Legal"]

# R0 canonical vocab
ROLE_ORDER: list[str] = ["Manager", "Department Head", "Finance", "CFO", "Procurement", "Security", "Privacy", "Legal"]
SPECIALIST_ROLES = {"Security", "Privacy", "Legal"}
STARTER_FLAGS = [
    "existing_tool_overlap",
    "budget_insufficient",
    "security_review_required",
    "privacy_review_required",
    "legal_review_required",
    "vendor_review_expired",
    "conflicting_vendor_evidence",
    "vendor_risk_unavailable",
    "prompt_injection_detected",
    "missing_information",
]
ADDED_FLAGS = ["vendor_not_registered", "budget_unverified", "unrecognized_data_access_level", "llm_unavailable"]
FLAG_ORDER: list[str] = STARTER_FLAGS + ADDED_FLAGS
ROLE_FLAGS = {"Security": "security_review_required", "Privacy": "privacy_review_required", "Legal": "legal_review_required"}


# ---------------------------------------------------------------- policy engine
class Reason(BaseModel):
    rule: str
    policy_ref: str
    detail: str


class RoleApproval(BaseModel):
    role: Role
    reasons: list[Reason] = Field(default_factory=list)
    hint: str | None = None


class VendorDerived(BaseModel):
    registered: bool
    registry_class: str | None = None
    registry_review_date: str | None = None
    registry_age_days: int | None = None
    registry_current: bool = False
    api_outcome: str
    api_class: str | None = None
    api_review_date: str | None = None
    api_age_days: int | None = None
    api_current: bool = False
    expired: bool = False
    expired_on: str | None = None
    conflict: bool = False
    cleared: bool = False
    new_vendor: bool = False
    procurement_status: str | None = None
    legal_terms_status: str | None = None
    legal_terms_approved: bool = False
    stores_data_outside_region: bool | None = None
    processes_personal_data: bool | None = None


class VendorStatus(BaseModel):
    vendor_name: str | None
    canonical_name: str | None
    registry: dict
    api: dict
    derived: VendorDerived
    untrusted_text: dict = Field(default_factory=dict)
    injection_scan: dict = Field(default_factory=dict)


class PolicyResult(BaseModel):
    request_id: str
    reference_date: str
    policy_version: str | None = None
    requester: dict
    department: str | None
    annual_cost_usd: float | None
    tier: str
    tier_roles: list[str]
    approvals: list[RoleApproval]
    flags: list[str]
    flag_reasons: dict[str, list[Reason]] = Field(default_factory=dict)
    missing_information: list[str]
    missing_request_fields: list[str]
    request_fields_missing: bool
    data_classes: list[dict]
    budget: dict
    catalog_candidates: list[dict]
    overlap_flag_candidates: list[str]
    vendor: VendorStatus
    injection_hits: list[dict]
    evidence: list[EvidenceItem]
    rules_decision_type: DecisionType
    notes: list[str] = Field(default_factory=list)

    @property
    def required_approvals(self) -> list[str]:
        return [a.role for a in self.approvals]

    def role_reasons(self, role: str) -> list[Reason]:
        return next((a.reasons for a in self.approvals if a.role == role), [])


# ---------------------------------------------------------------- LLM-facing (T8, D6)
class ApprovalProposal(BaseModel):
    role: Role
    reason: str


class OverlapAssessment(BaseModel):
    software_id: str
    relationship: Literal["same_product_expansion", "substitute_could_meet_need", "related_not_substitute"]
    covers_stated_need: bool
    reason: str


class EvidenceProposal(BaseModel):
    source: str
    finding: str
    reference: str | None = None


class AgentProposal(BaseModel):  # submit_recommendation args (A, and B stage 2)
    decision_type: DecisionType
    recommendation: str
    next_step: str
    required_approvals: list[ApprovalProposal]
    risk_flags: list[str]
    missing_information: list[str]
    overlap_assessment: list[OverlapAssessment]
    evidence: list[EvidenceProposal]
    injection_observed: bool
    injection_excerpt: str | None = None


class EvidencePack(BaseModel):  # submit_evidence_pack args (B stage 1)
    need_summary: str
    data_classes_implied: list[str]
    overlap_assessment: list[OverlapAssessment]
    vendor_observations: list[str]
    uncertainties: list[str]
    injection_observed: bool
    injection_excerpt: str | None = None
    evidence: list[EvidenceProposal]
    gaps: list[str]
    unsupported_or_unverified: list[str]


class AnalystAudit(BaseModel):
    issues_found: list[str]
    rejected_claims: list[str]
    agrees_with_overlap_assessment: bool


class ReviewerProposal(AgentProposal):  # B stage 2 output
    analyst_audit: AnalystAudit
