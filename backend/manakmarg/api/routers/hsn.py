"""HSN lookup (local, no external AI): classification candidates from the supplied HSN master, shown verbatim."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.engine import Connection

from manakmarg.ingest.sources import REGISTRY
from manakmarg.search.hsn import SOURCE_ID, search_hsn

from ..deps import get_conn
from ..serialize import plain

router = APIRouter(prefix="/hsn", tags=["hsn"])

DISCLAIMER = {
    "en": "HSN results are classification candidates from the supplied HSN master. They are not a GST, customs or BIS determination — verify with the competent authority before use.",
    "hi": "HSN परिणाम दिए गए HSN मास्टर से वर्गीकरण के संभावित मिलान हैं। ये GST, सीमा शुल्क या BIS का निर्णय नहीं हैं — उपयोग से पहले सक्षम प्राधिकरण से पुष्टि करें।",
}


def _source() -> dict:
    definition = REGISTRY[SOURCE_ID]
    return {"source_id": SOURCE_ID, "name": definition.name, "authority": definition.authority, "as_of": definition.as_of_label}


@router.get("/search")
def hsn_search(q: str = Query(..., min_length=1, max_length=120), limit: int = Query(8, ge=1, le=25), conn: Connection = Depends(get_conn)) -> dict:
    return {**plain(search_hsn(conn, q, limit=limit)), "source": _source(), "disclaimer": DISCLAIMER}


@router.get("/code/{code}")
def hsn_code(code: str, conn: Connection = Depends(get_conn)) -> dict:
    compact = code.replace(" ", "").replace(".", "")
    if not compact.isdigit() or not 2 <= len(compact) <= 8:
        raise HTTPException(422, "An HSN code has 2 to 8 digits.")
    result = search_hsn(conn, compact, limit=25)
    if not result.matches:
        raise HTTPException(404, f"HSN code {compact} is not in the supplied HSN master.")
    return {**plain(result), "source": _source(), "disclaimer": DISCLAIMER}
