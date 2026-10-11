"""Settings (read at call time) and the policy reference date (T3, D1).

Evals change environment variables between cases, so nothing here is cached
except values parsed from the policy files, which never change during a run.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
POLICY_PATH = DATA_DIR / "procurement_policy.md"
DATA_README_PATH = DATA_DIR / "README.md"

log = logging.getLogger(__name__)

EXPECTED_POLICY_VERSION = "2026.09"

# T3 regex, then (D-07.1) a second regex matched to data/README.md's wording.
_REFERENCE_DATE_PATTERNS = [
    re.compile(r"Data snapshot / evaluation reference date:\*\*\s*(\d{4}-\d{2}-\d{2})"),
    re.compile(r"Reference date for date-based policy checks:\s*(\d{4}-\d{2}-\d{2})"),
]
_POLICY_VERSION_PATTERN = re.compile(r"Policy version:\*\*\s*([\d.]+)")

# D1 provider table.
PROVIDERS: dict[str, dict] = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_envs": ["GROQ_API_KEY"],
        "default_model": "openai/gpt-oss-20b",
        "default_min_interval": 2.5,
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_envs": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "default_model": "gemini-3.5-flash-lite",  # the evaluated model (D-23, D-24)
        "default_min_interval": 6.0,
    },
}


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None else value.strip()


def _float(name: str, default: float) -> float:
    raw = _env(name)
    try:
        return float(raw) if raw else default
    except ValueError:
        log.warning("Invalid %s=%r; using %s", name, raw, default)
        return default


def _int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        log.warning("Invalid %s=%r; using %s", name, raw, default)
        return default


def _truthy(raw: str) -> bool:
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    vendor_risk_base_url: str
    app_port: int
    llm_provider: str
    llm_base_url: str
    llm_api_key: str
    model_name: str
    llm_temperature: float
    llm_reasoning_effort: str | None
    llm_timeout_seconds: float
    llm_max_retries: int
    llm_retry_after_cap_seconds: float
    llm_min_interval_seconds: float
    llm_simulate_outage: bool
    langsmith_tracing: bool
    langsmith_api_key: str
    langsmith_project: str
    eval_api_port: int
    extra_data_dir: str | None

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key)


def get_settings() -> Settings:
    """Read every setting from the environment now (never cached)."""
    provider = _env("LLM_PROVIDER", "gemini").casefold() or "gemini"  # default = evaluated config (D-24)
    if provider in PROVIDERS:
        spec = PROVIDERS[provider]
        api_key = next((_env(k) for k in spec["key_envs"] if _env(k)), "")
    else:
        # Conservative: an unknown provider leaves the LLM unconfigured (rules-only fallback).
        log.warning("Unknown LLM_PROVIDER=%r; the LLM is treated as unavailable", provider)
        spec = {"base_url": "", "default_model": "", "default_min_interval": 2.5}
        api_key = ""
    effort = _env("LLM_REASONING_EFFORT").casefold()
    extra = _env("EXTRA_DATA_DIR")
    return Settings(
        vendor_risk_base_url=(_env("VENDOR_RISK_BASE_URL") or "http://127.0.0.1:8001").rstrip("/"),
        app_port=_int("APP_PORT", 8000),
        llm_provider=provider,
        llm_base_url=spec["base_url"],
        llm_api_key=api_key,
        model_name=_env("MODEL_NAME") or spec["default_model"],
        llm_temperature=_float("LLM_TEMPERATURE", 0.0),
        llm_reasoning_effort=effort or None,
        llm_timeout_seconds=_float("LLM_TIMEOUT_SECONDS", 60.0),
        llm_max_retries=_int("LLM_MAX_RETRIES", 4),
        llm_retry_after_cap_seconds=_float("LLM_RETRY_AFTER_CAP_SECONDS", 60.0),
        llm_min_interval_seconds=_float("LLM_MIN_INTERVAL_SECONDS", spec["default_min_interval"]),
        llm_simulate_outage=_truthy(_env("LLM_SIMULATE_OUTAGE")),
        langsmith_tracing=_truthy(_env("LANGSMITH_TRACING")),
        langsmith_api_key=_env("LANGSMITH_API_KEY"),
        langsmith_project=_env("LANGSMITH_PROJECT", "procurement-copilot") or "procurement-copilot",
        eval_api_port=_int("EVAL_API_PORT", 8011),
        extra_data_dir=extra or None,
    )


def parse_reference_date(*texts: str) -> date:
    """First date matched by any pattern, trying the texts in order."""
    for text in texts:
        for pattern in _REFERENCE_DATE_PATTERNS:
            match = pattern.search(text or "")
            if match:
                return date.fromisoformat(match.group(1))
    raise RuntimeError(
        "Could not parse the reference date from data/procurement_policy.md or data/README.md. "
        "Policy checks never fall back to today's date."
    )


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


@lru_cache(maxsize=1)
def get_reference_date() -> date:
    return parse_reference_date(_read(POLICY_PATH), _read(DATA_README_PATH))


@lru_cache(maxsize=1)
def get_policy_version() -> str | None:
    match = _POLICY_VERSION_PATTERN.search(_read(POLICY_PATH))
    version = match.group(1) if match else None
    if version != EXPECTED_POLICY_VERSION:
        log.warning(
            "Policy version is %r, expected %s: the thresholds in the policy engine may be stale.",
            version,
            EXPECTED_POLICY_VERSION,
        )
    return version


def __getattr__(name: str):
    """Lazy module attributes REFERENCE_DATE and POLICY_VERSION (T3 names)."""
    if name == "REFERENCE_DATE":
        return get_reference_date()
    if name == "POLICY_VERSION":
        return get_policy_version()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def apply_provider(provider: str) -> None:
    """Select a provider for this process (D-17). A MODEL_NAME that belongs to the other
    provider is cleared (with a warning) so the provider default is used instead of
    sending, say, a Groq model ID to Gemini."""
    os.environ["LLM_PROVIDER"] = provider
    model = _env("MODEL_NAME")
    if model and (model.startswith("gemini") != (provider == "gemini")):
        log.warning("MODEL_NAME=%r does not belong to provider %r; using the provider default instead.", model, provider)
        print(f"WARNING: MODEL_NAME={model!r} does not belong to {provider}; using {PROVIDERS[provider]['default_model']}.")
        os.environ["MODEL_NAME"] = ""
