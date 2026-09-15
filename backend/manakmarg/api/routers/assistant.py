"""Assistant endpoint: rule-based understanding, deterministic services and an evidence-cited EN/HI answer."""

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.engine import Connection

from manakmarg.reasoning.assistant import answer

from ..deps import get_conn, get_state, get_today
from ..serialize import with_evidence

router = APIRouter(tags=["assistant"])


class AssistantQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    lang: str = Field("en", pattern="^(en|hi)$")


@router.post("/assistant/query")
def assistant_query(body: AssistantQuery, conn: Connection = Depends(get_conn), today: date = Depends(get_today)) -> dict:
    state = get_state()
    result = answer(conn, body.query, lang=body.lang, today=today, vectors=state.vectors, gazetteer=state.gazetteer(conn), settings=state.settings)
    return with_evidence(result)
