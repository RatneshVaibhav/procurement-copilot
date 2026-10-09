"""Data loaders (T4.1).

Each loader also appends rows from the same-named file in EXTRA_DATA_DIR when that
variable is set (evals use evals/fixtures). CSVs are read as strings with blanks
kept as "" so missing values are never silently turned into NaN.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RUNTIME_DIR = ROOT / "runtime"
SUBMITTED_REQUESTS_PATH = RUNTIME_DIR / "submitted_requests.json"


def norm_key(value: object) -> str:
    """Name key for matching: collapse whitespace, casefold."""
    return " ".join(str(value).split()).casefold()


def _extra_dir() -> Path | None:
    raw = get_settings().extra_data_dir
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _read_csv(name: str) -> pd.DataFrame:
    frames = [pd.read_csv(DATA_DIR / name, dtype=str, keep_default_na=False)]
    extra = _extra_dir()
    if extra is not None and (extra / name).is_file():
        frames.append(pd.read_csv(extra / name, dtype=str, keep_default_na=False))
    return pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]


def _read_json_list(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def records(df: pd.DataFrame) -> list[dict]:
    return df.to_dict(orient="records")


def load_employees() -> pd.DataFrame:
    return _read_csv("employees.csv")


def load_budgets() -> pd.DataFrame:
    return _read_csv("department_budgets.csv")


def load_software_catalog() -> pd.DataFrame:
    return _read_csv("software_catalog.csv")


def load_vendors() -> pd.DataFrame:
    return _read_csv("vendors.csv")


def load_purchase_history() -> pd.DataFrame:
    return _read_csv("purchase_history.csv")


def load_requests() -> list[dict]:
    """Official requests plus EXTRA_DATA_DIR fixtures (not runtime submissions)."""
    rows = _read_json_list(DATA_DIR / "requests.json")
    extra = _extra_dir()
    if extra is not None:
        rows += _read_json_list(extra / "requests.json")
    return rows


def load_submitted_requests() -> list[dict]:
    return _read_json_list(SUBMITTED_REQUESTS_PATH)


def all_requests() -> list[dict]:
    return load_requests() + load_submitted_requests()


def get_request(request_id: str) -> dict:
    """Search data/requests.json, then extra fixtures, then runtime submissions."""
    for request in all_requests():
        if request.get("request_id") == request_id:
            return request
    raise KeyError(f"Unknown request_id: {request_id}")


def find_vendor(name: object) -> dict | None:
    if name is None or not str(name).strip():
        return None
    key = norm_key(name)
    return next((v for v in records(load_vendors()) if norm_key(v["vendor_name"]) == key), None)


def find_employee(employee_id: object) -> dict | None:
    if employee_id is None or not str(employee_id).strip():
        return None
    key = norm_key(employee_id)
    return next((e for e in records(load_employees()) if norm_key(e["employee_id"]) == key), None)


def find_budget(department: str | None) -> dict | None:
    if not department:
        return None
    key = norm_key(department)
    return next((b for b in records(load_budgets()) if norm_key(b["department"]) == key), None)


def load_policy_text() -> str:
    return (DATA_DIR / "procurement_policy.md").read_text(encoding="utf-8")
