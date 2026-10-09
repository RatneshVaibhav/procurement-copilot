from __future__ import annotations

import time
from urllib.parse import quote

import requests

from src.config import get_settings

TIMEOUT_SECONDS = 3.0
RETRY_BACKOFF_SECONDS = 0.5


def _url(vendor_name: str) -> str:
    return f"{get_settings().vendor_risk_base_url}/vendor-risk/{quote(vendor_name, safe='')}"


def get_vendor_risk(vendor_name: str, timeout_seconds: float = TIMEOUT_SECONDS) -> dict:
    """Low-level API client kept for backwards compatibility. Raises on any HTTP error."""
    response = requests.get(_url(vendor_name), timeout=timeout_seconds)
    response.raise_for_status()
    return response.json()


def get_vendor_risk_classified(vendor_name: str, timeout_seconds: float = TIMEOUT_SECONDS) -> dict:
    """Query the vendor-risk API and classify the outcome (T6.4). Never raises.

    Returns {"outcome": "ok" | "not_found" | "unavailable", "status_code", "record",
    "error", "attempts", "duration_ms", "endpoint"}.
    404 is "not_found" (no retry). 5xx, timeout and connection errors are retried
    once after 0.5 s, then reported as "unavailable".
    """
    url = _url(vendor_name)
    endpoint = f"GET /vendor-risk/{vendor_name}"
    start = time.perf_counter()
    attempts = 0
    status_code: int | None = None
    error: str | None = None
    for attempt in range(2):
        attempts = attempt + 1
        try:
            response = requests.get(url, timeout=timeout_seconds)
        except requests.Timeout:
            status_code, error = None, f"timeout after {timeout_seconds:g} s"
        except requests.RequestException as exc:
            status_code, error = None, f"connection error: {type(exc).__name__}"
        else:
            status_code = response.status_code
            if status_code == 404:
                return _result("not_found", status_code, None, "no vendor-risk record", attempts, start, endpoint)
            if 200 <= status_code < 300:
                try:
                    record = response.json()
                except ValueError:
                    return _result("unavailable", status_code, None, "invalid JSON from vendor-risk API", attempts, start, endpoint)
                return _result("ok", status_code, record, None, attempts, start, endpoint)
            error = _detail(response)
            if status_code < 500:
                # 4xx other than 404: not retried, and never treated as favorable.
                return _result("unavailable", status_code, None, error, attempts, start, endpoint)
        if attempt == 0:
            time.sleep(RETRY_BACKOFF_SECONDS)
    return _result("unavailable", status_code, None, error, attempts, start, endpoint)


def _detail(response: requests.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    return f"HTTP {response.status_code}" + (f": {detail}" if detail else "")


def _result(outcome, status_code, record, error, attempts, start, endpoint) -> dict:
    return {
        "outcome": outcome,
        "status_code": status_code,
        "record": record,
        "error": error,
        "attempts": attempts,
        "duration_ms": round((time.perf_counter() - start) * 1000, 1),
        "endpoint": endpoint,
    }
