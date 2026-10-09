"""Web app. Phase 0 placeholder: the full JSON API and UI arrive in Phase 6 (T17)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

app = FastAPI(title="Procurement Request Copilot")


@app.get("/", response_class=PlainTextResponse)
def index() -> str:
    return "ok"
