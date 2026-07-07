"""Platform store — sessions memory, feedback, traces (SQLite).

Every read helper REQUIRES a company slug (and employee where relevant) so
scoping is structural: there is no unscoped read path. Thread-safe via a
module lock; demo-scale write volume.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "platform.db"

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    employee TEXT NOT NULL,
    session_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    question TEXT NOT NULL,
    resolved_question TEXT,
    answer_summary TEXT,
    source_type TEXT,
    chart_type TEXT,
    refused INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_memory_scope ON memory_turns (company, employee, session_id);

CREATE TABLE IF NOT EXISTS employee_prefs (
    company TEXT NOT NULL,
    employee TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (company, employee, key)
);

CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    employee TEXT NOT NULL,
    role TEXT NOT NULL,
    ts TEXT NOT NULL,
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    page TEXT,
    trace_id TEXT,
    status TEXT NOT NULL DEFAULT 'new'
);
CREATE INDEX IF NOT EXISTS idx_feedback_company ON feedback (company, ts);

CREATE TABLE IF NOT EXISTS traces (
    id TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    employee TEXT NOT NULL,
    role TEXT NOT NULL,
    ts TEXT NOT NULL,
    question TEXT NOT NULL,
    access_decision TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_traces_company ON traces (company, ts);
CREATE INDEX IF NOT EXISTS idx_traces_employee ON traces (company, employee, ts);
"""


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(_SCHEMA)
    return _conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Memory ──────────────────────────────────────────────────────────────

def save_turn(company: str, employee: str, session_id: str, question: str,
              resolved_question: str, answer_summary: str, source_type: str,
              chart_type: Optional[str], refused: bool) -> None:
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO memory_turns (company, employee, session_id, ts, question, "
            "resolved_question, answer_summary, source_type, chart_type, refused) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (company, employee, session_id, _now(), question, resolved_question,
             answer_summary[:500] if answer_summary else "", source_type,
             chart_type, int(refused)),
        )
        conn.commit()


def recent_turns(company: str, employee: str, session_id: str, limit: int = 12) -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT * FROM memory_turns WHERE company=? AND employee=? AND session_id=? "
            "ORDER BY id DESC LIMIT ?",
            (company, employee, session_id, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def employee_history(company: str, employee: str, limit: int = 50) -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT * FROM memory_turns WHERE company=? AND employee=? "
            "ORDER BY id DESC LIMIT ?",
            (company, employee, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def set_pref(company: str, employee: str, key: str, value: str) -> None:
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO employee_prefs (company, employee, key, value, updated_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT (company, employee, key) "
            "DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (company, employee, key, value, _now()),
        )
        conn.commit()


def get_prefs(company: str, employee: str) -> dict[str, str]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT key, value FROM employee_prefs WHERE company=? AND employee=?",
            (company, employee),
        ).fetchall()
    return {r["key"]: r["value"] for r in rows}


# ── Feedback ────────────────────────────────────────────────────────────

def save_feedback(company: str, employee: str, role: str, category: str,
                  message: str, page: Optional[str], trace_id: Optional[str]) -> str:
    fid = f"fb_{uuid.uuid4().hex[:10]}"
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO feedback (id, company, employee, role, ts, category, message, "
            "page, trace_id, status) VALUES (?,?,?,?,?,?,?,?,?,'new')",
            (fid, company, employee, role, _now(), category, message, page, trace_id),
        )
        conn.commit()
    return fid


def list_feedback(company: str, employee: Optional[str] = None,
                  status: Optional[str] = None, category: Optional[str] = None) -> list[dict]:
    sql = "SELECT * FROM feedback WHERE company=?"
    params: list = [company]
    if employee:
        sql += " AND employee=?"
        params.append(employee)
    if status:
        sql += " AND status=?"
        params.append(status)
    if category:
        sql += " AND category=?"
        params.append(category)
    sql += " ORDER BY ts DESC LIMIT 200"
    with _lock:
        rows = _get_conn().execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def update_feedback_status(company: str, feedback_id: str, status: str) -> bool:
    if status not in ("new", "reviewed", "resolved"):
        return False
    with _lock:
        conn = _get_conn()
        cur = conn.execute(
            "UPDATE feedback SET status=? WHERE id=? AND company=?",
            (status, feedback_id, company),
        )
        conn.commit()
    return cur.rowcount > 0


# ── Traces ──────────────────────────────────────────────────────────────

def save_trace(company: str, employee: str, role: str, question: str,
               access_decision: str, payload: dict) -> str:
    tid = f"tr_{uuid.uuid4().hex[:10]}"
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO traces (id, company, employee, role, ts, question, "
            "access_decision, payload) VALUES (?,?,?,?,?,?,?,?)",
            (tid, company, employee, role, _now(), question, access_decision,
             json.dumps(payload, default=str)),
        )
        conn.commit()
    return tid


def get_trace(company: str, trace_id: str) -> Optional[dict]:
    """Company-scoped lookup — a trace id from another company returns None."""
    with _lock:
        row = _get_conn().execute(
            "SELECT * FROM traces WHERE id=? AND company=?", (trace_id, company)
        ).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["payload"] = json.loads(out["payload"])
    return out


def list_traces(company: str, employee: Optional[str] = None,
                date_from: Optional[str] = None, date_to: Optional[str] = None,
                limit: int = 100) -> list[dict]:
    sql = ("SELECT id, company, employee, role, ts, question, access_decision "
           "FROM traces WHERE company=?")
    params: list = [company]
    if employee:
        sql += " AND employee=?"
        params.append(employee)
    if date_from:
        sql += " AND ts >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND ts <= ?"
        params.append(date_to)
    sql += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    with _lock:
        rows = _get_conn().execute(sql, params).fetchall()
    return [dict(r) for r in rows]
