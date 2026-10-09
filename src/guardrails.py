"""Guardrails and assembler (T11): merge + validate + ground → ProcurementDecision.

Code decides; the LLM may only add. The policy engine's approvals, flags and missing
information are never removed. Every correction is logged as an event on the RunContext.
"""
from __future__ import annotations

import re

from src import injection
from src.contracts import EvidenceItem, ProcurementDecision, RunTelemetry
from src.schemas import (
    FLAG_ORDER,
    ROLE_FLAGS,
    ROLE_ORDER,
    SPECIALIST_ROLES,
    AgentProposal,
    EvidenceProposal,
    PolicyResult,
)

EVIDENCE_CAP = 12
MISSING_ADD_CAP = 3
MISSING_ITEM_MAX = 120
SENTENCE_MAX = 400
INJECTION_EXCERPT_MIN = 8

LABELS = {
    "route_for_approval": "Route for approval",
    "route_for_specialist_review": "Route for specialist review",
    "request_clarification": "Request clarification",
    "use_existing_tool": "Use existing tool",
}
LABEL_TO_DECISION = {v.casefold(): k for k, v in LABELS.items()}

OUTPUT_FILTER = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\b(this|the)\s+(request|purchase)\s+(is|has\s+been|was)\s+(pre-?)?approved\b",
        r"\bpre-?approved\b|\bcfo[- ]approved\b|\bapproval\s+(is\s+)?granted\b",
        r"\b(approve|approving)\s+(it|this|the\s+request)\s+(now|immediately)\b",
        r"\b(purchase|order)\s+(has\s+been\s+|is\s+)?(placed|completed|made)\b",
    ]
]
GROUNDING_TOKEN = re.compile(r"\$?\d[\d,]*(\.\d+)?|\d{4}-\d{2}-\d{2}|[A-Z]{1,4}-?\d{2,5}")
FULL_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def output_filter_hit(text: str | None) -> bool:
    return bool(text) and any(p.search(text) for p in OUTPUT_FILTER)


def decision_from_recommendation(recommendation: str) -> str | None:
    label = recommendation.split(":", 1)[0].strip().casefold()
    return LABEL_TO_DECISION.get(label)


def _norm_space(text: str) -> str:
    return " ".join(str(text).split()).casefold()


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


# ---------------------------------------------------------------- grounding (T11 step 7, D-07.7)
def grounding_tokens(finding: str) -> list[str]:
    return [m.group(0).replace("$", "").replace(",", "") for m in GROUNDING_TOKEN.finditer(finding)]


def _token_in(token: str, corpus: str) -> bool:
    """Whole-token match: 1500 must not match inside 15000, SW00 not inside SW001."""
    left = r"(?<![A-Za-z0-9])" if token[:1].isalpha() else r"(?<![0-9.])"
    return re.search(left + re.escape(token) + r"(?![0-9])", corpus) is not None


def is_grounded(item: EvidenceProposal, ctx) -> tuple[bool, str | None]:
    called = {t["name"] for t in ctx.tool_log if t["status"] in {"ok", "cached"}}
    if item.source != "copilot_analysis" and item.source not in called:
        return False, f"source {item.source!r} was not called in this run"
    corpus = ctx.evidence_corpus
    corpus_norm = corpus.replace("$", "").replace(",", "")
    for date_text in FULL_DATE.findall(item.finding):  # dates must appear whole, not piecewise
        if date_text not in corpus:
            return False, f"date {date_text!r} not found in tool results"
    for token in grounding_tokens(item.finding):
        if token and not (_token_in(token, corpus) or _token_in(token, corpus_norm)):
            return False, f"token {token!r} not found in tool results"
    return True, None


# ---------------------------------------------------------------- untrusted text for D-04
def untrusted_texts(ctx) -> list[str]:
    texts: list[str] = []

    def walk(value, inside: bool):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, inside or k in {"untrusted_text", "hits", "facts"})
        elif isinstance(value, list):
            for v in value:
                walk(v, inside)
        elif isinstance(value, str) and inside:
            texts.append(value)

    for r in ctx.results:
        walk(r["result"], False)
    return texts


def excerpt_is_verbatim(excerpt: str | None, ctx) -> bool:
    if not excerpt or len(_norm_space(excerpt)) < INJECTION_EXCERPT_MIN:
        return False
    needle = _norm_space(excerpt).strip("\"'“”‘’ ")
    return any(needle in _norm_space(t) for t in untrusted_texts(ctx))


# ---------------------------------------------------------------- templates (T11.1)
def _reasons_short(roles: list[str], flags: list[str]) -> str:
    parts = [f"{r} review" for r in roles if r in SPECIALIST_ROLES]
    if "budget_insufficient" in flags:
        parts.append("budget exception (Finance)")
    if "budget_unverified" in flags:
        parts.append("budget could not be verified (Finance)")
    if "conflicting_vendor_evidence" in flags:
        parts.append("conflicting vendor evidence")
    return ", ".join(parts) or "specialist checks"


def template_recommendation(decision: str, roles: list[str], flags: list[str]) -> str:
    return {
        "route_for_approval": "Request is complete and within policy; route to the approvers for this cost tier.",
        "route_for_specialist_review": f"Route for specialist review before any business approval: {_reasons_short(roles, flags)}.",
        "request_clarification": "Request is not ready for review; required information is missing.",
        "use_existing_tool": "An existing licensed tool may already meet this need.",
    }[decision]


def template_next_step(decision: str, roles: list[str], flags: list[str], policy: PolicyResult | None,
                       products: list[str]) -> str:
    requester = (policy.requester.get("name") if policy else None) or "the requester"
    if decision == "route_for_approval":
        return f"Send the evidence pack to {_join(roles)}."
    if decision == "route_for_specialist_review":
        specialists = [r for r in roles if r in SPECIALIST_ROLES]
        if not specialists and ("budget_insufficient" in flags or "budget_unverified" in flags):
            specialists = ["Finance"]
        first = _join(specialists) or "Procurement"
        return f"Send the evidence pack to {_join(roles)}; {first} review first."
    if decision == "request_clarification":
        fields = policy.missing_request_fields if policy else []
        return f"Ask {requester} to provide: {', '.join(fields) or 'the missing request details'}."
    return (f"Confirm with {requester} whether {_join(products) or 'the existing catalog product'} covers the need "
            "before starting a new purchase.")


def _clean_sentence(text: str | None, label: str) -> str:
    text = " ".join((text or "").split())
    if text.casefold().startswith(label.casefold() + ":"):
        text = text[len(label) + 1:].strip()
    return text


def _usable(text: str) -> bool:
    return bool(text) and len(text) <= SENTENCE_MAX and not output_filter_hit(text) and not injection.matches_injection(text)


# ---------------------------------------------------------------- assemble (T11)
def assemble(policy: PolicyResult, proposal: AgentProposal | None, ctx, extra_flags: list[str] | None = None,
             extra_evidence: list[EvidenceProposal] | None = None) -> tuple[ProcurementDecision, dict]:
    """Merge the authoritative policy result with an optional LLM proposal.

    Returns (decision, report). The report carries the guardrail details for the trace and UI.
    """
    report: dict = {"questions_for_reviewer": [], "ungrounded_evidence": [], "llm_added_reviews": [],
                    "approval_reasons": {a.role: [r.model_dump() for r in a.reasons] for a in policy.approvals},
                    "used_template_recommendation": True, "used_template_next_step": True}
    policy_roles = list(policy.required_approvals)

    # 1. Approvals: policy ∪ grounded Security/Privacy/Legal additions
    roles = list(policy_roles)
    approvals_changed = False
    if proposal is not None:
        proposed = {a.role: a.reason for a in proposal.required_approvals}
        for role, reason in proposed.items():
            if role in roles:
                continue
            if role in SPECIALIST_ROLES and reason and reason.strip():
                roles.append(role)
                report["llm_added_reviews"].append({"role": role, "reason": reason.strip()})
                report["approval_reasons"].setdefault(role, []).append(
                    {"rule": "AI", "policy_ref": "§5–§7", "detail": reason.strip()})
                ctx.event("llm_added_review", role=role, reason=reason.strip())
            else:
                approvals_changed = True
                ctx.event("llm_role_dropped", role=role)
        for role in policy_roles:
            if role not in proposed:
                approvals_changed = True
                ctx.event("code_restored_approval", role=role)
    roles = [r for r in ROLE_ORDER if r in roles]

    # 2. Flags: policy ∪ accepted LLM flags; specialist flags follow accepted roles (R11)
    flags = list(policy.flags)
    if proposal is not None:
        accepted_role_flags = {ROLE_FLAGS[r["role"]] for r in report["llm_added_reviews"]}
        proposed_flags = list(dict.fromkeys(proposal.risk_flags + (["prompt_injection_detected"] if proposal.injection_observed else [])))
        for flag in proposed_flags:
            if flag in flags:
                continue
            if flag == "prompt_injection_detected":
                if excerpt_is_verbatim(proposal.injection_excerpt, ctx):  # D-04
                    flags.append(flag)
                    ctx.event("llm_added_flag", flag=flag, excerpt=proposal.injection_excerpt)
                else:
                    ctx.event("llm_flag_dropped", flag=flag, why="injection excerpt not verbatim in untrusted tool text")
            elif flag in accepted_role_flags:
                continue  # added below with its role
            else:  # includes existing_tool_overlap not set by code (D-03) and unknown flags
                ctx.event("llm_flag_dropped", flag=flag)
        for flag in sorted(accepted_role_flags):
            if flag not in flags:
                flags.append(flag)
        for flag in policy.flags:
            if flag not in proposal.risk_flags:
                ctx.event("code_restored_flag", flag=flag)
    for flag in extra_flags or []:
        if flag not in flags:
            flags.append(flag)
    flags = [f for f in FLAG_ORDER if f in flags] + [f for f in flags if f not in FLAG_ORDER]

    # 3. Missing information: policy items; proposal items only when going back to the requester
    missing = list(policy.missing_information)
    if proposal is not None:
        added = 0
        for item in proposal.missing_information:
            text = " ".join(str(item).split())
            ok = (policy.request_fields_missing and added < MISSING_ADD_CAP and 0 < len(text) <= MISSING_ITEM_MAX
                  and not injection.matches_injection(text) and text.casefold() not in {m.casefold() for m in missing})
            if ok:
                missing.append(text)
                added += 1
            elif text and text.casefold() not in {m.casefold() for m in missing}:
                report["questions_for_reviewer"].append(text)

    # 4. Decision type: R12 with the agent's overlap assessment
    covering = []
    if proposal is not None:
        covering = [o for o in proposal.overlap_assessment
                    if o.software_id in policy.overlap_flag_candidates and o.covers_stated_need
                    and o.relationship != "related_not_substitute"]  # D-16 (proposed): contradictory pair
    if policy.request_fields_missing:
        decision = "request_clarification"
    elif covering:
        decision = "use_existing_tool"
    elif SPECIALIST_ROLES & set(roles) or {"budget_insufficient", "budget_unverified", "conflicting_vendor_evidence"} & set(flags):
        decision = "route_for_specialist_review"
    else:
        decision = "route_for_approval"
    overridden = proposal is not None and proposal.decision_type != decision
    if overridden:
        ctx.event("llm_decision_overridden", proposed=proposal.decision_type, final=decision)
    report["decision_type"] = decision
    report["overlap_covering"] = [o.software_id for o in covering]
    products = [c["product_name"] for c in policy.catalog_candidates if c["software_id"] in report["overlap_covering"]]

    # 5–6. Recommendation and next step: proposal wording only if not overridden and it passes the filters
    label = LABELS[decision]
    sentence = template_recommendation(decision, roles, flags)
    next_step = template_next_step(decision, roles, flags, policy, products)
    if proposal is not None and not overridden:
        candidate = _clean_sentence(proposal.recommendation, label)
        if _usable(candidate):
            sentence = candidate
            report["used_template_recommendation"] = False
        else:
            ctx.event("output_guardrail_triggered", field="recommendation")
        candidate = _clean_sentence(proposal.next_step, label)
        if not approvals_changed and _usable(candidate):
            next_step = candidate
            report["used_template_next_step"] = False
        elif not _usable(candidate):
            ctx.event("output_guardrail_triggered", field="next_step")
    recommendation = f"{label}: {sentence}"

    # 7. Evidence: deterministic first, then grounded proposal items; cap 12
    evidence = list(policy.evidence)
    seen = {_norm_space(e.finding) for e in evidence}
    candidates = list(proposal.evidence if proposal is not None else []) + list(extra_evidence or [])
    for item in candidates:
        grounded, why = is_grounded(item, ctx)
        if not grounded:
            ctx.event("ungrounded_evidence_removed", source=item.source, why=why)
            report["ungrounded_evidence"].append({**item.model_dump(), "why": why})
            continue
        if _norm_space(item.finding) in seen:
            continue
        seen.add(_norm_space(item.finding))
        evidence.append(EvidenceItem(source=item.source, finding=item.finding, reference=item.reference))
    evidence = evidence[:EVIDENCE_CAP]

    decision_obj = ProcurementDecision(
        request_id=policy.request_id,
        recommendation=recommendation,
        evidence=evidence,
        required_approvals=roles,
        missing_information=missing,
        risk_flags=flags,
        next_step=next_step,
        human_review_required=True,
        telemetry=RunTelemetry(llm_calls=ctx.llm_calls, tool_calls=ctx.tool_calls, tool_names=ctx.tool_names),
    )
    return decision_obj, report
