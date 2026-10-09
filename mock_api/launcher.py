"""Start and health-check the mock vendor-risk API (used by run_local and the eval runners)."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def is_local(base_url: str) -> bool:
    return (urlparse(base_url).hostname or "") in LOCAL_HOSTS


def port_of(base_url: str, default: int = 8001) -> int:
    return urlparse(base_url).port or default


def is_healthy(base_url: str, timeout: float = 0.5) -> bool:
    try:
        return requests.get(f"{base_url.rstrip('/')}/health", timeout=timeout).ok
    except requests.RequestException:
        return False


def start(port: int, env: dict | None = None, quiet: bool = False) -> subprocess.Popen:
    cmd = [sys.executable, "-m", "uvicorn", "mock_api.app:app", "--host", "127.0.0.1", "--port", str(port)]
    if quiet:
        cmd += ["--log-level", "warning"]
    return subprocess.Popen(cmd, cwd=ROOT, env=env)


def wait_for_api(url: str, proc: subprocess.Popen, timeout_seconds: float = 10.0, label: str = "Vendor-risk API") -> None:
    """Wait until the service is reachable or fail with a useful message."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"{label} exited during startup with code {proc.returncode}. "
                "Check the terminal output above (a port conflict is a common cause)."
            )
        try:
            if requests.get(url, timeout=0.5).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"{label} did not become ready within {timeout_seconds:.0f}s: {url}")


def stop(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
