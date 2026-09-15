"""Health, coverage counts, limitations, source registry, ingestion runs and data quality."""

import json
from datetime import date

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from manakmarg import __version__
from manakmarg.core import paths
from manakmarg.db import schema
from manakmarg.ingest.sources import REGISTRY
from manakmarg.reasoning import groq

from ..deps import get_conn, get_state, get_today

router = APIRouter(tags=["meta"])

LIMITATIONS = [
    {
        "key": "standards_snapshot",
        "en": "Standards metadata comes from BIS exports generated on 12 Sep 2026; standard texts are not collected — look them up on the BIS standards portal.",
        "hi": "मानकों का मेटाडेटा 12 सितंबर 2026 को बने BIS निर्यात से है; मानकों के पाठ एकत्र नहीं किए जाते — उन्हें BIS मानक पोर्टल पर देखें।",
    },
    {
        "key": "classification_partial",
        "en": "Ministry classification covers 18 ministry exports only; department and group classification is not available.",
        "hi": "मंत्रालय वर्गीकरण केवल 18 मंत्रालय निर्यातों तक सीमित है; विभाग और समूह वर्गीकरण उपलब्ध नहीं है।",
    },
    {
        "key": "jewellers_captcha",
        "en": "Registered jewellers cannot be listed because the official report requires a CAPTCHA.",
        "hi": "पंजीकृत ज्वैलर्स की सूची नहीं दी जा सकती क्योंकि आधिकारिक रिपोर्ट के लिए CAPTCHA आवश्यक है।",
    },
    {
        "key": "lab_scope_selected",
        "en": "IS-wise laboratory scope, Product Manual text and QCO text are indexed for selected product families; others link to official pages.",
        "hi": "IS-वार लैब दायरा, उत्पाद मैनुअल और QCO का पाठ चुने हुए उत्पाद परिवारों के लिए अनुक्रमित है; अन्य के लिए आधिकारिक पृष्ठों के लिंक दिए गए हैं।",
    },
    {
        "key": "snapshots",
        "en": "Web listings are snapshots with retrieval dates; legal status must be verified against the latest Gazette and BIS notifications.",
        "hi": "वेब सूचियाँ प्राप्ति तिथि वाले स्नैपशॉट हैं; कानूनी स्थिति की पुष्टि नवीनतम राजपत्र और BIS अधिसूचनाओं से करें।",
    },
    {
        "key": "gap_scope",
        "en": "Gap analysis only compares against requirements contained in documents you upload; it never generates requirements.",
        "hi": "गैप विश्लेषण केवल आपके अपलोड किए दस्तावेज़ों में दी गई आवश्यकताओं से तुलना करता है; यह स्वयं आवश्यकताएँ नहीं बनाता।",
    },
]

_COUNTS = {
    "standards": ("standard", True),
    "coverage_listings": ("scheme_coverage", True),
    "orders": ("regulatory_order", True),
    "guidelines": ("product_guideline", True),
    "laboratories": ("laboratory", True),
    "lab_list_entries": ("lab_list_entry", True),
    "lab_scope_rows": ("lab_scope", True),
    "ahcs": ("ahc", True),
    "ahc_status_events": ("ahc_status_event", True),
    "hallmarking_districts": ("hallmarking_district", True),
    "faqs": ("faq", True),
    "documents": ("document", True),
    "document_chunks": ("document_chunk", False),
    "hsn_codes": ("hsn_code", True),
}


@router.get("/health")
def health(response: Response, conn: Connection = Depends(get_conn)) -> dict:
    """200 when the processed data is loaded; 503 when the database is empty or missing its tables."""
    try:
        listings = conn.execute(sa.select(sa.func.count()).select_from(schema.scheme_coverage)).scalar()
    except SQLAlchemyError:
        listings = 0
    ready = bool(listings)
    if not ready:
        response.status_code = 503
    return {"status": "ok" if ready else "no_data", "version": __version__, "data_ready": ready}


@router.get("/meta")
def meta(conn: Connection = Depends(get_conn), today: date = Depends(get_today)) -> dict:
    counts = {}
    for key, (table_name, current_only) in _COUNTS.items():
        table = schema.metadata.tables[table_name]
        query = sa.select(sa.func.count()).select_from(table)
        if current_only:
            query = query.where(table.c.is_current.is_(True))
        counts[key] = conn.execute(query).scalar()
    guidelines = schema.product_guideline
    counts["manuals_parsed"] = conn.execute(
        sa.select(sa.func.count()).select_from(guidelines).where(guidelines.c.parse_status == "parsed")
    ).scalar()
    runs = schema.ingestion_run
    latest = dict(
        conn.execute(
            sa.select(runs.c.source_id, sa.func.max(runs.c.completed_at)).where(runs.c.status == "success").group_by(runs.c.source_id)
        ).all()
    )

    def day(source_id: str) -> str | None:
        return latest.get(source_id, None) and latest[source_id][:10]

    from manakmarg.refresh import log as refresh_log
    from manakmarg.refresh import scheduler as refresh_scheduler

    settings = get_state().settings
    scheduled = refresh_scheduler.ACTIVE_SCHEDULER
    refresh = refresh_log.read_status(settings.refresh_dir, scheduled.next_run_at if scheduled else None)
    return {
        "version": __version__,
        "llm_enabled": settings.llm_enabled,
        "checked_on": today.isoformat(),
        "counts": counts,
        # Weekly BIS standards refresh: active dataset version and the latest run (no admin controls).
        "data_refresh": refresh,
        "as_of": {
            "standards_export": (refresh["activated_at"] or "")[:10] or "2026-09-12",
            "compulsory_listings": day("bis_scheme_i_page"),
            "laboratories": day("lims_recognised_labs"),
            "ahc_list": day("manak_ahc_list"),
            "hallmarking_districts": REGISTRY["bis_hm_districts_phasewise"].as_of_label,
        },
        "limitations": LIMITATIONS,
        "upload_ttl_minutes": settings.upload_ttl_minutes,
        "voice_enabled": settings.voice_enabled,
        "voice_max_mb": settings.voice_max_mb,
        # Counts only (since process start): no query text, audio or credentials.
        "ai_usage": groq.usage_snapshot(),
    }


@router.get("/sources")
def sources(conn: Connection = Depends(get_conn)) -> dict:
    runs = schema.ingestion_run
    latest_ids = sa.select(sa.func.max(runs.c.run_id)).group_by(runs.c.source_id)
    latest = {
        row["source_id"]: dict(row)
        for row in conn.execute(sa.select(runs).where(runs.c.run_id.in_(latest_ids))).mappings()
    }
    items = []
    for row in conn.execute(sa.select(schema.source).order_by(schema.source.c.source_id)).mappings():
        run = latest.get(row["source_id"])
        items.append(
            {
                **dict(row),
                "latest_run": None
                if run is None
                else {key: run[key] for key in ("run_id", "status", "started_at", "completed_at", "records_seen", "inserted", "updated", "unchanged", "retired", "rejected")},
            }
        )
    return {"items": items}


@router.get("/ingestion-runs")
def ingestion_runs(limit: int = Query(100, ge=1, le=500), conn: Connection = Depends(get_conn)) -> dict:
    runs = schema.ingestion_run
    rows = conn.execute(sa.select(runs).order_by(runs.c.run_id.desc()).limit(limit)).mappings().all()
    items = []
    for row in rows:
        item = dict(row)
        errors = json.loads(item.pop("errors_json") or "[]")
        item["error_count"] = len(errors)
        item["errors"] = errors[:5]
        items.append(item)
    return {"items": items}


@router.get("/data-quality")
def data_quality() -> dict:
    path = paths.MANIFEST_DIR / "data_quality.json"
    if not path.exists():
        raise HTTPException(404, "The data-quality report has not been generated yet (run `python -m manakmarg validate`).")
    return json.loads(path.read_text(encoding="utf-8"))
