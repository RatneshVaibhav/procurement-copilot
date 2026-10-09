"""Request normalisation (T4.2). The raw dict is kept for display and the injection scan."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

MISSING_DATA_LEVELS = {"", "unknown"}


@dataclass
class NormalizedRequest:
    request_id: str
    requester_id: str | None
    product_name: str | None
    vendor_name: str | None
    category: str | None
    annual_cost_usd: float | None
    user_count: int | None
    business_justification: str | None
    data_access_level: str | None
    requested_integrations: list[str] | None
    urgency: str | None
    notes: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(value: object) -> float | None:
    """A finite number, or a string that parses as one; booleans are not numbers."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    return number if math.isfinite(number) else None


def _cost(value: object, notes: list[str]) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    number = _number(value)
    if number is None or number < 0:
        notes.append("annual cost (invalid value)")
        return None
    return number


def _users(value: object) -> int | None:
    number = _number(value)
    if number is None or number <= 0 or number != int(number):
        return None
    return int(number)


def _integrations(value: object) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else None
    if isinstance(value, (list, tuple)):
        return [s for s in (str(v).strip() for v in value if v is not None) if s]
    return None


def normalize_request(raw: dict) -> NormalizedRequest:
    notes: list[str] = []
    level = _text(raw.get("data_access_level"))
    level = level.casefold() if level else None
    if level in MISSING_DATA_LEVELS:
        level = None
    return NormalizedRequest(
        request_id=str(raw.get("request_id") or "").strip(),
        requester_id=_text(raw.get("requester_id")),
        product_name=_text(raw.get("product_name")),
        vendor_name=_text(raw.get("vendor_name")),
        category=_text(raw.get("category")),
        annual_cost_usd=_cost(raw.get("annual_cost_usd"), notes),
        user_count=_users(raw.get("user_count")),
        business_justification=_text(raw.get("business_justification")),
        data_access_level=level,
        requested_integrations=_integrations(raw.get("requested_integrations")),
        urgency=_text(raw.get("urgency")),
        notes=notes,
        raw=dict(raw),
    )
