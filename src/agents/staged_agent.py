"""Architecture B: sequential specialists through a deterministic supervisor (D9).

Analyst (LLM + 5 tools) → completeness gate (code) → policy engine (code) →
Policy & Risk Reviewer (LLM, structured output, no tools) → guardrails (code).
Routing is plain code (`supervisor`), never an LLM. Every step is traced with its
route reason; MAX_STAGED_STEPS bounds the graph.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from src import fallback, guardrails, prompts, tools
from src.agents.loop import record_llm, run_tool_loop
from src.llm_client import InvalidOutput, LLMUnavailable, ToolUseFailed
from src.schemas import EvidencePack, PolicyResult, ReviewerProposal
from src.tools import RunContext
from src.tracing import traceable

MAX_STAGED_STEPS = 8
ANALYST_MAX_TURNS = 5


@dataclass
class StagedState:
    request_id: str
    ctx: RunContext
    evidence_pack: EvidencePack | None = None
    gate_done: bool = False
    policy: PolicyResult | None = None
    proposal: ReviewerProposal | None = None
    error: str | None = None
    steps: int = 0


def supervisor(s: StagedState) -> tuple[str, str]:
    """Deterministic routing (D9): (next_node, route_reason)."""
    if s.steps >= MAX_STAGED_STEPS:
        return "fallback", "step limit reached"
    if s.error:
        return "fallback", f"stage failed: {s.error}"
    if s.evidence_pack is None:
        return "analyst", "no evidence pack yet"
    if not s.gate_done:
        return "gate", "verify required evidence ran"
    if s.policy is None:
        return "policy_engine", "authoritative rules not computed"
    if s.proposal is None:
        return "reviewer", "evidence and rules ready for independent review"
    return "finalize", "all artifacts present"


# ---------------------------------------------------------------- nodes
def _analyst(s: StagedState, trace, llm) -> None:
    user = prompts.USER_ANALYSE.format(request_id=s.request_id, reference_date=s.ctx.reference_date.isoformat())
    loop = run_tool_loop(llm, prompts.SYSTEM_ANALYST, user, "analyst", "submit_evidence_pack", EvidencePack,
                         ANALYST_MAX_TURNS, s.ctx, trace, finalizer_model=None)
    trace.analyst_stop_reason = loop.stop_reason
    if loop.proposal is None:
        s.error = f"analyst {loop.stop_reason}"
        return
    s.evidence_pack = loop.proposal
    trace.evidence_pack = loop.proposal.model_dump()
    trace.proposals.append({"actor": "agent:analyst", "final_mode": loop.final_mode, "proposal": trace.evidence_pack})


def _gate(s: StagedState, trace, llm) -> None:
    filled = tools.run_gate(s.ctx, tools.GATE_STAGED)
    trace.step("code:gate", "completeness gate", f"required: {', '.join(tools.GATE_STAGED)}",
               f"filled: {', '.join(filled) or 'none'}")
    s.gate_done = True


def _policy_engine(s: StagedState, trace, llm) -> None:
    s.policy = tools.policy_for(s.ctx)  # runs evaluate_policy_rules with initiator="orchestrator"
    if s.policy is None:
        s.error = "policy engine produced no result"
        return
    trace.step("code:policy_engine", "evaluate_policy_rules", s.request_id,
               f"approvals: {', '.join(s.policy.required_approvals)}; flags: {', '.join(s.policy.flags) or 'none'}")


def referenced_sections(policy: PolicyResult) -> list[int]:
    refs = [r.policy_ref for a in policy.approvals for r in a.reasons]
    refs += [r.policy_ref for rs in policy.flag_reasons.values() for r in rs]
    numbers = {int(n) for ref in refs for n in re.findall(r"§\s*(\d+)", ref)}
    return sorted(n for n in numbers if n in tools.policy_sections())


def reviewer_messages(s: StagedState) -> list[dict]:
    raw = [{"tool": r["tool"], "args": r["args"], "result": r["result"]}
           for r in s.ctx.results if r["tool"] in tools.EVIDENCE_TOOLS]
    sections = tools.policy_sections()
    policy_text = "\n\n".join(f"§{n}. {sections[n]['title']}\n{sections[n]['text']}" for n in referenced_sections(s.policy))
    compact = lambda obj: json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)  # noqa: E731
    user = prompts.REVIEWER_USER.format(
        evidence_pack=tools.UNTRUSTED_PREFIX + compact(s.evidence_pack.model_dump()),
        tool_results=tools.UNTRUSTED_PREFIX + compact(raw),
        policy=tools.UNTRUSTED_PREFIX + compact(tools.compact_policy(s.policy)),  # quotes request text (injection hits)
        policy_text=policy_text or "(no sections referenced)",
    )
    return [{"role": "system", "content": prompts.SYSTEM_REVIEWER}, {"role": "user", "content": user}]


def _reviewer(s: StagedState, trace, llm) -> None:
    try:
        proposal, res = llm.chat_structured(reviewer_messages(s), ReviewerProposal, "submit_recommendation")
    except InvalidOutput as exc:
        if exc.result is not None:
            record_llm(s.ctx, trace, "agent:reviewer", exc.result)
        trace.step("agent:reviewer", "structured review", "evidence pack + raw tool results + policy", "invalid after one repair")
        s.error = "reviewer invalid_output"
        return
    except ToolUseFailed as exc:
        s.ctx.event("tool_use_failed", actor="reviewer", error=str(exc))
        trace.step("agent:reviewer", "structured review", "evidence pack + raw tool results + policy", "provider rejected the output (tool_use_failed)")
        s.error = "reviewer tool_use_failed"
        return
    record_llm(s.ctx, trace, "agent:reviewer", res)
    s.proposal = proposal
    audit = proposal.analyst_audit
    trace.analyst_audit = audit.model_dump()
    trace.proposals.append({"actor": "agent:reviewer", "final_mode": "structured", "proposal": proposal.model_dump()})
    for _ in audit.rejected_claims:
        s.ctx.event("reviewer_rejection")
    trace.step("agent:reviewer", "structured review", "evidence pack + raw tool results + policy",
               f"proposal: {proposal.decision_type}; audit: {len(audit.issues_found)} issues, "
               f"{len(audit.rejected_claims)} rejected claims", ms=res.latency_ms, tokens=res.usage)


NODES = {"analyst": _analyst, "gate": _gate, "policy_engine": _policy_engine, "reviewer": _reviewer}


@traceable("staged_agent")
def run_staged(ctx: RunContext, trace, llm):
    s = StagedState(ctx.request_id, ctx)
    trace.analyst_stop_reason = None
    while True:
        node, reason = supervisor(s)
        trace.step("code:supervisor", "route", f"step {s.steps}", node, route_reason=reason)
        if node == "finalize":
            trace.stop_reason, trace.final_mode = "completed", "structured"
            return _finalize(s, trace)
        if node == "fallback":
            return _fallback(s, trace, reason)
        try:
            NODES[node](s, trace, llm)
        except LLMUnavailable as exc:
            trace.error = f"{type(exc).__name__}: {exc}"
            trace.llm_error_kind = exc.kind
            s.error = f"{node} llm_unavailable"
        s.steps += 1


def _finalize(s: StagedState, trace):
    """D9 finalize: guardrails.assemble(policy, proposal); the gate and engine already ran as nodes."""
    decision, report = guardrails.assemble(s.policy, s.proposal, s.ctx)
    counts: dict[str, int] = {}
    for e in s.ctx.events:
        counts[e["event"]] = counts.get(e["event"], 0) + 1
    corrections = {k: v for k, v in counts.items() if k in {
        "code_restored_approval", "code_restored_flag", "llm_role_dropped", "llm_flag_dropped", "llm_added_review",
        "llm_decision_overridden", "ungrounded_evidence_removed", "output_guardrail_triggered"}}
    trace.step("code:guardrails", "merge + validate + ground", f"proposal: {s.proposal.decision_type}",
               f"final: {report['decision_type']}; corrections: {corrections or 'none'}")
    return decision, {**report, "policy": s.policy}


def _fallback(s: StagedState, trace, reason: str):
    """Rules-only (T12), keeping stage-1 evidence items that pass the grounding check."""
    if reason == "step limit reached":
        trace.stop_reason = "step_limit"
    elif s.error and s.error.endswith("llm_unavailable"):
        trace.stop_reason = "llm_unavailable"
    else:
        trace.stop_reason = f"stage_failed:{s.error}"
    trace.final_mode = "fallback"
    trace.error = trace.error or reason
    extra = s.evidence_pack.evidence if s.evidence_pack is not None else None
    return fallback.rules_only(s.ctx, trace, llm_failed=True, extra_evidence=extra)
