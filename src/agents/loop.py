"""Shared bounded tool loop (D8) with the structured-output finalizer (D2.4).

Stop conditions: submitted | max_turns | loop_detected | invalid_output | tool_use_failed.
LLMUnavailable propagates to the caller, which falls back to rules only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from pydantic import BaseModel, ValidationError

from src import prompts, tools
from src.llm_client import ChatResult, InvalidOutput, ToolUseFailed
from src.structured import strict_schema
from src.tools import RunContext

SUBMIT_DESCRIPTIONS = {
    "submit_recommendation": prompts.SUBMIT_RECOMMENDATION_DESCRIPTION,
    "submit_evidence_pack": prompts.SUBMIT_EVIDENCE_PACK_DESCRIPTION,
}
LOOP_REPEAT_LIMIT = 2


@dataclass
class LoopResult:
    proposal: BaseModel | None
    stop_reason: str
    final_mode: str  # tool_call | finalizer | fallback
    turns: int


@lru_cache(maxsize=None)
def _submit_definition(name: str, model: type[BaseModel]) -> dict:
    return {"type": "function", "function": {"name": name, "description": SUBMIT_DESCRIPTIONS[name],
                                             "parameters": strict_schema(model)}}


def tool_list(actor: str, submit_tool: str, model: type[BaseModel]) -> list[dict]:
    """Static, fixed-order tool list for an agent (D3)."""
    return tools.tool_definitions(actor) + [_submit_definition(submit_tool, model)]


def record_llm(ctx: RunContext, trace, actor: str, res: ChatResult) -> None:
    ctx.llm_calls += res.calls
    for key in ("prompt", "completion", "cached"):
        ctx.tokens[key] += res.usage.get(key, 0)
    trace.record_llm_call(actor, res)


def _describe(call) -> str:
    args = call.args or {}
    inner = ", ".join(f"{v}" for v in args.values() if not isinstance(v, (dict, list))) if call.name.startswith(("get_", "check_", "search_", "evaluate_", "lookup_")) else ""
    return f"{call.name}({inner})"


def run_tool_loop(llm, system: str, user: str, actor: str, submit_tool: str, submit_model: type[BaseModel],
                  max_turns: int, ctx: RunContext, trace, finalizer_model: type[BaseModel] | None = None,
                  gate_tools: list[str] | None = None) -> LoopResult:
    trace_actor = f"agent:{actor}"
    tool_defs = tool_list(actor, submit_tool, submit_model)
    messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    repairs_left, repeat_turns = 1, 0
    stop_reason = "max_turns"
    turn = 0
    for turn in range(1, max_turns + 1):
        try:
            res = llm.chat(messages, tools=tool_defs, tool_choice="auto")
        except ToolUseFailed as exc:
            ctx.event("tool_use_failed", actor=actor, error=str(exc))
            trace.step(trace_actor, f"llm turn {turn}", f"{len(messages)} messages", "provider rejected the tool call (tool_use_failed)")
            stop_reason = "tool_use_failed"
            break
        record_llm(ctx, trace, trace_actor, res)
        messages.append(res.message)
        if not res.tool_calls:
            trace.step(trace_actor, f"llm turn {turn}", f"{len(messages) - 1} messages", "text reply, no tool call",
                       ms=res.latency_ms, tokens=res.usage)
            messages.append({"role": "user", "content": prompts.NUDGE_TEXT_ONLY})
            continue
        all_repeats, invalid_stop, outcome = True, False, []
        for call in res.tool_calls:
            if call.name == submit_tool:
                try:
                    if call.args is None:
                        raise ValueError(call.parse_error or "arguments missing")
                    proposal = submit_model.model_validate(call.args)
                except (ValidationError, ValueError) as exc:
                    errors = _errors(exc)
                    if repairs_left:
                        repairs_left -= 1
                        all_repeats = False
                        ctx.event("invalid_submission_repair", actor=actor, errors=errors)
                        messages.append({"role": "tool", "tool_call_id": call.id,
                                         "content": prompts.SUBMIT_INVALID.format(tool=submit_tool, errors=errors)})
                        outcome.append(f"{submit_tool} invalid → repair requested")
                        continue
                    ctx.event("invalid_output", actor=actor, errors=errors)
                    outcome.append(f"{submit_tool} invalid again")
                    stop_reason, invalid_stop = "invalid_output", True
                    break
                trace.step(trace_actor, f"llm turn {turn}", f"{len(messages) - 1} messages",
                           "; ".join(outcome + [f"{submit_tool}: valid"]), ms=res.latency_ms, tokens=res.usage)
                return LoopResult(proposal, "submitted", "tool_call", turn)
            args = call.args if call.args is not None else {}
            known = call.name in tools.TOOLS and call.name in tools.ALLOWLISTS.get(actor, [])
            if known and not tools.is_cached(call.name, args, ctx):
                all_repeats = False
            result = tools.execute(call.name, args, ctx, actor=actor, initiator="agent")
            messages.append({"role": "tool", "tool_call_id": call.id, "content": tools.tool_message_content(result)})
            status = "rejected" if not known else ("error" if result.get("status") == "error" else "ok")
            outcome.append(f"{_describe(call)} → {status}")
        trace.step(trace_actor, f"llm turn {turn}", f"{len(messages)} messages", "; ".join(outcome),
                   ms=res.latency_ms, tokens=res.usage)
        if invalid_stop:
            break
        if all_repeats:
            repeat_turns += 1
            if repeat_turns >= LOOP_REPEAT_LIMIT:
                ctx.event("loop_detected", actor=actor)
                stop_reason = "loop_detected"
                break
        else:
            repeat_turns = 0
    if finalizer_model is None:
        return LoopResult(None, stop_reason, "fallback", turn)
    proposal = finalize(llm, ctx, trace, finalizer_model, gate_tools or [])
    return LoopResult(proposal, stop_reason, "finalizer" if proposal is not None else "fallback", turn)


def finalize(llm, ctx: RunContext, trace, model: type[BaseModel], gate_tools: list[str]) -> BaseModel | None:
    """D2.4: a fresh, compact message set with the run's tool results; never the tool-laden conversation."""
    filled = tools.run_gate(ctx, gate_tools)  # the finalizer must see the required evidence
    if filled:
        trace.step("code:gate", "completeness gate (before finalizer)", ", ".join(gate_tools), f"filled: {', '.join(filled)}")
    results = [{"tool": r["tool"], "result": r["result"]} for r in ctx.results]
    user = prompts.FINALIZER_USER.format(
        request_id=ctx.request_id, reference_date=ctx.reference_date.isoformat(),
        tool_results=tools.UNTRUSTED_PREFIX + json.dumps(results, ensure_ascii=False, separators=(",", ":"), default=str))
    messages = [{"role": "system", "content": prompts.SYSTEM_FINALIZER}, {"role": "user", "content": user}]
    try:
        proposal, res = llm.chat_structured(messages, model, "submit_recommendation")
    except InvalidOutput as exc:
        if exc.result is not None:
            record_llm(ctx, trace, "code:finalizer", exc.result)
        ctx.event("finalizer_invalid", error=str(exc)[:300])
        trace.step("code:finalizer", "structured finalizer", "tool results", "invalid after one repair → fallback")
        return None
    record_llm(ctx, trace, "code:finalizer", res)
    ctx.event("finalizer_used")
    trace.step("code:finalizer", "structured finalizer", "tool results", f"proposal: {proposal.decision_type}",
               ms=res.latency_ms, tokens=res.usage)
    return proposal


def _errors(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:10])
    return str(exc)[:300]
