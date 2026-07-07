"""Real corpus statistics for the product frontend.

Every number here is measured from the live system (database count, Chroma
collection, files on disk, glossary JSON). When a source is unreachable the
value is null and the status says so — the frontend renders an honest
degraded state instead of a made-up number.
"""

import json
import time
from pathlib import Path

from fastapi import APIRouter
from sqlalchemy import text

from agents._singleton import get_sql_agent, get_rag_agent

router = APIRouter()

ROOT = Path(__file__).resolve().parents[2]
PDF_DIR = ROOT / "data" / "pdfs"
GLOSSARY_PATH = ROOT / "config" / "business_glossary.json"

# Mirrors the scraper registry in agents/web_agent.py (scraper_methods).
WEB_RETAILERS = {
    "electronics": ["Newegg", "Goal Zero"],
    "home": ["IKEA"],
    "clothing": ["Taylor Stitch", "Chubbies", "Finisterre"],
    "food": ["Swanson", "NativePath"],
    "sports": ["Campmor"],
}

_CACHE_TTL_S = 300
_cache: dict = {"at": 0.0, "payload": None}


def _transaction_count() -> tuple:
    try:
        session = get_sql_agent().session
        row = session.execute(text("SELECT COUNT(*) FROM sales_transactions")).fetchone()
        session.commit()
        return int(row[0]), "live"
    except Exception:
        return None, "offline"


def _document_stats() -> dict:
    from database.ingestion_pipeline import CORPUS_BASE_DIR, list_corpus_documents

    pdf_count = len(list(PDF_DIR.rglob("*.pdf"))) if PDF_DIR.exists() else None
    categories = {}
    if PDF_DIR.exists():
        for folder in sorted(PDF_DIR.iterdir()):
            if folder.is_dir():
                count = len(list(folder.glob("*.pdf")))
                if count:
                    # "01_financial" → "Financial"
                    label = folder.name.split("_", 1)[-1].replace("_", " ").title()
                    categories[label] = count

    # Business files beyond PDF (data/corpus): glossary, policies, ticket
    # exports, inventory CSVs — counted by format so the UI shows the real mix.
    corpus_by_format: dict = {}
    corpus_count = 0
    for path in list_corpus_documents(CORPUS_BASE_DIR):
        corpus_count += 1
        fmt = path.suffix.lstrip(".").lower()
        corpus_by_format[fmt] = corpus_by_format.get(fmt, 0) + 1
        label = path.parent.name.replace("_", " ").title()
        categories[label] = categories.get(label, 0) + 1

    total = (pdf_count or 0) + corpus_count if pdf_count is not None else None
    try:
        chunks = get_rag_agent().collection.count()
        status = "live"
    except Exception:
        chunks = None
        status = "offline"
    return {
        "pdf_count": pdf_count,
        "business_file_count": corpus_count,
        "business_files_by_format": corpus_by_format,
        "total_documents": total,
        "chunks": chunks,
        "categories": categories,
        "status": status,
    }


def _glossary_entries() -> int | None:
    try:
        data = json.loads(GLOSSARY_PATH.read_text())
        return len(data.get("entries", []))
    except Exception:
        return None


@router.get("/meta")
async def meta():
    now = time.time()
    if _cache["payload"] and now - _cache["at"] < _CACHE_TTL_S:
        return _cache["payload"]

    tx_count, db_status = _transaction_count()
    payload = {
        "database": {
            "table": "sales_transactions",
            "transactions": tx_count,
            "status": db_status,
        },
        "documents": _document_stats(),
        "web": {
            "retailers": sum(len(v) for v in WEB_RETAILERS.values()),
            "categories": len(WEB_RETAILERS),
            "sources": WEB_RETAILERS,
        },
        "business_context": {"glossary_entries": _glossary_entries()},
        "measured_at": now,
    }
    _cache["at"] = now
    _cache["payload"] = payload
    return payload
