"""Architecture A: one bounded agent (D7 card A).

Goal: one grounded AgentProposal for one request. Instructions: SYSTEM_SINGLE.
Context: request id + reference date; tool results. Tools: 6 + submit_recommendation.
State: RunContext. Stop: submitted / max_turns=6 / loop_detected / invalid_output / llm_unavailable.
On failure: finalizer → rules-only fallback.
"""
from __future__ import annotations

from src import fallback, guardrails, prompts, tools
from src.agents.loop import run_tool_loop
from src.schemas import AgentProposal
from src.tools import RunContext
from src.tracing import traceable

MAX_TURNS = 6


@traceable("single_agent")
def run_single(ctx: RunContext, trace, llm):
    user = prompts.USER_ANALYSE.format(request_id=ctx.request_id, reference_date=ctx.reference_date.isoformat())
    loop = run_tool_loop(llm, prompts.SYSTEM_SINGLE, user, "single", "submit_recommendation", AgentProposal,
                         MAX_TURNS, ctx, trace, finalizer_model=AgentProposal, gate_tools=tools.GATE_SINGLE)
    trace.stop_reason = loop.stop_reason
    if loop.proposal is None:
        trace.final_mode = "fallback"
        trace.error = f"no valid proposal (stop_reason={loop.stop_reason})"
        return fallback.rules_only(ctx, trace, llm_failed=True)
    trace.final_mode = loop.final_mode
    trace.proposals.append({"actor": "agent:single", "final_mode": loop.final_mode, "proposal": loop.proposal.model_dump()})
    return finish(ctx, trace, loop.proposal, tools.GATE_SINGLE)


def finish(ctx: RunContext, trace, proposal, gate: list[str]):
    """Completeness gate (T6.3) → policy engine → guardrails (T11)."""
    filled = tools.run_gate(ctx, gate)
    trace.step("code:gate", "completeness gate", f"required: {', '.join(gate)}", f"filled: {', '.join(filled) or 'none'}")
    policy = tools.policy_for(ctx)
    if policy is None:
        raise RuntimeError("policy engine produced no result")
    decision, report = guardrails.assemble(policy, proposal, ctx)
    counts = {}
    for e in ctx.events:
        counts[e["event"]] = counts.get(e["event"], 0) + 1
    corrections = {k: v for k, v in counts.items() if k in {
        "code_restored_approval", "code_restored_flag", "llm_role_dropped", "llm_flag_dropped", "llm_added_review",
        "llm_decision_overridden", "ungrounded_evidence_removed", "output_guardrail_triggered"}}
    trace.step("code:guardrails", "merge + validate + ground", f"proposal: {proposal.decision_type}",
               f"final: {report['decision_type']}; corrections: {corrections or 'none'}")
    return decision, {**report, "policy": policy}
