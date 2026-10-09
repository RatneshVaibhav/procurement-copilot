from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)

from mock_api import launcher  # noqa: E402
from src.config import get_settings  # noqa: E402


def start(cmd: list[str]) -> subprocess.Popen:
    return subprocess.Popen(cmd, cwd=ROOT)


def _handle_termination(signum: int, frame: object) -> None:
    """Route SIGTERM through normal cleanup (useful for IDE/terminal stop actions)."""
    raise KeyboardInterrupt


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_termination)
    procs: list[subprocess.Popen] = []
    try:
        settings = get_settings()
        api_url = settings.vendor_risk_base_url
        if not launcher.is_local(api_url):
            print(f"WARNING: VENDOR_RISK_BASE_URL={api_url} is not local; the mock still starts on 127.0.0.1.")
        api_port = launcher.port_of(api_url)
        print(f"Starting vendor-risk API on http://127.0.0.1:{api_port} ...")
        api_proc = launcher.start(api_port)
        procs.append(api_proc)
        launcher.wait_for_api(f"http://127.0.0.1:{api_port}/health", api_proc)
        print("Vendor-risk API is ready.")

        app_port = settings.app_port
        print(f"Starting web app on http://127.0.0.1:{app_port} ...")
        app_proc = start(
            [sys.executable, "-m", "uvicorn", "webapp.main:app", "--host", "127.0.0.1", "--port", str(app_port)]
        )
        procs.append(app_proc)
        launcher.wait_for_api(f"http://127.0.0.1:{app_port}/", app_proc, label="Web app")
        print(f"\n  Web app:         http://127.0.0.1:{app_port}")
        print(f"  Vendor-risk API: http://127.0.0.1:{api_port}")
        print("\nPress Ctrl+C to stop.")

        while True:
            time.sleep(1)
            for proc in procs:
                if proc.poll() is not None:
                    raise RuntimeError(f"A local process exited with code {proc.returncode}")
    except KeyboardInterrupt:
        print("\nStopping local services ...")
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
