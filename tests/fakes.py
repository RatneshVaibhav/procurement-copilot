"""ScriptedLLM (D12): a fake LLM driven by a list of scripted responses. No network.

Script items:
- {"tool_calls": [("name", {args} | "raw json"), ...], "content": optional text}
- {"content": "text only"}
- {"structured": {...} | "raw text"}            (for chat_structured)
- an Exception instance                          (raised from that call)
"""
from __future__ import annotations

import copy
import json
import os

from src.llm_client import ChatResult, ToolCall, assistant_message, structured_with_repair

# Unit tests never call a real LLM: blank every provider key. Settings are read at call
# time, so this holds even if src/__init__.py already loaded .env.
for _key in ("GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "LANGSMITH_API_KEY", "LANGSMITH_TRACING"):
    os.environ[_key] = ""


class ScriptedLLM:
    provider = "scripted"
    model = "scripted-llm"

    def __init__(self, script: list):
        self.script = list(script)
        self.calls: list[dict] = []

    def _next(self):
        if not self.script:
            raise AssertionError("ScriptedLLM ran out of scripted responses")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def chat(self, messages, tools=None, tool_choice="auto") -> ChatResult:
        self.calls.append({"method": "chat", "messages": copy.deepcopy(messages),
                           "tools": [t["function"]["name"] for t in tools or []], "tool_choice": tool_choice})
        item = self._next()
        calls = []
        for i, (name, args) in enumerate(item.get("tool_calls", [])):
            raw = args if isinstance(args, str) else json.dumps(args)
            try:
                parsed = json.loads(raw)
                error = None if isinstance(parsed, dict) else "arguments are not a JSON object"
                parsed = parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError as exc:
                parsed, error = None, f"invalid JSON arguments: {exc}"
            calls.append(ToolCall(id=f"call_{len(self.calls)}_{i}", name=name, arguments=raw, args=parsed, parse_error=error))
        content = item.get("content")
        return ChatResult(message=assistant_message(content, calls), content=content, tool_calls=calls,
                          usage={"prompt": 100, "completion": 20, "cached": 0}, latency_ms=1.0)

    def chat_structured(self, messages, schema_model, name):
        return structured_with_repair(self._complete_structured, messages, schema_model, name)

    def _complete_structured(self, messages, schema_model, name) -> ChatResult:
        self.calls.append({"method": "chat_structured", "messages": copy.deepcopy(messages), "schema": name})
        item = self._next()
        payload = item["structured"]
        content = payload if isinstance(payload, str) else json.dumps(payload)
        return ChatResult(message={"role": "assistant", "content": content}, content=content,
                          usage={"prompt": 100, "completion": 20, "cached": 0}, latency_ms=1.0)


def call(name: str, **args) -> tuple[str, dict]:
    return name, args


def tools_turn(*calls) -> dict:
    return {"tool_calls": list(calls)}
