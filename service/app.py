"""The web API.   Start it with:   uvicorn service.app:app --port 8000

POST /insight   {"member_id": "M0042"}  ->  the insight
GET  /health
Status codes: 200 ok, 404 unknown member, 422 invalid input, 503 database unavailable.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import db
from .core import generate_insight
from .llm import get_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("insight")
app = FastAPI(title="insight service", version="2.0")
client = get_client()


class InsightRequest(BaseModel):
    # [0-9] and not \d, because \d also accepts Arabic-Indic digits. FastAPI answers 422 on any other input.
    member_id: str = Field(pattern=r"^M[0-9]{4}$", examples=["M0042"])


class InsightResponse(BaseModel):
    member_id: str
    insight: str
    evidence: list[str]
    actions: list[str]
    tone: str
    safety_flag: bool
    meta: dict


@app.get("/health")
def health():
    return {"status": "ok", "backend": client.name, "model": getattr(client, "model", None)}


@app.post("/insight", response_model=InsightResponse)
def insight(req: InsightRequest):
    try:
        return generate_insight(req.member_id, client)
    except db.MemberNotFound:
        raise HTTPException(status_code=404, detail="no snapshot for this member")
    except db.DatabaseUnavailable as e:
        log.error("database unavailable: %s", e)                        # the reason goes to the log, not to the caller
        raise HTTPException(status_code=503, detail="database unavailable")
