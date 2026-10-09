"""LLM provider smoke test (Phase 0). Standalone: uses the raw openai SDK, not src.llm_client.

Checks: model list, one tool-call round trip, one JSON-schema structured output,
reasoning_effort acceptance, latency, usage and rate-limit headers.
Exits non-zero with a clear message on any failure.

    python scripts/smoke_llm.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import openai  # noqa: E402
from openai import OpenAI  # noqa: E402

from src.config import get_settings  # noqa: E402

DUMMY_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Returns the weather for a city. Call it when asked about the weather.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "City name"}},
            "required": ["city"],
            "additionalProperties": False,
        },
    },
}

TINY_SCHEMA = {
    "type": "object",
    "properties": {
        "colour": {"type": "string"},
        "count": {"type": "integer"},
        "note": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["colour", "count", "note"],
    "additionalProperties": False,
}


def fail(message: str) -> None:
    print(f"\n[FAIL] {message}")
    raise SystemExit(1)


def show_call(raw, latency_ms: float) -> object:
    completion = raw.parse()
    usage = completion.usage
    cached = None
    details = getattr(usage, "prompt_tokens_details", None) if usage else None
    if details is not None:
        cached = getattr(details, "cached_tokens", None)
    print(f"  latency: {latency_ms:.0f} ms")
    if usage:
        print(
            f"  usage: prompt={usage.prompt_tokens} completion={usage.completion_tokens} "
            f"total={usage.total_tokens} cached={cached}"
        )
    limits = {k: v for k, v in raw.headers.items() if k.lower().startswith("x-ratelimit") or k.lower() == "retry-after"}
    print(f"  rate-limit headers: {json.dumps(limits, indent=None) if limits else '(none returned)'}")
    return completion


def create(client: OpenAI, settings, effort: str | None, **kwargs):
    params = dict(model=settings.model_name, temperature=settings.llm_temperature, **kwargs)
    if effort:
        params["reasoning_effort"] = effort
    start = time.perf_counter()
    raw = client.chat.completions.with_raw_response.create(**params)
    return raw, (time.perf_counter() - start) * 1000


def main() -> None:
    s = get_settings()
    print("LLM smoke test")
    print(f"  provider: {s.llm_provider}")
    print(f"  base_url: {s.llm_base_url}")
    print(f"  model:    {s.model_name}")
    print(f"  reasoning_effort: {s.llm_reasoning_effort or '(not sent)'}")
    if not s.llm_api_key:
        fail(f"No API key for provider '{s.llm_provider}'. Set it in .env (see .env.example).")

    client = OpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key, max_retries=0, timeout=s.llm_timeout_seconds)

    print("\n1. Model list")
    try:
        ids = sorted(m.id for m in client.models.list())
    except openai.AuthenticationError as exc:
        fail(f"Authentication failed (check the key): {exc}")
    except openai.APIError as exc:
        fail(f"Could not list models: {type(exc).__name__}: {exc}")
    print(f"  {len(ids)} models available")
    candidates = {s.model_name, f"models/{s.model_name}"}
    if candidates & set(ids):
        print(f"  OK: {s.model_name} is listed")
    else:
        print(f"  WARNING: resolved model ID {s.model_name!r} is not in the provider's model list.")

    effort = s.llm_reasoning_effort
    print("\n2. Tool-call round trip (tool_choice=auto)")
    messages = [{"role": "user", "content": "What is the weather in Pune? Use the get_weather tool."}]
    try:
        raw, ms = create(client, s, effort, messages=messages, tools=[DUMMY_TOOL], tool_choice="auto")
    except openai.BadRequestError as exc:
        if effort and "reasoning" in str(exc).lower():
            print(f"  reasoning_effort rejected ({exc}); retrying without it")
            effort = None
            try:
                raw, ms = create(client, s, effort, messages=messages, tools=[DUMMY_TOOL], tool_choice="auto")
            except openai.APIError as exc2:
                fail(f"Tool-call request failed without reasoning_effort: {type(exc2).__name__}: {exc2}")
        else:
            fail(f"Tool-call request rejected: {exc}")
    except openai.APIError as exc:
        fail(f"Tool-call request failed: {type(exc).__name__}: {exc}")
    completion = show_call(raw, ms)
    calls = completion.choices[0].message.tool_calls or []
    if not calls:
        fail(f"The model did not call the tool. Reply: {completion.choices[0].message.content!r}")
    try:
        args = json.loads(calls[0].function.arguments or "{}")
    except json.JSONDecodeError:
        fail(f"Tool-call arguments are not valid JSON: {calls[0].function.arguments!r}")
    print(f"  tool call: {calls[0].function.name}({args})")
    print(f"  reasoning_effort accepted: {'yes' if effort else 'not sent'}")

    strict = s.llm_provider == "groq" and s.model_name.startswith("openai/gpt-oss")
    print(f"\n3. Structured output (response_format json_schema, strict={strict})")
    try:
        raw, ms = create(
            client,
            s,
            effort,
            messages=[{"role": "user", "content": "Return colour=blue, count=3 and note=null as JSON."}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "smoke", "strict": strict, "schema": TINY_SCHEMA},
            },
        )
    except openai.APIError as exc:
        fail(f"Structured-output request failed: {type(exc).__name__}: {exc}")
    completion = show_call(raw, ms)
    content = completion.choices[0].message.content or ""
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        fail(f"Structured output is not valid JSON: {content!r}")
    if set(parsed) != {"colour", "count", "note"}:
        fail(f"Structured output has the wrong keys: {parsed}")
    print(f"  parsed: {parsed}")

    print("\nSMOKE TEST PASSED")


if __name__ == "__main__":
    main()
