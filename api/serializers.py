"""Shared serialization from fusion-agent results to API payloads.

Everything here only *exposes* data the agents already produce — it never
invents values. Missing data serializes as None/[] so clients can render
honest empty states.
"""

from typing import Any, Dict, List, Optional

_RESULT_PREVIEW_ROWS = 5
_SNIPPET_CHARS = 300


def _sql_evidence(sql_result: Optional[Dict]) -> Optional[Dict[str, Any]]:
    if not sql_result:
        return None
    rows = sql_result.get("results") or []
    preview = []
    for row in rows[:_RESULT_PREVIEW_ROWS]:
        if isinstance(row, dict):
            preview.append({k: _jsonable(v) for k, v in row.items()})
    return {
        "success": bool(sql_result.get("success")),
        "query": sql_result.get("query") or None,
        "row_count": sql_result.get("row_count"),
        "result_preview": preview,
        "answer_mode": sql_result.get("answer_mode"),
        "repair_attempted": bool((sql_result.get("sql_repair") or {}).get("attempted")),
        "error": _clip(sql_result.get("error")) or None,
        "time_s": sql_result.get("time"),
    }


def _document_evidence(rag_result: Optional[Dict]) -> List[Dict[str, Any]]:
    if not rag_result:
        return []
    out = []
    for s in rag_result.get("sources") or []:
        if not isinstance(s, dict):
            continue
        out.append({
            "filename": s.get("filename") or s.get("source") or s.get("title"),
            "page": s.get("page"),
            "relevance": s.get("relevance_score"),
            "cited_in_answer": bool(s.get("cited_in_answer")),
            "snippet": _clip(s.get("content") or s.get("document") or s.get("text")),
        })
    return out


def _web_evidence(web_result: Optional[Dict]) -> List[Dict[str, Any]]:
    if not web_result:
        return []
    out = []
    competitors = (web_result.get("raw_data") or {}).get("competitors") or []
    for c in competitors:
        if not isinstance(c, dict):
            continue
        out.append({
            "source": c.get("competitor") or c.get("source") or c.get("name"),
            "category": c.get("category") or web_result.get("category"),
            "products": c.get("product_count") or len(c.get("products") or []),
            "sample_data": bool(c.get("is_mock") or c.get("data_status") == "sample"),
        })
    return out


def _usage(result: Dict) -> Optional[Dict[str, Any]]:
    usage = result.get("llm_usage")
    if not usage:
        return None
    return {
        "llm_calls": usage.get("successful_calls"),
        "avoided_llm_calls": usage.get("avoided_calls"),
        "avoided_estimated_tokens": usage.get("avoided_estimated_tokens"),
        "estimated_tokens": usage.get("estimated_tokens"),
        "actual_tokens": usage.get("actual_tokens") or None,
        "answer_mode": result.get("answer_generation_mode"),
    }


def build_answer_payload(result: Dict) -> Dict[str, Any]:
    """Full, honest answer payload for /query and the final stream event."""
    validation = result.get("validation") or {}
    return {
        "answer": result.get("answer", ""),
        "confidence": validation.get("confidence") or "UNKNOWN",
        "confidence_reason": validation.get("confidence_reason"),
        "route": result.get("source_type", "unknown"),
        "evidence": {
            "sql": _sql_evidence(result.get("sql_result")),
            "documents": _document_evidence(result.get("rag_result")),
            "web": _web_evidence(result.get("web_result")),
        },
        "usage": _usage(result),
        "query_time_s": _round(result.get("query_time")),
        "cached": bool(result.get("_from_cache", False)),
        "trace_id": result.get("trace_id"),
    }


def _clip(value: Any, limit: int = _SNIPPET_CHARS) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    return text[:limit]


def _round(value: Any) -> Optional[float]:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
