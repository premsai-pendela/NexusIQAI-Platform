"""Learning-loop endpoint: failures, repair queue, governance stats.

Read-only. The API never mutates the loop; scans and approvals run through
the CLI (`python -m learning.service`) where they are audit-logged in the
JSONL stores.
"""

from fastapi import APIRouter, HTTPException, Query

from learning.memory import recall
from learning.service import loop_summary

router = APIRouter()


@router.get("/learning")
def get_learning_loop():
    try:
        return loop_summary()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"learning summary failed: {exc}")


@router.get("/learning/recall")
def get_learning_recall(q: str = Query(..., min_length=3, max_length=500)):
    """Failure-memory lookup: has a question like this failed before?"""
    try:
        return recall(q)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"recall failed: {exc}")
