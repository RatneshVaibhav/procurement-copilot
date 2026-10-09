"""Shared test helpers. No network: the mock vendor-risk API runs in-process."""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

from fastapi.testclient import TestClient

from mock_api.app import app as mock_app

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = json.loads((ROOT / "evals" / "golden_cases.json").read_text(encoding="utf-8"))
DOWN_URL = "http://127.0.0.1:9"  # closed port: connection refused

_client = TestClient(mock_app)


def _fake_get(url, timeout=None, **kwargs):
    parsed = urlparse(url)
    if f"{parsed.scheme}://{parsed.netloc}" == DOWN_URL:
        import requests
        raise requests.ConnectionError("connection refused (simulated closed port)")
    return _client.get(parsed.path)


@contextlib.contextmanager
def in_process_vendor_api(extra_data_dir: str | None = "evals/fixtures", down: bool = False):
    """Route src.vendor_client HTTP calls to the in-process mock; optionally simulate an outage."""
    env = {"EXTRA_DATA_DIR": extra_data_dir or "", "VENDOR_RISK_BASE_URL": DOWN_URL if down else "http://127.0.0.1:8001"}
    with mock.patch.dict(os.environ, env), mock.patch("src.vendor_client.requests.get", side_effect=_fake_get), \
            mock.patch("src.vendor_client.RETRY_BACKOFF_SECONDS", 0):
        yield


def fixed_vendor_fetch(outcome: str, record: dict | None = None, status_code: int | None = None):
    """A vendor_fetch for RunContext that returns a canned classified result."""
    def fetch(name: str) -> dict:
        rec = None if record is None else {"vendor_name": name, **record}
        return {"outcome": outcome, "status_code": status_code or {"ok": 200, "not_found": 404}.get(outcome, 503),
                "record": rec, "error": None if outcome == "ok" else "simulated", "attempts": 1,
                "duration_ms": 0.0, "endpoint": f"GET /vendor-risk/{name}"}
    return fetch
