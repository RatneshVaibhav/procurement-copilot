"""Deterministic prompt-injection scanner (R10). A hit only adds a flag and evidence;
it never changes any other rule output."""
from __future__ import annotations

import re

EXCERPT_MAX = 120

PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore\s+(all\s+|any\s+|the\s+|previous\s+|prior\s+|above\s+)*(procurement\s+)?(rules|instructions|polic(y|ies))",
        r"disregard\s+(all\s+|any\s+|the\s+)*(rules|instructions|polic(y|ies))",
        r"\b(treat|mark|consider|report)\s+(this|it|the\s+request|this\s+vendor|the\s+vendor)\b[^.]{0,40}\b(approved|pre-?approved|low\s+risk|cfo[- ]approved)",
        r"\b(pre-?approved|cfo[- ]approved|already\s+approved)\b",
        r"\b(auto-?)?approve\s+(it|this|the\s+request)\b",
        r"\b(skip|bypass|override)\s+(all\s+|the\s+|any\s+)*(reviews?|approvals?|controls|checks|polic(y|ies))",
        r"\b(system|assistant)\s*(note|prompt|message|instructions?)\s*:",
        r"\byou\s+are\s+now\b|\bnew\s+instructions\b|reveal\s+(the\s+)?(system\s+prompt|api\s+key|secrets?)",
        r"\bno\s+(security\s+|legal\s+|privacy\s+)?review\s+(is\s+)?(required|needed)\b",
    ]
]


def first_match(text: str) -> re.Match | None:
    matches = [m for m in (p.search(text) for p in PATTERNS) if m]
    return min(matches, key=lambda m: m.start()) if matches else None


def matches_injection(text: str | None) -> bool:
    return bool(text) and first_match(text) is not None


def excerpt(text: str, match: re.Match, limit: int = EXCERPT_MAX) -> str:
    """The whole field if short enough, else a window around the first hit."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    flat_match = first_match(flat) or match
    start = max(0, flat_match.start() - 30)
    window = flat[start : start + limit]
    return window


def iter_strings(value: object, path: str):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from iter_strings(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            yield from iter_strings(item, f"{path}[{i}]")


def scan(value: object, path: str = "") -> list[dict]:
    """Scan every string inside value. Returns [{field, excerpt}] (one hit per field)."""
    hits = []
    for field, text in iter_strings(value, path):
        match = first_match(text)
        if match:
            hits.append({"field": field, "excerpt": excerpt(text, match)})
    return hits
