"""Rules-only decision (T12): gate tools + policy engine + guardrails with templates.

Used when the LLM is unavailable (flag llm_unavailable) and for the --no-llm eval
baseline (mode rules_only, no flag).
"""
from __future__ import annotations

from src import guardrails, tools
from src.contracts import EvidenceItem, ProcurementDecision, RunTelemetry
from src.schemas import EvidenceProposal
from src.tools import RunContext

UNKNOWN_REQUEST_ITEM = "request record (unknown request ID)"


def rules_only(ctx: RunContext, trace, llm_failed: bool,
               extra_evidence: list[EvidenceProposal] | None = None) -> tuple[ProcurementDecision, dict]:
    """Run the gate tools and the policy engine, then assemble with no proposal."""
    filled = tools.run_gate(ctx, tools.GATE_SINGLE)
    trace.step("code:gate", "completeness gate", f"required: {', '.join(tools.GATE_SINGLE)}",
               f"filled: {', '.join(filled) or 'none'}")
    policy = tools.policy_for(ctx)
    if policy is None:
        raise RuntimeError("policy engine produced no result")
    trace.step("code:policy_engine", "evaluate_policy_rules", ctx.request_id,
               f"approvals: {', '.join(policy.required_approvals)}; flags: {', '.join(policy.flags) or 'none'}")
    extra_flags = ["llm_unavailable"] if llm_failed else []
    decision, report = guardrails.assemble(policy, None, ctx, extra_flags=extra_flags, extra_evidence=extra_evidence)
    trace.step("code:fallback", "rules-only decision",
               "LLM unavailable" if llm_failed else "rules-only mode",
               decision.recommendation)
    return decision, {**report, "policy": policy}


def unknown_request_decision(request_id: str) -> ProcurementDecision:
    """D-07.8: an unknown request ID returns a valid request_clarification decision."""
    return ProcurementDecision(
        request_id=request_id,
        recommendation="Request clarification: No purchase request with this ID was found; it cannot be reviewed.",
        evidence=[EvidenceItem(source="get_request_details", finding="No purchase request record matches this ID",
                               reference="requests.json")],
        required_approvals=["Procurement"],
        missing_information=[UNKNOWN_REQUEST_ITEM],
        risk_flags=["missing_information"],
        next_step="Ask the requester to resubmit the request with a valid request ID; Procurement triages it.",
        human_review_required=True,
        telemetry=RunTelemetry(llm_calls=0, tool_calls=0, tool_names=[]),
    )


def error_decision(request_id: str, error: str) -> ProcurementDecision:
    """Last resort if even the rules-only path fails: hold for manual review, never favorable."""
    return ProcurementDecision(
        request_id=request_id,
        recommendation="Route for specialist review: The copilot could not complete its checks; a manual procurement review is required.",
        evidence=[EvidenceItem(source="copilot", finding=f"Automated analysis failed ({error}); nothing was verified",
                               reference=None)],
        required_approvals=["Procurement"],
        missing_information=["automated policy checks (analysis failed)"],
        risk_flags=["missing_information"],
        next_step="Hold the request for a manual procurement review; no approver has been contacted.",
        human_review_required=True,
        telemetry=RunTelemetry(llm_calls=0, tool_calls=0, tool_names=[]),
    )
