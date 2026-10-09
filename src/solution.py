from __future__ import annotations

import logging

from src import data_access as da
from src import fallback
from src.config import get_reference_date, get_settings
from src.contracts import Architecture, ProcurementDecision
from src.tools import RunContext
from src.tracing import Trace, traceable

log = logging.getLogger(__name__)
ARCHITECTURES = ("single", "staged")
MODES = ("llm", "rules_only")


def handle_request(request_id: str, architecture: Architecture = "single") -> ProcurementDecision:
    """Assessment adapter. Always returns a valid ProcurementDecision."""
    decision, _ = handle_request_with_trace(request_id, architecture)
    return decision


@traceable("handle_request_with_trace")
def handle_request_with_trace(request_id: str, architecture: Architecture = "single", mode: str = "llm",
                              llm=None) -> tuple[ProcurementDecision, dict]:
    """Run one request. mode="llm" uses the chosen architecture; mode="rules_only" is the
    workflow baseline (T12). `llm` is injected in tests (ScriptedLLM). Never raises."""
    request_id = str(request_id)
    arch = architecture if architecture in ARCHITECTURES else "single"
    mode = mode if mode in MODES else "llm"
    trace, ctx, report = None, None, {}
    try:
        settings = get_settings()
        trace = Trace(request_id, arch, mode, provider=settings.llm_provider, model=settings.model_name,
                      reference_date=get_reference_date().isoformat())
        ctx = RunContext(request_id)
        if arch != architecture:
            ctx.event("unknown_architecture", requested=str(architecture), used=arch)
        try:
            da.get_request(request_id)
        except KeyError:
            trace.stop_reason, trace.final_mode = "unknown_request", "fallback"
            trace.step("code:fallback", "unknown request", request_id, "request_clarification (no record)")
            return fallback.unknown_request_decision(request_id), trace.to_dict(ctx)
        if mode == "rules_only":
            decision, report = fallback.rules_only(ctx, trace, llm_failed=False)
            trace.stop_reason, trace.final_mode = "rules_only", "fallback"
        else:
            decision, report = _run_llm(arch, ctx, trace, llm)
    except Exception as exc:  # never raise to the caller
        log.exception("handle_request failed for %s", request_id)
        trace = trace or Trace(request_id, arch, mode)
        trace.error = f"{type(exc).__name__}: {exc}"
        trace.stop_reason, trace.final_mode = "error", "fallback"
        trace.step("code:fallback", "error", request_id, trace.error)
        decision, report = fallback.error_decision(request_id, type(exc).__name__), {}
    policy = report.pop("policy", None)
    trace.guardrails = report
    return decision, trace.to_dict(ctx, policy)


def _run_llm(arch: str, ctx: RunContext, trace: Trace, llm):
    # Phase 2: the agents do not exist yet, so both architectures use the rules-only
    # fallback and say so with llm_unavailable (D-07.9).
    trace.error = "LLMUnavailable: agents not built yet"
    trace.stop_reason, trace.final_mode = "llm_unavailable", "fallback"
    return fallback.rules_only(ctx, trace, llm_failed=True)
