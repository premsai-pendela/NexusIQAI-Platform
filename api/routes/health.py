import time
import os
from datetime import datetime, timezone
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from api.models.schemas import HealthResponse
from nexus_platform.contexts import get_company_fusion_agent
from nexus_platform.registry import get_registry
from observability.langfuse_adapter import get_langfuse_observer

router = APIRouter()

_START_TIME = time.time()

# Health checks exercise one real company workspace end to end (SQL + RAG +
# web + fusion). Any registered company/Admin pair works; acmecloud is just
# the first one seeded.
_PROBE_COMPANY = "acmecloud"
_PROBE_ROLE = "Admin"


def _probe_agent():
    return get_company_fusion_agent(_PROBE_COMPANY, _PROBE_ROLE)


def _chroma_chunk_count() -> int:
    try:
        return _probe_agent().rag_agent.collection.count()
    except Exception:
        return -1


def _cache_entry_count() -> int:
    try:
        return len(_probe_agent()._query_cache)
    except Exception:
        return -1


def _truthy_env(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _production_features() -> dict:
    langfuse = get_langfuse_observer()
    return {
        "production_harness": _truthy_env("NEXUSIQ_USE_PRODUCTION_HARNESS", "1"),
        "langgraph": _truthy_env("NEXUSIQ_USE_LANGGRAPH", "1"),
        "langfuse": langfuse.enabled(),
        "trace_enabled": _truthy_env("NEXUSIQ_TRACE_ENABLED", "1"),
        "llm_ledger_enabled": os.getenv("NEXUSIQ_LLM_LEDGER_ENABLED", "1") != "0",
        "environment": os.getenv("ENVIRONMENT", "development"),
    }


@router.get("/health", response_model=HealthResponse)
async def health():
    agents_status = {}
    degraded = False

    if get_registry().get_company(_PROBE_COMPANY) is None:
        return JSONResponse(
            content=HealthResponse(
                status="degraded",
                agents={"registry": f"company '{_PROBE_COMPANY}' not seeded"},
                production_features=_production_features(),
                chroma_chunks=-1,
                cache_entries=-1,
                uptime_seconds=round(time.time() - _START_TIME, 1),
                timestamp=datetime.now(timezone.utc).isoformat(),
            ).model_dump(),
            status_code=503,
        )

    try:
        agent = _probe_agent()
    except Exception as e:
        agent = None
        degraded = True
        agents_status["fusion"] = f"degraded: {str(e)[:60]}"

    if agent is not None:
        # SQL
        try:
            agent.sql_agent.session.execute(text("SELECT 1"))
            agents_status["sql"] = "online"
        except Exception as e:
            agents_status["sql"] = f"degraded: {str(e)[:60]}"
            degraded = True

        # RAG / ChromaDB
        try:
            agent.rag_agent.collection.count()
            agents_status["rag"] = "online"
        except Exception as e:
            agents_status["rag"] = f"degraded: {str(e)[:60]}"
            degraded = True

        # Web (company workspaces don't mix in live web data — presence check only)
        agents_status["web"] = "disabled (company workspace scope)"

        agents_status["fusion"] = "online"

    chroma_chunks = _chroma_chunk_count()
    cache_entries = _cache_entry_count()
    status = "degraded" if degraded else "healthy"
    response = HealthResponse(
        status=status,
        agents=agents_status,
        production_features=_production_features(),
        chroma_chunks=chroma_chunks,
        cache_entries=cache_entries,
        uptime_seconds=round(time.time() - _START_TIME, 1),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    http_status = 503 if degraded else 200
    return JSONResponse(content=response.model_dump(), status_code=http_status)
