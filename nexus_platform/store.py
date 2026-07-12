"""Platform store — sessions memory, feedback, traces (SQLite).

Every read helper REQUIRES a company slug (and employee where relevant) so
scoping is structural: there is no unscoped read path. Thread-safe via a
module lock; demo-scale write volume.
"""

from __future__ import annotations

import contextlib
import contextvars
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

CREATE TABLE IF NOT EXISTS simulated_query_log (
    id TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    persona_role TEXT NOT NULL,
    question TEXT NOT NULL,
    generated_from TEXT,
    pattern_family TEXT,
    difficulty TEXT,
    path_expected TEXT,
    trace_id TEXT,
    session_id TEXT,
    classification TEXT,
    classifier_confidence TEXT,
    classifier_reason TEXT,
    surfaced_real_failure INTEGER DEFAULT 0,
    tokens_estimated INTEGER DEFAULT 0,
    llm_used INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_simlog_campaign ON simulated_query_log (company, campaign_id);

CREATE TABLE IF NOT EXISTS health_findings (
    id TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    classification TEXT NOT NULL,
    severity TEXT NOT NULL,
    summary TEXT,
    payload TEXT,
    linked_branch TEXT,
    linked_pr TEXT,
    linked_eval TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_findings_fp ON health_findings (company, fingerprint);

CREATE TABLE IF NOT EXISTS health_finding_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS sim_pattern_stats (
    company TEXT NOT NULL,
    pattern_family TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    role TEXT NOT NULL,
    candidates_run INTEGER NOT NULL DEFAULT 0,
    passes INTEGER NOT NULL DEFAULT 0,
    failures_surfaced INTEGER NOT NULL DEFAULT 0,
    llm_calls_spent INTEGER NOT NULL DEFAULT 0,
    last_campaign_id TEXT,
    updated_at TEXT,
    PRIMARY KEY (company, pattern_family, difficulty, role)
);

CREATE TABLE IF NOT EXISTS agent_lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    campaign_id TEXT,
    scope TEXT NOT NULL,
    lesson TEXT NOT NULL,
    evidence TEXT NOT NULL,
    expires_after TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    referenced_count INTEGER NOT NULL DEFAULT 0
);
"""


# Columns added after first release — applied via ALTER for existing DBs.
_MIGRATIONS = [
    ("memory_turns", "intent_json", "TEXT"),
    ("memory_turns", "sql", "TEXT"),
    ("memory_turns", "route", "TEXT"),
    ("memory_turns", "tables_json", "TEXT"),
    ("memory_turns", "trace_id", "TEXT"),
    ("memory_turns", "chart_json", "TEXT"),
    # Simulated-traffic tagging: existing rows predate the column and are
    # real traffic; reads treat NULL as 'real'.
    ("traces", "source", "TEXT NOT NULL DEFAULT 'real'"),
]


# Trace-source tagging. The simulation runner wraps run_query() in
# tagged_trace_source("simulated") so every trace saved inside the pipeline
# is tagged without threading a parameter through the query service. Reads
# default to real-only so simulated traffic can never leak into reports,
# exports, or admin views unless a caller explicitly opts in.
TRACE_SOURCES = ("real", "simulated")
_trace_source: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_source", default="real")


@contextlib.contextmanager
def tagged_trace_source(source: str):
    if source not in TRACE_SOURCES:
        raise ValueError(f"Unknown trace source: {source}")
    token = _trace_source.set(source)
    try:
        yield
    finally:
        _trace_source.reset(token)


def _source_clause(source: Optional[str]) -> tuple[str, list]:
    """WHERE fragment for a source filter. None means both sources."""
    if source is None:
        return "", []
    if source not in TRACE_SOURCES:
        raise ValueError(f"Unknown trace source: {source}")
    return " AND COALESCE(source, 'real') = ?", [source]


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
               access_decision: str, payload: dict,
               source: Optional[str] = None) -> str:
    tid = f"tr_{uuid.uuid4().hex[:10]}"
    src = source or _trace_source.get()
    if src not in TRACE_SOURCES:
        raise ValueError(f"Unknown trace source: {src}")
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO traces (id, company, employee, role, ts, question, "
            "access_decision, payload, source) VALUES (?,?,?,?,?,?,?,?,?)",
            (tid, company, employee, role, _now(), question, access_decision,
             json.dumps(payload, default=str), src),
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
                             limit: int = 5000,
                             source: Optional[str] = "real") -> list[dict]:
    """Company-scoped traces WITH payloads — the Health Check input.

    Defaults to real traffic only; pass source="simulated" for campaign
    review or source=None for both (explicit opt-in, never the default).
    """
    sql = "SELECT * FROM traces WHERE company=?"
    params: list = [company]
    clause, extra = _source_clause(source)
    sql += clause
    params += extra
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
                limit: int = 100, source: Optional[str] = "real") -> list[dict]:
    sql = ("SELECT id, company, employee, role, ts, question, access_decision "
           "FROM traces WHERE company=?")
    params: list = [company]
    clause, extra = _source_clause(source)
    sql += clause
    params += extra
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


# ── Simulation campaign ledger ──────────────────────────────────────────

def save_sim_query(company: str, campaign_id: str, persona_role: str,
                   question: str, generated_from: Optional[str],
                   pattern_family: str, difficulty: str, path_expected: str,
                   trace_id: Optional[str], session_id: Optional[str],
                   llm_used: bool, tokens_estimated: int = 0) -> str:
    sid = f"sim_{uuid.uuid4().hex[:10]}"
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO simulated_query_log (id, company, campaign_id, ts, "
            "persona_role, question, generated_from, pattern_family, "
            "difficulty, path_expected, trace_id, session_id, llm_used, "
            "tokens_estimated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, company, campaign_id, _now(), persona_role, question,
             generated_from, pattern_family, difficulty, path_expected,
             trace_id, session_id, int(llm_used), tokens_estimated),
        )
        conn.commit()
    return sid


def classify_sim_query(sim_id: str, classification: str, confidence: str,
                       reason: str, surfaced_real_failure: bool) -> None:
    with _lock:
        conn = _get_conn()
        conn.execute(
            "UPDATE simulated_query_log SET classification=?, "
            "classifier_confidence=?, classifier_reason=?, "
            "surfaced_real_failure=? WHERE id=?",
            (classification, confidence, reason,
             int(surfaced_real_failure), sim_id),
        )
        conn.commit()


def list_sim_queries(company: str, campaign_id: Optional[str] = None) -> list[dict]:
    sql = "SELECT * FROM simulated_query_log WHERE company=?"
    params: list = [company]
    if campaign_id:
        sql += " AND campaign_id=?"
        params.append(campaign_id)
    sql += " ORDER BY ts"
    with _lock:
        rows = _get_conn().execute(sql, params).fetchall()
    return [dict(r) for r in rows]


# ── Finding resolution memory ───────────────────────────────────────────

def upsert_finding(company: str, fingerprint: str, classification: str,
                   severity: str, summary: str, payload: Optional[dict] = None,
                   actor: str = "health_check_agent") -> dict:
    """Insert a finding or refresh last_seen on its fingerprint. Reopens
    findings previously marked fixed (recurrence must be visible, never
    silently swallowed)."""
    now = _now()
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM health_findings WHERE company=? AND fingerprint=?",
            (company, fingerprint),
        ).fetchone()
        if row is None:
            fid = f"hf_{uuid.uuid4().hex[:10]}"
            conn.execute(
                "INSERT INTO health_findings (id, company, fingerprint, "
                "first_seen, last_seen, status, classification, severity, "
                "summary, payload) VALUES (?,?,?,?,?,'new',?,?,?,?)",
                (fid, company, fingerprint, now, now, classification,
                 severity, summary, json.dumps(payload or {}, default=str)),
            )
            conn.execute(
                "INSERT INTO health_finding_events (finding_id, ts, actor, "
                "from_status, to_status, note) VALUES (?,?,?,NULL,'new',?)",
                (fid, now, actor, "finding first observed"),
            )
            conn.commit()
            status, is_new = "new", True
        else:
            fid = row["id"]
            status, is_new = row["status"], False
            new_status = status
            if status == "fixed":
                new_status = "reopened"
            conn.execute(
                "UPDATE health_findings SET last_seen=?, status=?, severity=?, "
                "summary=? WHERE id=?",
                (now, new_status, severity, summary, fid),
            )
            if new_status != status:
                conn.execute(
                    "INSERT INTO health_finding_events (finding_id, ts, actor, "
                    "from_status, to_status, note) VALUES (?,?,?,?,?,?)",
                    (fid, now, actor, status, new_status,
                     "finding recurred after fix"),
                )
            status = new_status
            conn.commit()
    return {"id": fid, "status": status, "is_new": is_new}


def update_finding_status(finding_id: str, to_status: str, actor: str,
                          note: str = "", linked_branch: Optional[str] = None,
                          linked_pr: Optional[str] = None,
                          linked_eval: Optional[str] = None) -> bool:
    valid = ("new", "reviewed", "fix_planned", "fixed", "dismissed_valid",
             "needs_clarification", "reopened")
    if to_status not in valid:
        return False
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT status FROM health_findings WHERE id=?", (finding_id,)
        ).fetchone()
        if row is None:
            return False
        sets, params = ["status=?"], [to_status]
        for col, val in (("linked_branch", linked_branch),
                         ("linked_pr", linked_pr),
                         ("linked_eval", linked_eval)):
            if val is not None:
                sets.append(f"{col}=?")
                params.append(val)
        params.append(finding_id)
        conn.execute(f"UPDATE health_findings SET {', '.join(sets)} WHERE id=?",
                     params)
        conn.execute(
            "INSERT INTO health_finding_events (finding_id, ts, actor, "
            "from_status, to_status, note) VALUES (?,?,?,?,?,?)",
            (finding_id, _now(), actor, row["status"], to_status, note),
        )
        conn.commit()
    return True


def list_findings(company: str, status: Optional[str] = None) -> list[dict]:
    sql = "SELECT * FROM health_findings WHERE company=?"
    params: list = [company]
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY last_seen DESC"
    with _lock:
        rows = _get_conn().execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d["payload"]) if d.get("payload") else {}
        except (ValueError, TypeError):
            d["payload"] = {}
        out.append(d)
    return out


# ── Agent operational memory (pattern stats + episodic lessons) ─────────
# Design rationale in docs/platform improvements/ARCHITECTURE_LOG.md Entry 2:
# numeric stats compact by lossless aggregation; lessons are append-only raw
# episodes, never LLM-rewritten, bounded by deactivation (not deletion).

def bump_pattern_stats(company: str, pattern_family: str, difficulty: str,
                       role: str, campaign_id: str, ran: int = 0,
                       passed: int = 0, failed: int = 0,
                       llm_calls: int = 0) -> None:
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO sim_pattern_stats (company, pattern_family, "
            "difficulty, role, candidates_run, passes, failures_surfaced, "
            "llm_calls_spent, last_campaign_id, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT (company, pattern_family, difficulty, role) DO UPDATE SET "
            "candidates_run = candidates_run + excluded.candidates_run, "
            "passes = passes + excluded.passes, "
            "failures_surfaced = failures_surfaced + excluded.failures_surfaced, "
            "llm_calls_spent = llm_calls_spent + excluded.llm_calls_spent, "
            "last_campaign_id = excluded.last_campaign_id, "
            "updated_at = excluded.updated_at",
            (company, pattern_family, difficulty, role, ran, passed, failed,
             llm_calls, campaign_id, _now()),
        )
        conn.commit()


def get_pattern_stats(company: str) -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT * FROM sim_pattern_stats WHERE company=? "
            "ORDER BY failures_surfaced DESC, candidates_run DESC", (company,),
        ).fetchall()
    return [dict(r) for r in rows]


MAX_ACTIVE_LESSONS = 40


def add_lesson(scope: str, lesson: str, evidence: list[str],
               campaign_id: Optional[str] = None,
               expires_after: Optional[str] = None) -> int:
    """Record one episodic lesson. Evidence ids are required — a lesson
    without evidence is a belief, not a lesson, and is refused."""
    if not evidence:
        raise ValueError("A lesson requires evidence ids (trace/finding/campaign)")
    with _lock:
        conn = _get_conn()
        cur = conn.execute(
            "INSERT INTO agent_lessons (ts, campaign_id, scope, lesson, "
            "evidence, expires_after, active) VALUES (?,?,?,?,?,?,1)",
            (_now(), campaign_id, scope, lesson, json.dumps(evidence),
             expires_after),
        )
        # Bound the active set: deactivate (never delete) expired lessons,
        # then the least-referenced oldest beyond the cap.
        conn.execute(
            "UPDATE agent_lessons SET active=0 WHERE active=1 AND "
            "expires_after IS NOT NULL AND expires_after < ?", (_now(),),
        )
        extra = conn.execute(
            "SELECT COUNT(*) FROM agent_lessons WHERE active=1"
        ).fetchone()[0] - MAX_ACTIVE_LESSONS
        if extra > 0:
            # The just-written lesson is exempt: reads bump
            # referenced_count, so entrenched entries out-count any
            # newcomer (always 0) and would evict it at birth — the
            # memory would stop learning the moment it filled up.
            conn.execute(
                "UPDATE agent_lessons SET active=0 WHERE id IN ("
                "SELECT id FROM agent_lessons WHERE active=1 AND id != ? "
                "ORDER BY referenced_count ASC, id ASC LIMIT ?)",
                (cur.lastrowid, extra),
            )
        conn.commit()
        return int(cur.lastrowid)


def list_active_lessons(scope: Optional[str] = None) -> list[dict]:
    sql = "SELECT * FROM agent_lessons WHERE active=1"
    params: list = []
    if scope:
        sql += " AND scope=?"
        params.append(scope)
    sql += " ORDER BY id DESC"
    with _lock:
        conn = _get_conn()
        rows = conn.execute(sql, params).fetchall()
        if rows:
            conn.execute(
                f"UPDATE agent_lessons SET referenced_count = referenced_count + 1 "
                f"WHERE id IN ({','.join('?' * len(rows))})",
                [r["id"] for r in rows],
            )
            conn.commit()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["evidence"] = json.loads(d["evidence"])
        except (ValueError, TypeError):
            d["evidence"] = []
        out.append(d)
    return out
