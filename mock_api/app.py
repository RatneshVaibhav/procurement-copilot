from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException

ROOT = Path(__file__).resolve().parents[1]

app = FastAPI(title="FDE Mock Vendor Risk API", version="1.1")


def _norm_key(value: str) -> str:
    return " ".join(str(value).split()).casefold()


def _extra_data_dir() -> Path | None:
    raw = os.environ.get("EXTRA_DATA_DIR", "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def load_data() -> dict:
    """Load per request so EXTRA_DATA_DIR changes between eval cases take effect."""
    data = json.loads((ROOT / "data" / "vendor_risk.json").read_text(encoding="utf-8"))
    extra = _extra_data_dir()
    if extra is not None and (extra / "vendor_risk.json").is_file():
        data.update(json.loads((extra / "vendor_risk.json").read_text(encoding="utf-8")))
    return data


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/vendor-risk/{vendor_name:path}")
def vendor_risk(vendor_name: str) -> dict:
    # The path is already percent-decoded once by the server; do not unquote again.
    key = _norm_key(vendor_name)
    match = next(((name, rec) for name, rec in load_data().items() if _norm_key(name) == key), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"No vendor-risk record for '{vendor_name}'")
    canonical, record = match
    if record.get("force_error"):
        raise HTTPException(status_code=503, detail=record.get("error_message", "Vendor-risk service unavailable"))
    return {"vendor_name": canonical, **record}
