"""Public, sanitized trace lookup.

Lets the frontend show the real execution timeline behind an answer
("How I answered" → full trace). Only whitelisted, non-sensitive fields
leave the server: span names, timing, status, and scalar metadata. Prompt
previews, answer previews, and any long strings are dropped.
"""

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from observability import tracer

router = APIRouter()

_TRACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
_BLOCKED_KEY_PARTS = ("prompt", "preview", "answer", "question", "error_detail")
_MAX_STR = 120


def _safe_scalar(value):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str) and len(value) <= _MAX_STR:
        return value
    return None


def _safe_metadata(metadata: dict) -> dict:
    out = {}
    for key, value in (metadata or {}).items():
        if any(part in key.lower() for part in _BLOCKED_KEY_PARTS):
            continue
        safe = _safe_scalar(value)
        if safe is not None:
            out[key] = safe
    return out


def _sanitize_span(span: dict) -> dict:
    return {
        "name": span.get("name"),
        "started_at": span.get("started_at"),
        "duration_s": span.get("duration_s"),
        "status": span.get("status"),
        "metadata": _safe_metadata(span.get("metadata") or {}),
    }


def _find_trace_file(trace_id: str) -> Path | None:
    trace_dir = tracer._trace_dir()
    if not trace_dir.exists():
        return None
    matches = sorted(trace_dir.glob(f"trace-*-{trace_id}.json"))
    return matches[-1] if matches else None


@router.get("/trace/{trace_id}")
async def get_trace(trace_id: str):
    if not _TRACE_ID_RE.match(trace_id):
        raise HTTPException(status_code=400, detail="Invalid trace id")

    path = _find_trace_file(trace_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Trace not found")

    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        raise HTTPException(status_code=404, detail="Trace not readable")

    final = data.get("final") or {}
    usage = final.get("llm_usage") or {}
    return {
        "trace_id": data.get("trace_id"),
        "started_at": data.get("started_at"),
        "duration_s": data.get("duration_s"),
        "trace_type": data.get("trace_type"),
        "spans": [_sanitize_span(s) for s in data.get("spans") or []],
        "final": {
            "source_type": final.get("source_type"),
            "routing_model": final.get("routing_model"),
            "answer_models": final.get("answer_models"),
            "from_cache": final.get("from_cache"),
            "query_time_s": final.get("query_time_s"),
            "validation": final.get("validation"),
            "llm_usage": {
                "successful_calls": usage.get("successful_calls"),
                "avoided_calls": usage.get("avoided_calls"),
                "estimated_tokens": usage.get("estimated_tokens"),
                "avoided_estimated_tokens": usage.get("avoided_estimated_tokens"),
            } if usage else None,
        },
    }
