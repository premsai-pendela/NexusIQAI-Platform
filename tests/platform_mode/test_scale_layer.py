"""Scale layer: generated employee population, historical corpus, curated
login boundary, and PostgreSQL parity (skipped when PG is unreachable)."""

import os

import pytest
from sqlalchemy import create_engine, text

from nexus_platform import store
from nexus_platform.registry import get_registry
from nexus_platform.scale.population import (generate_population,
                                             generated_password, seed_population)

PG_URL = "postgresql://nagapremsaipendela@localhost:5432/nexusiqai_platform"


def _pg_available() -> bool:
    try:
        eng = create_engine(PG_URL, connect_args={"connect_timeout": 2})
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        eng.dispose()
        return True
    except Exception:
        return False


# ── Generated population ─────────────────────────────────────────────────

def test_population_size_and_determinism():
    a1 = generate_population("acmecloud")
    a2 = generate_population("acmecloud")
    assert a1 == a2, "population must be reproducible"
    assert 100 <= len(a1) <= 150
    roles = {e["role"] for e in a1}
    assert roles <= {"Analyst", "Finance", "HR", "Support", "Ops"}
    assert all(e["password_hash"] for e in a1)
    assert all(e["manager_email"] for e in a1)


def test_generated_employee_can_authenticate():
    seed_population("acmecloud")
    emp_row = store.list_generated_employees("acmecloud", limit=1)[0]
    # recover the deterministic index from the email suffix
    import re
    n = int(re.search(r"(\d+)@", emp_row["email"]).group(1))
    reg = get_registry()
    emp = reg.authenticate(emp_row["email"], generated_password("acmecloud", n))
    assert emp is not None
    assert emp.company_slug == "acmecloud"
    assert emp.role == emp_row["role"]
    assert not emp.is_admin  # generated employees are never Admin/CEO


def test_generated_employee_wrong_password_rejected():
    emp_row = store.list_generated_employees("acmecloud", limit=1)[0]
    assert get_registry().authenticate(emp_row["email"], "wrong") is None


def test_curated_registry_unchanged_by_population():
    """The login UI lists only curated accounts — the registry's in-memory
    employee map must stay exactly the seed file."""
    reg = get_registry()
    assert len(reg.employees) == 9
    assert all(e.email.endswith((".test",)) for e in reg.employees.values())


def test_population_counts_all_companies():
    for slug in ("acmecloud", "medcore", "finpilot"):
        seed_population(slug)
        n = store.count_generated_employees(slug)
        assert 100 <= n <= 150, f"{slug}: {n}"


# ── Historical corpus ────────────────────────────────────────────────────

def test_history_generator_produces_volume_and_variety():
    from nexus_platform.scale.history import generate_history
    stats = generate_history("medcore", per_company=400, days=30)
    assert stats["traces"] >= 400
    assert stats["feedback"] > 0
    traces = store.list_traces_with_payload("medcore", limit=10000)
    gen = [t for t in traces if str(t["id"]).startswith("gen_")]
    routes = {t["payload"]["route"] for t in gen}
    assert {"deterministic_sql_template", "rag_agent", "clarification",
            "access_refusal"} <= routes
    # role-scoped: no generated trace answers a table outside its role policy
    from nexus_platform.access_policy import get_policy
    for t in gen:
        if t["payload"]["route"] == "deterministic_sql_template":
            allowed = set(get_policy(t["role"]).allowed_tables)
            assert set(t["payload"].get("tables_touched") or []) <= allowed


def test_history_rerun_replaces_not_duplicates():
    from nexus_platform.scale.history import generate_history
    generate_history("medcore", per_company=200, days=30)
    first = len([t for t in store.list_traces_with_payload("medcore", limit=100000)
                 if str(t["id"]).startswith("gen_")])
    generate_history("medcore", per_company=200, days=30)
    second = len([t for t in store.list_traces_with_payload("medcore", limit=100000)
                  if str(t["id"]).startswith("gen_")])
    assert abs(first - second) <= first * 0.2  # replaced, not accumulated 2x


# ── PostgreSQL parity ────────────────────────────────────────────────────

@pytest.mark.skipif(not _pg_available(), reason="local PostgreSQL not running")
def test_postgres_matches_sqlite_answers(monkeypatch):
    """The same deterministic question must produce the same number on both
    backends — proves the PG data layer is real, not a label."""
    from nexus_platform import db
    from nexus_platform.access_policy import get_policy
    from nexus_platform.auth import AccessContext
    from nexus_platform.deterministic import execute, parse_intent

    reg = get_registry()
    e = reg.employees["analyst@acmecloud.test"]
    ctx = AccessContext(employee=e, company=reg.get_company("acmecloud"),
                        policy=get_policy("Analyst"))

    monkeypatch.delenv("NEXUSIQ_PLATFORM_PG_URL", raising=False)
    db.reset_engines()
    sqlite_out = execute(ctx, parse_intent("What was total revenue in Q3 2024?"))

    monkeypatch.setenv("NEXUSIQ_PLATFORM_PG_URL", PG_URL)
    db.reset_engines()
    assert db.dialect_name("acmecloud") == "postgresql"
    pg_out = execute(ctx, parse_intent("What was total revenue in Q3 2024?"))

    monkeypatch.delenv("NEXUSIQ_PLATFORM_PG_URL", raising=False)
    db.reset_engines()

    assert sqlite_out["rows"][0]["value"] == pytest.approx(
        pg_out["rows"][0]["value"], rel=1e-9)


@pytest.mark.skipif(not _pg_available(), reason="local PostgreSQL not running")
def test_postgres_schema_scale(monkeypatch):
    """Company schemas in PG carry the promised scale: 30+ tables, 100k+ rows."""
    eng = create_engine(PG_URL)
    with eng.connect() as conn:
        for slug in ("acmecloud", "medcore", "finpilot"):
            tables = [r[0] for r in conn.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :s"), {"s": slug})]
            assert len(tables) >= 30, f"{slug}: {len(tables)} tables"
            total = 0
            for t in tables:
                total += conn.execute(
                    text(f'SELECT COUNT(*) FROM "{slug}"."{t}"')).scalar()
            assert total >= 100_000, f"{slug}: {total} rows"
    eng.dispose()
