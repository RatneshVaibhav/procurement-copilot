"""Step trace recorder (T13, D10) and an optional LangSmith shim.

The local JSON trace is the graded evidence. LangSmith is used only when
LANGSMITH_TRACING=true, LANGSMITH_API_KEY is set and `langsmith` imports;
otherwise every hook here is a no-op. Init failures are logged and ignored.
"""
from __future__ import annotations

import functools
import logging
import re
import time
import uuid
from datetime import datetime, timezone

from src.config import get_settings

log = logging.getLogger(__name__)
SUMMARY_MAX = 300
ACTORS = {
    "agent:single", "agent:analyst", "agent:reviewer", "code:gate", "code:policy_engine",
    "code:guardrails", "code:supervisor", "code:finalizer", "code:fallback",
}


def _clip(text: object) -> str:
    text = " ".join(str(text if text is not None else "").split())
    return text if len(text) <= SUMMARY_MAX else text[: SUMMARY_MAX - 1] + "…"


class Trace:
    def __init__(self, request_id: str, architecture: str, mode: str, provider: str | None = None,
                 model: str | None = None, reference_date: str | None = None):
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(request_id))[:40] or "request"
        self.run_id = f"{safe_id}-{re.sub(r'[^a-z]', '', str(architecture))[:10]}-{uuid.uuid4().hex[:8]}"
        self.request_id = request_id
        self.architecture = architecture
        self.mode = mode
        self.provider = provider
        self.model = model
        self.reference_date = reference_date
        self.created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")  # log timestamp only
        self.steps: list[dict] = []
        self.stop_reason: str | None = None
        self.final_mode: str | None = None
        self.error: str | None = None
        self.llm_error_kind: str | None = None
        self.analyst_stop_reason: str | None = None
        self.proposals: list[dict] = []
        self.analyst_audit: dict | None = None
        self.evidence_pack: dict | None = None
        self.llm_calls_detail: list[dict] = []
        self.guardrails: dict = {}
        self._start = time.perf_counter()

    def step(self, actor: str, action: str, summary_in: object = "", summary_out: object = "",
             route_reason: str | None = None, ms: float | None = None, tokens: dict | None = None) -> None:
        if actor not in ACTORS:
            raise ValueError(f"unknown trace actor {actor!r}")
        self.steps.append({
            "n": len(self.steps) + 1,
            "actor": actor,
            "action": action,
            "summary_in": _clip(summary_in),
            "summary_out": _clip(summary_out),
            "route_reason": route_reason,
            "ms": None if ms is None else round(ms, 1),
            "tokens": tokens,
        })

    def record_llm_call(self, actor: str, result) -> None:
        """Record one completed chat request (ChatResult-like: latency_ms, wait_ms, attempts, usage)."""
        self.llm_calls_detail.append({
            "actor": actor,
            "latency_ms": round(getattr(result, "latency_ms", 0.0), 1),
            "wait_ms": round(getattr(result, "wait_ms", 0.0), 1),
            "attempts": getattr(result, "attempts", 1),
            "usage": getattr(result, "usage", None),
        })

    def to_dict(self, ctx=None, policy=None) -> dict:
        total_ms = (time.perf_counter() - self._start) * 1000
        wait_ms = sum(c["wait_ms"] for c in self.llm_calls_detail)
        llm_ms = sum(c["latency_ms"] for c in self.llm_calls_detail)
        tool_log = list(ctx.tool_log) if ctx is not None else []
        events = list(ctx.events) if ctx is not None else []
        counts: dict[str, int] = {}
        for e in events:
            counts[e["event"]] = counts.get(e["event"], 0) + 1
        return {
            "run_id": self.run_id,
            "request_id": self.request_id,
            "architecture": self.architecture,
            "mode": self.mode,
            "provider": self.provider,
            "model": self.model,
            "reference_date": self.reference_date,
            "created_at": self.created_at,
            "latency_total_ms": round(total_ms, 1),
            "llm_wait_ms": round(wait_ms, 1),
            "latency_active_ms": round(total_ms - wait_ms, 1),
            "llm_ms": round(llm_ms, 1),
            "tool_ms": round(sum(t["duration_ms"] for t in tool_log), 1),
            "llm_calls": ctx.llm_calls if ctx is not None else 0,
            "tool_calls": ctx.tool_calls if ctx is not None else 0,
            "tokens": dict(ctx.tokens) if ctx is not None else {"prompt": 0, "completion": 0, "cached": 0},
            "steps": self.steps,
            "stop_reason": self.stop_reason,
            "final_mode": self.final_mode,
            "analyst_stop_reason": self.analyst_stop_reason,
            "repeated_tool_calls": counts.get("repeated_tool_call", 0),
            "tool_rejected": counts.get("tool_rejected", 0),
            "event_counts": counts,
            "events": events,
            "tool_log": tool_log,
            "llm_call_log": self.llm_calls_detail,
            "proposals": self.proposals,
            "evidence_pack": self.evidence_pack,
            "analyst_audit": self.analyst_audit,
            "guardrails": self.guardrails,
            "policy": policy.model_dump() if policy is not None else None,
            "error": self.error,
            "llm_error_kind": self.llm_error_kind,
        }


# ---------------------------------------------------------------- optional LangSmith (D10)
def langsmith_enabled() -> bool:
    s = get_settings()
    if not (s.langsmith_tracing and s.langsmith_api_key):
        return False
    try:
        import langsmith  # noqa: F401
    except Exception:  # pragma: no cover - optional dependency
        return False
    return True


def traceable(name: str):
    """Decorator: LangSmith @traceable when enabled at call time, otherwise a plain call."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            target = fn
            if langsmith_enabled():
                try:  # only the wrapping is guarded; the call itself runs once, outside
                    from langsmith import traceable as ls_traceable
                    target = ls_traceable(name=name)(fn)
                except Exception as exc:  # never let tracing break a run
                    log.warning("LangSmith tracing disabled for this call: %s", exc)
            return target(*args, **kwargs)
        return wrapper
    return decorator


def wrap_openai_client(client):
    if not langsmith_enabled():
        return client
    try:
        from langsmith.wrappers import wrap_openai
        return wrap_openai(client)
    except Exception as exc:  # pragma: no cover
        log.warning("LangSmith wrap_openai failed; continuing without it: %s", exc)
        return client
