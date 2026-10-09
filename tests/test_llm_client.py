"""LLM client tests with a fake SDK transport: no network (D12)."""
from __future__ import annotations

import dataclasses
import json
import unittest
from types import SimpleNamespace
from unittest import mock

import httpx2
import openai

from src import llm_client
from src.config import get_settings
from src.llm_client import InvalidOutput, LLMClient, LLMRateLimited, LLMUnavailable, ToolUseFailed
from src.schemas import AnalystAudit

REQ = httpx2.Request("POST", "https://example.invalid/v1/chat/completions")


def completion(content=None, tool_calls=None, usage=(10, 5, 3)):
    msg = SimpleNamespace(content=content, tool_calls=[
        SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=n, arguments=json.dumps(a)))
        for i, (n, a) in enumerate(tool_calls or [])] or None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg, finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1],
                              prompt_tokens_details=SimpleNamespace(cached_tokens=usage[2])))


class FakeSDK:
    """Mimics client.chat.completions.with_raw_response.create(**body)."""

    def __init__(self, script):
        self.script = list(script)
        self.bodies = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(with_raw_response=SimpleNamespace(create=self.create)))

    def create(self, **body):
        self.bodies.append(body)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        headers, comp = item if isinstance(item, tuple) else ({}, item)
        return SimpleNamespace(headers=headers, parse=lambda: comp)


def err(cls, status, headers=None, body=None):
    return cls("err", response=httpx2.Response(status, headers=headers or {}, request=REQ), body=body)


class LLMClientTests(unittest.TestCase):
    def setUp(self):
        st = llm_client._ProcessState
        st.last_start, st.not_before, st.drop_reasoning_effort, st.warned = 0.0, 0.0, False, False
        self.settings = dataclasses.replace(
            get_settings(), llm_provider="groq", llm_base_url="https://example.invalid/v1", llm_api_key="test",
            model_name="openai/gpt-oss-20b", llm_reasoning_effort="low", llm_min_interval_seconds=0.0,
            llm_max_retries=3, llm_retry_after_cap_seconds=60.0, llm_simulate_outage=False)
        self.sleeps = []
        patcher = mock.patch.object(llm_client.time, "sleep", side_effect=self.sleeps.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def client(self, script, **over):
        sdk = FakeSDK(script)
        return LLMClient(dataclasses.replace(self.settings, **over), sdk_client=sdk), sdk

    def test_tool_call_parsed_and_usage_recorded(self):
        c, sdk = self.client([completion(tool_calls=[("check_budget", {"request_id": "R"})])])
        res = c.chat([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])
        self.assertEqual(res.tool_calls[0].name, "check_budget")
        self.assertEqual(res.tool_calls[0].args, {"request_id": "R"})
        self.assertEqual(res.usage, {"prompt": 10, "completion": 5, "cached": 3})
        self.assertEqual(sdk.bodies[0]["reasoning_effort"], "low")
        self.assertEqual(sdk.bodies[0]["tool_choice"], "auto")
        self.assertEqual(sdk.bodies[0]["temperature"], 0.0)

    def test_429_retry_after_is_honoured(self):
        c, _ = self.client([err(openai.RateLimitError, 429, {"retry-after": "7"}), completion(content="ok")])
        res = c.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(res.content, "ok")
        self.assertIn(7.0, self.sleeps)
        self.assertGreaterEqual(res.wait_ms, 7000)
        self.assertEqual(res.attempts, 2)

    def test_429_exhaustion_raises_rate_limited(self):
        c, _ = self.client([err(openai.RateLimitError, 429)] * 4)
        with self.assertRaises(LLMRateLimited) as ctx:
            c.chat([{"role": "user", "content": "hi"}])
        self.assertTrue(ctx.exception.infra)
        self.assertIsInstance(ctx.exception, LLMUnavailable)

    def test_retry_after_above_cap_gives_up(self):
        c, _ = self.client([err(openai.RateLimitError, 429, {"retry-after": "3600"})])
        with self.assertRaises(LLMRateLimited):
            c.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(self.sleeps, [])

    def test_simulated_outage_never_calls_network(self):
        c, sdk = self.client([], llm_simulate_outage=True)
        with self.assertRaises(LLMUnavailable) as ctx:
            c.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(ctx.exception.kind, "simulated")
        self.assertFalse(ctx.exception.infra)
        self.assertEqual(sdk.bodies, [])

    def test_reasoning_effort_dropped_after_400(self):
        bad = openai.BadRequestError("reasoning_effort is not supported", response=httpx2.Response(400, request=REQ),
                                     body={"message": "reasoning_effort is not supported", "param": "reasoning_effort"})
        c, sdk = self.client([bad, completion(content="a"), completion(content="b")])
        c.chat([{"role": "user", "content": "1"}])
        c.chat([{"role": "user", "content": "2"}])
        self.assertIn("reasoning_effort", sdk.bodies[0])
        self.assertNotIn("reasoning_effort", sdk.bodies[1])
        self.assertNotIn("reasoning_effort", sdk.bodies[2])

    def test_auth_error_is_immediate(self):
        c, sdk = self.client([err(openai.AuthenticationError, 401)])
        with self.assertRaises(LLMUnavailable) as ctx:
            c.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(ctx.exception.kind, "auth")
        self.assertEqual(len(sdk.bodies), 1)

    def test_5xx_backs_off_then_succeeds(self):
        c, _ = self.client([err(openai.InternalServerError, 503), completion(content="ok")])
        self.assertEqual(c.chat([{"role": "user", "content": "hi"}]).content, "ok")
        self.assertEqual(len(self.sleeps), 1)
        self.assertGreaterEqual(self.sleeps[0], 2.0)

    def test_connection_error_exhaustion_is_infra(self):
        c, _ = self.client([openai.APIConnectionError(request=REQ)] * 4)
        with self.assertRaises(LLMUnavailable) as ctx:
            c.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(ctx.exception.kind, "network")
        self.assertTrue(ctx.exception.infra)

    def test_tool_use_failed_not_retried(self):
        bad = openai.BadRequestError("tool_use_failed: bad call", response=httpx2.Response(400, request=REQ), body=None)
        c, sdk = self.client([bad])
        with self.assertRaises(ToolUseFailed):
            c.chat([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])
        self.assertEqual(len(sdk.bodies), 1)

    def test_tool_use_failed_body_mentioning_reasoning_is_not_a_reasoning_error(self):
        body = {"error": {"message": "Tool call validation failed", "type": "invalid_request_error",
                          "code": "tool_use_failed", "failed_generation": "my reasoning: call the tool"}}
        bad = openai.BadRequestError("Error code: 400 - " + json.dumps(body),
                                     response=httpx2.Response(400, request=REQ), body=body["error"])
        c, sdk = self.client([bad])
        with self.assertRaises(ToolUseFailed):
            c.chat([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])
        self.assertEqual(len(sdk.bodies), 1)
        self.assertFalse(llm_client._ProcessState.drop_reasoning_effort)

    def test_other_400_is_not_retried_and_keeps_reasoning_effort(self):
        bad = openai.BadRequestError("context too long", response=httpx2.Response(400, request=REQ),
                                     body={"message": "context too long; reasoning budget exceeded"})
        c, sdk = self.client([bad])
        with self.assertRaises(LLMUnavailable) as ctx:
            c.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(ctx.exception.kind, "bad_request")
        self.assertFalse(ctx.exception.infra)
        self.assertFalse(llm_client._ProcessState.drop_reasoning_effort)

    def test_403_and_404_fail_immediately(self):
        for cls, status, kind in [(openai.PermissionDeniedError, 403, "auth"), (openai.NotFoundError, 404, "not_found")]:
            c, sdk = self.client([err(cls, status)])
            with self.assertRaises(LLMUnavailable) as ctx:
                c.chat([{"role": "user", "content": "hi"}])
            self.assertEqual(ctx.exception.kind, kind)
            self.assertEqual(len(sdk.bodies), 1)

    def test_timeout_backs_off_then_succeeds(self):
        c, _ = self.client([openai.APITimeoutError(request=REQ), completion(content="ok")])
        self.assertEqual(c.chat([{"role": "user", "content": "hi"}]).content, "ok")
        self.assertGreaterEqual(self.sleeps[0], 2.0)

    def test_header_aware_wait(self):
        headers = {"x-ratelimit-remaining-tokens": "1500", "x-ratelimit-reset-tokens": "4.5s"}
        c, _ = self.client([(headers, completion(content="a")), completion(content="b")])
        c.chat([{"role": "user", "content": "1"}])
        res = c.chat([{"role": "user", "content": "2"}])
        self.assertTrue(self.sleeps and self.sleeps[0] > 4.0)
        self.assertGreater(res.wait_ms, 4000)

    def test_duration_parsing(self):
        self.assertAlmostEqual(llm_client._duration_seconds("1m26.4s"), 86.4)
        self.assertAlmostEqual(llm_client._duration_seconds("250ms"), 0.25)
        self.assertEqual(llm_client._duration_seconds("12"), 12.0)


class StructuredTests(LLMClientTests.__base__):
    setUp = LLMClientTests.setUp
    client = LLMClientTests.client

    def test_structured_strict_no_tools_and_repair(self):
        good = {"issues_found": [], "rejected_claims": [], "agrees_with_overlap_assessment": True}
        c, sdk = self.client([completion(content='{"issues_found": []}'), completion(content=json.dumps(good))])
        parsed, res = c.chat_structured([{"role": "user", "content": "x"}], AnalystAudit, "audit")
        self.assertTrue(parsed.agrees_with_overlap_assessment)
        self.assertEqual(res.calls, 2)
        body = sdk.bodies[0]
        self.assertNotIn("tools", body)
        self.assertTrue(body["response_format"]["json_schema"]["strict"])
        self.assertIn("failed validation", sdk.bodies[1]["messages"][-1]["content"])

    def test_structured_not_strict_for_gemini(self):
        good = {"issues_found": [], "rejected_claims": [], "agrees_with_overlap_assessment": False}
        c, sdk = self.client([completion(content=json.dumps(good))], llm_provider="gemini", model_name="gemini-2.5-flash")
        c.chat_structured([{"role": "user", "content": "x"}], AnalystAudit, "audit")
        self.assertFalse(sdk.bodies[0]["response_format"]["json_schema"]["strict"])

    def test_invalid_twice_raises_with_call_count(self):
        c, _ = self.client([completion(content="{}"), completion(content="not json")])
        with self.assertRaises(InvalidOutput) as ctx:
            c.chat_structured([{"role": "user", "content": "x"}], AnalystAudit, "audit")
        self.assertEqual(ctx.exception.result.calls, 2)

    def test_provider_json_validate_failed_goes_to_repair(self):
        good = {"issues_found": ["x"], "rejected_claims": [], "agrees_with_overlap_assessment": True}
        bad = openai.BadRequestError("json_validate_failed", response=httpx2.Response(400, request=REQ),
                                     body={"error": {"code": "json_validate_failed", "failed_generation": "{}"}})
        c, _ = self.client([bad, completion(content=json.dumps(good))])
        parsed, res = c.chat_structured([{"role": "user", "content": "x"}], AnalystAudit, "audit")
        self.assertEqual(parsed.issues_found, ["x"])


if __name__ == "__main__":
    unittest.main()
