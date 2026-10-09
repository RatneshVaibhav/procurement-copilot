"""OpenAI-compatible LLM client for Groq or Gemini (T7, D1–D4).

- One SDK client per provider, `max_retries=0`: our loop owns retries so waits are counted.
- Process-wide throttle (LLM_MIN_INTERVAL_SECONDS between call starts) and header-aware
  token waits (x-ratelimit-remaining-tokens < 2000 → wait for x-ratelimit-reset-tokens).
- 429: honour retry-after (capped), else back off 2, 4, 8, 16 s + jitter → LLMRateLimited.
- 5xx / timeout / connection: same back-off → LLMUnavailable(kind=server|network).
- 401/403/404: LLMUnavailable immediately. LLM_SIMULATE_OUTAGE=1: LLMUnavailable before any call.
- reasoning_effort is sent only when set and dropped for the process after a 400 naming it.
- chat_structured: response_format json_schema (strict only for Groq gpt-oss), no tools,
  one repair call on a validation error, else InvalidOutput.
"""
from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
from dataclasses import dataclass, field

import openai
from pydantic import BaseModel, ValidationError

from src.config import Settings, get_settings
from src.structured import strict_schema
from src.tracing import wrap_openai_client

log = logging.getLogger(__name__)
TOKEN_FLOOR = 2000
BACKOFFS = [2.0, 4.0, 8.0, 16.0]


class LLMUnavailable(Exception):
    """The LLM cannot be used for this run. `kind` separates infra from other causes (D11.3)."""

    def __init__(self, message: str, kind: str = "unavailable"):
        super().__init__(message)
        self.kind = kind

    @property
    def infra(self) -> bool:
        return self.kind in {"rate_limited", "network", "server"}


class LLMRateLimited(LLMUnavailable):
    def __init__(self, message: str):
        super().__init__(message, kind="rate_limited")


class ToolUseFailed(Exception):
    """HTTP 400 tool_use_failed: do not retry the same request (D2.5)."""


class InvalidOutput(Exception):
    """Structured output still invalid after one repair. `result` holds the calls made."""

    def __init__(self, message: str, result: "ChatResult | None" = None):
        super().__init__(message)
        self.result = result


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str
    args: dict | None = None
    parse_error: str | None = None


@dataclass
class ChatResult:
    message: dict
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict = field(default_factory=lambda: {"prompt": 0, "completion": 0, "cached": 0})
    latency_ms: float = 0.0
    wait_ms: float = 0.0
    attempts: int = 1
    calls: int = 1
    finish_reason: str | None = None

    def merged(self, other: "ChatResult") -> "ChatResult":
        usage = {k: self.usage.get(k, 0) + other.usage.get(k, 0) for k in {"prompt", "completion", "cached"}}
        return ChatResult(message=other.message, content=other.content, tool_calls=other.tool_calls, usage=usage,
                          latency_ms=self.latency_ms + other.latency_ms, wait_ms=self.wait_ms + other.wait_ms,
                          attempts=self.attempts + other.attempts, calls=self.calls + other.calls,
                          finish_reason=other.finish_reason)


def parse_tool_calls(raw_calls) -> list[ToolCall]:
    calls = []
    for tc in raw_calls or []:
        name, arguments = tc.function.name, tc.function.arguments or "{}"
        try:
            args = json.loads(arguments)
            error = None if isinstance(args, dict) else "arguments are not a JSON object"
            args = args if isinstance(args, dict) else None
        except json.JSONDecodeError as exc:
            args, error = None, f"invalid JSON arguments: {exc}"
        calls.append(ToolCall(id=tc.id, name=name, arguments=arguments, args=args, parse_error=error))
    return calls


def assistant_message(content: str | None, tool_calls: list[ToolCall]) -> dict:
    message: dict = {"role": "assistant", "content": content or ""}
    if tool_calls:
        message["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in tool_calls
        ]
    return message


def structured_with_repair(complete, messages: list[dict], schema_model: type[BaseModel], name: str):
    """Shared by LLMClient and tests' ScriptedLLM. `complete(messages, schema_model, name)` makes
    one structured request and returns a ChatResult whose content is the JSON text."""
    result = complete(messages, schema_model, name)
    try:
        return schema_model.model_validate_json(result.content or ""), result
    except ValidationError as exc:
        errors = _errors(exc)
    repair = list(messages) + [
        {"role": "assistant", "content": result.content or ""},
        {"role": "user", "content": f"Your JSON failed validation:\n{errors}\nReturn the corrected JSON object only."},
    ]
    second = complete(repair, schema_model, name)
    total = result.merged(second)
    try:
        return schema_model.model_validate_json(second.content or ""), total
    except ValidationError as exc:
        raise InvalidOutput(f"{name}: still invalid after one repair: {_errors(exc)}", total) from exc


def _errors(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:10])


def _duration_seconds(value: str | None) -> float | None:
    """Parse Groq reset values such as '3.127s', '1m26.4s', '250ms', '2h1m'."""
    if not value:
        return None
    total, matched = 0.0, False
    for amount, unit in re.findall(r"([\d.]+)(ms|h|m|s)", value):
        matched = True
        total += float(amount) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    if matched:
        return total
    try:
        return float(value)
    except ValueError:
        return None


class _ProcessState:
    lock = threading.Lock()
    last_start = 0.0
    not_before = 0.0  # header-aware wait for the token window
    drop_reasoning_effort = False
    warned = False


class LLMClient:
    def __init__(self, settings: Settings | None = None, sdk_client=None):
        self.settings = settings or get_settings()
        self._sdk = sdk_client

    @property
    def provider(self) -> str:
        return self.settings.llm_provider

    @property
    def model(self) -> str:
        return self.settings.model_name

    def _client(self):
        if self._sdk is None:
            s = self.settings
            self._sdk = wrap_openai_client(openai.OpenAI(
                base_url=s.llm_base_url, api_key=s.llm_api_key, max_retries=0, timeout=s.llm_timeout_seconds))
        return self._sdk

    # ------------------------------------------------------------ public API
    def chat(self, messages: list[dict], tools: list[dict] | None = None, tool_choice: str = "auto") -> ChatResult:
        params: dict = {"messages": messages}
        if tools:
            params["tools"] = tools
            params["tool_choice"] = tool_choice
        return self._call(params)

    def chat_structured(self, messages: list[dict], schema_model: type[BaseModel], name: str):
        return structured_with_repair(self._complete_structured, messages, schema_model, name)

    # ------------------------------------------------------------ internals
    def _complete_structured(self, messages, schema_model, name) -> ChatResult:
        s = self.settings
        strict = s.llm_provider == "groq" and s.model_name.startswith("openai/gpt-oss")
        params = {
            "messages": messages,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": name, "strict": strict, "schema": strict_schema(schema_model)}},
        }
        try:
            return self._call(params)
        except _JsonValidateFailed as exc:  # provider-side schema failure: hand back the text for repair
            return ChatResult(message={"role": "assistant", "content": exc.text}, content=exc.text,
                              wait_ms=exc.wait_s * 1000, attempts=exc.attempts, calls=1)

    def _check_available(self) -> None:
        s = self.settings
        if s.llm_simulate_outage:
            raise LLMUnavailable("simulated LLM outage (LLM_SIMULATE_OUTAGE=1)", kind="simulated")
        if not s.llm_configured or not s.llm_base_url:
            raise LLMUnavailable(f"LLM not configured for provider {s.llm_provider!r}", kind="not_configured")

    def _wait_turn(self) -> float:
        """Throttle + header-aware wait. Returns seconds waited."""
        with _ProcessState.lock:
            now = time.monotonic()
            start_at = max(now, _ProcessState.last_start + self.settings.llm_min_interval_seconds, _ProcessState.not_before)
            _ProcessState.last_start = start_at
        waited = max(0.0, start_at - now)
        if waited:
            time.sleep(waited)
        return waited

    def _note_headers(self, headers) -> None:
        try:
            remaining = int(float(headers.get("x-ratelimit-remaining-tokens", "")))
        except (TypeError, ValueError):
            return
        if remaining < TOKEN_FLOOR:
            reset = _duration_seconds(headers.get("x-ratelimit-reset-tokens")) or 0.0
            with _ProcessState.lock:
                _ProcessState.not_before = max(_ProcessState.not_before, time.monotonic() + reset)

    def _call(self, params: dict) -> ChatResult:
        self._check_available()
        s = self.settings
        wait_s, attempts = 0.0, 0
        while True:
            attempts += 1
            body = {"model": s.model_name, "temperature": s.llm_temperature, **params}
            if s.llm_reasoning_effort and not _ProcessState.drop_reasoning_effort:
                body["reasoning_effort"] = s.llm_reasoning_effort
            wait_s += self._wait_turn()
            start = time.perf_counter()
            try:
                raw = self._client().chat.completions.with_raw_response.create(**body)
                latency_ms = (time.perf_counter() - start) * 1000
                self._note_headers(raw.headers)
                completion = raw.parse()
                return self._result(completion, latency_ms, wait_s * 1000, attempts)
            except openai.RateLimitError as exc:
                log.warning("429 from %s (attempt %d): %s", s.llm_provider, attempts, _short(exc))
                delay = self._retry_after(exc)
                if attempts > s.llm_max_retries or (delay is not None and delay > s.llm_retry_after_cap_seconds):
                    raise LLMRateLimited(f"rate limited after {attempts} attempt(s): {_short(exc)}") from exc
                delay = delay if delay is not None else self._backoff(attempts)
            except openai.BadRequestError as exc:
                text = str(exc)
                code = getattr(exc, "code", None) or ""
                # Branch on the error code first: the body may echo model output ("failed_generation")
                # that happens to contain any word, including "reasoning".
                if code == "tool_use_failed" or (not code and "tool_use_failed" in text):
                    raise ToolUseFailed(_short(exc)) from exc
                if code == "json_validate_failed" or (not code and "json_validate_failed" in text):
                    raise _JsonValidateFailed(_failed_generation(exc), wait_s, attempts) from exc
                if "reasoning_effort" in body and _names_reasoning_effort(exc):
                    _ProcessState.drop_reasoning_effort = True
                    if not _ProcessState.warned:
                        log.warning("Provider rejected reasoning_effort; dropping it for this process.")
                        _ProcessState.warned = True
                    continue
                raise LLMUnavailable(f"bad request: {_short(exc)}", kind="bad_request") from exc
            except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
                raise LLMUnavailable(f"authentication failed: {_short(exc)}", kind="auth") from exc
            except openai.NotFoundError as exc:
                raise LLMUnavailable(f"model or endpoint not found: {_short(exc)}", kind="not_found") from exc
            except openai.APITimeoutError as exc:
                if attempts > s.llm_max_retries:
                    raise LLMUnavailable(f"timeout after {attempts} attempt(s)", kind="network") from exc
                delay = self._backoff(attempts)
            except openai.APIConnectionError as exc:
                if attempts > s.llm_max_retries:
                    raise LLMUnavailable(f"connection error after {attempts} attempt(s)", kind="network") from exc
                delay = self._backoff(attempts)
            except openai.APIStatusError as exc:
                if exc.status_code >= 500 and attempts <= s.llm_max_retries:
                    delay = self._backoff(attempts)
                elif exc.status_code >= 500:
                    raise LLMUnavailable(f"provider error {exc.status_code} after {attempts} attempt(s)", kind="server") from exc
                else:
                    raise LLMUnavailable(f"provider error {exc.status_code}: {_short(exc)}", kind="bad_request") from exc
            time.sleep(delay)
            wait_s += delay

    @staticmethod
    def _retry_after(exc) -> float | None:
        try:
            value = exc.response.headers.get("retry-after")
        except AttributeError:
            return None
        return _duration_seconds(value)

    @staticmethod
    def _backoff(attempt: int) -> float:
        return BACKOFFS[min(attempt - 1, len(BACKOFFS) - 1)] + random.uniform(0, 0.5)

    @staticmethod
    def _result(completion, latency_ms: float, wait_ms: float, attempts: int) -> ChatResult:
        choice = completion.choices[0]
        msg = choice.message
        calls = parse_tool_calls(getattr(msg, "tool_calls", None))
        usage = {"prompt": 0, "completion": 0, "cached": 0}
        if completion.usage is not None:
            usage["prompt"] = completion.usage.prompt_tokens or 0
            usage["completion"] = completion.usage.completion_tokens or 0
            details = getattr(completion.usage, "prompt_tokens_details", None)
            usage["cached"] = (getattr(details, "cached_tokens", None) or 0) if details is not None else 0
        return ChatResult(message=assistant_message(msg.content, calls), content=msg.content, tool_calls=calls,
                          usage=usage, latency_ms=latency_ms, wait_ms=wait_ms, attempts=attempts, calls=1,
                          finish_reason=choice.finish_reason)


class _JsonValidateFailed(Exception):
    def __init__(self, text: str, wait_s: float = 0.0, attempts: int = 1):
        super().__init__("json_validate_failed")
        self.text, self.wait_s, self.attempts = text, wait_s, attempts


def _names_reasoning_effort(exc) -> bool:
    """True only when the 400 itself is about the reasoning_effort parameter (D1)."""
    if getattr(exc, "param", None) == "reasoning_effort":
        return True
    body = exc.body if isinstance(getattr(exc, "body", None), dict) else {}
    err = body.get("error") if isinstance(body.get("error"), dict) else body
    message = str(err.get("message", "")) if isinstance(err, dict) else ""
    return "reasoning_effort" in message or (not body and "reasoning_effort" in str(exc))


def _failed_generation(exc) -> str:
    try:
        return exc.body.get("failed_generation") or exc.body.get("error", {}).get("failed_generation") or ""
    except AttributeError:
        return ""


def _short(exc) -> str:
    return " ".join(str(exc).split())[:300]
