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

CREATE TABLE IF NOT EXISTS generated_employees (
    email TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    title TEXT NOT NULL,
    department TEXT NOT NULL,
    team TEXT,
    manager_email TEXT,
    password_hash TEXT NOT NULL,
    is_demo INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_genemp_company ON generated_employees (company);

CREATE TABLE IF NOT EXISTS health_reports (
    id TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    ts TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    window_days INTEGER NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_health_company ON health_reports (company, ts);
"""


# Columns added after first release — applied via ALTER for existing DBs.
_MIGRATIONS = [
    ("memory_turns", "intent_json", "TEXT"),
    ("memory_turns", "sql", "TEXT"),
    ("memory_turns", "route", "TEXT"),
    ("memory_turns", "tables_json", "TEXT"),
    ("memory_turns", "trace_id", "TEXT"),
    ("memory_turns", "chart_json", "TEXT"),
]


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(_SCHEMA)
        for table, column, ctype in _MIGRATIONS:
            cols = {r[1] for r in _conn.execute(f'PRAGMA table_info("{table}")').fetchall()}
            if column not in cols:
                _conn.execute(f'ALTER TABLE {table} ADD COLUMN "{column}" {ctype}')
        _conn.commit()
    return _conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Memory ──────────────────────────────────────────────────────────────

def save_turn(company: str, employee: str, session_id: str, question: str,
              resolved_question: str, answer_summary: str, source_type: str,
              chart_type: Optional[str], refused: bool,
              intent_json: Optional[str] = None, sql: Optional[str] = None,
              route: Optional[str] = None, tables_json: Optional[str] = None,
              trace_id: Optional[str] = None, chart_json: Optional[str] = None) -> None:
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO memory_turns (company, employee, session_id, ts, question, "
            "resolved_question, answer_summary, source_type, chart_type, refused, "
            "intent_json, sql, route, tables_json, trace_id, chart_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (company, employee, session_id, _now(), question, resolved_question,
             answer_summary[:500] if answer_summary else "", source_type,
             chart_type, int(refused), intent_json, sql, route, tables_json,
             trace_id, chart_json),
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


def list_traces_with_payload(company: str, date_from: Optional[str] = None,
                             limit: int = 5000) -> list[dict]:
    """Company-scoped traces WITH payloads — the Health Check input."""
    sql = "SELECT * FROM traces WHERE company=?"
    params: list = [company]
    if date_from:
        sql += " AND ts >= ?"
        params.append(date_from)
    sql += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    with _lock:
        rows = _get_conn().execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d["payload"])
        except (ValueError, TypeError):
            d["payload"] = {}
        out.append(d)
    return out


# ── Generated employee population ───────────────────────────────────────

def replace_generated_employees(company: str, employees: list[dict]) -> int:
    """Replace the generated (non-demo) population for one company."""
    with _lock:
        conn = _get_conn()
        conn.execute("DELETE FROM generated_employees WHERE company=?", (company,))
        conn.executemany(
            "INSERT INTO generated_employees (email, company, name, role, title, "
            "department, team, manager_email, password_hash, is_demo) "
            "VALUES (:email, :company, :name, :role, :title, :department, "
            ":team, :manager_email, :password_hash, 0)",
            employees,
        )
        conn.commit()
    return len(employees)


def get_generated_employee(email: str) -> Optional[dict]:
    with _lock:
        row = _get_conn().execute(
            "SELECT * FROM generated_employees WHERE email=?",
            (email.strip().lower(),),
        ).fetchone()
    return dict(row) if row else None


def count_generated_employees(company: str) -> int:
    with _lock:
        row = _get_conn().execute(
            "SELECT COUNT(*) FROM generated_employees WHERE company=?", (company,)
        ).fetchone()
    return int(row[0])


def list_generated_employees(company: str, limit: int = 500) -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT email, name, role, title, department, team FROM "
            "generated_employees WHERE company=? ORDER BY email LIMIT ?",
            (company, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Bulk history (generated trace/feedback corpus) ──────────────────────

def bulk_save_traces(rows: list[dict]) -> int:
    """Insert many traces in one transaction. Each row needs: id, company,
    employee, role, ts, question, access_decision, payload(dict)."""
    with _lock:
        conn = _get_conn()
        conn.executemany(
            "INSERT OR REPLACE INTO traces (id, company, employee, role, ts, "
            "question, access_decision, payload) "
            "VALUES (:id, :company, :employee, :role, :ts, :question, "
            ":access_decision, :payload)",
            [{**r, "payload": json.dumps(r["payload"], default=str)} for r in rows],
        )
        conn.commit()
    return len(rows)


def bulk_save_feedback(rows: list[dict]) -> int:
    with _lock:
        conn = _get_conn()
        conn.executemany(
            "INSERT OR REPLACE INTO feedback (id, company, employee, role, ts, "
            "category, message, page, trace_id, status) "
            "VALUES (:id, :company, :employee, :role, :ts, :category, "
            ":message, :page, :trace_id, :status)",
            rows,
        )
        conn.commit()
    return len(rows)


def delete_generated_history(company: str) -> None:
    """Remove previously generated corpus rows (ids are prefixed gen_)."""
    with _lock:
        conn = _get_conn()
        conn.execute("DELETE FROM traces WHERE company=? AND id LIKE 'gen_%'", (company,))
        conn.execute("DELETE FROM feedback WHERE company=? AND id LIKE 'genfb_%'", (company,))
        conn.commit()


# ── Health reports ──────────────────────────────────────────────────────

def save_health_report(company: str, requested_by: str, window_days: int,
                       payload: dict) -> str:
    hid = f"hc_{uuid.uuid4().hex[:10]}"
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO health_reports (id, company, ts, requested_by, "
            "window_days, payload) VALUES (?,?,?,?,?,?)",
            (hid, company, _now(), requested_by, window_days,
             json.dumps(payload, default=str)),
        )
        conn.commit()
    return hid


def list_health_reports(company: str, limit: int = 20) -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT id, company, ts, requested_by, window_days FROM health_reports "
            "WHERE company=? ORDER BY ts DESC LIMIT ?", (company, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_health_report(company: str, report_id: str) -> Optional[dict]:
    with _lock:
        row = _get_conn().execute(
            "SELECT * FROM health_reports WHERE id=? AND company=?",
            (report_id, company),
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
