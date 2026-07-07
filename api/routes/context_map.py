"""Business context / ontology endpoint. Read-only, provenance-tagged."""

from fastapi import APIRouter, HTTPException

from context.entity_map import build_context_map

router = APIRouter()


@router.get("/context")
def get_context_map():
    try:
        return build_context_map()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"context map failed: {exc}")
