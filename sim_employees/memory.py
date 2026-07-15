"""Per-employee private memory — plain JSON files, inspectable and durable.

One file per simulation employee under `sim_employees/memory/<company>/`. The
file records every interaction (question, how the analyst routed/answered, a
cheap health verdict) plus a rolling list of weak spots to re-probe and
free-text notes the external CLI brain may write for its future self. Files
live on disk (never the ephemeral container), so memory survives regardless
of the trace database.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

MEM_DIR = Path(__file__).resolve().parent / "memory"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(email: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "_", email.strip().lower())


def mem_path(company: str, email: str) -> Path:
    return MEM_DIR / company / f"{_slug(email)}.json"


def load(company: str, email: str, role: str = "", name: str = "") -> dict:
    p = mem_path(company, email)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (ValueError, OSError):
            pass
    return {
        "company": company,
        "employee": email,
        "role": role,
        "name": name,
        "created": _now(),
        "interactions": [],   # append-only history
        "weak_spots": [],     # {topic, note, evidence_trace, ts}
        "notes": "",          # free-text the CLI brain writes for next time
    }


def save(mem: dict) -> Path:
    p = mem_path(mem["company"], mem["employee"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(mem, indent=2, ensure_ascii=False))
    return p


def append_interaction(mem: dict, interaction: dict,
                       weak: bool = False, weak_note: str = "") -> None:
    """Record one Q/A interaction; optionally flag a weak spot to re-probe."""
    mem["interactions"].append({"ts": _now(), **interaction})
    if weak:
        mem.setdefault("weak_spots", []).append({
            "topic": interaction.get("question", "")[:80],
            "note": weak_note or "answer looked weak — re-probe differently",
            "evidence_trace": interaction.get("trace_id"),
            "ts": _now(),
        })


def set_notes(mem: dict, notes: str) -> None:
    mem["notes"] = notes


def brief_summary(mem: dict, recent: int = 10) -> dict:
    """What the CLI brain needs to ask an adaptive next batch: what was asked
    recently (avoid repeats), and where the analyst looked weak (re-probe)."""
    inter = mem.get("interactions", [])
    return {
        "total_interactions": len(inter),
        "recent_questions": [i.get("question") for i in inter[-recent:]],
        "recent_outcomes": [
            {"question": i.get("question"), "route": i.get("route"),
             "access_decision": i.get("access_decision"),
             "confidence": i.get("confidence"), "verdict": i.get("verdict")}
            for i in inter[-recent:]
        ],
        "weak_spots": mem.get("weak_spots", [])[-12:],
        "notes": mem.get("notes", ""),
    }
