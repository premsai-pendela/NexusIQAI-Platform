"""Platform API tests: login routing, company isolation, feedback, traces.

The query engine is monkeypatched — these tests prove the access/product
layer, not the LLM. Engine-boundary behavior is covered by
test_sql_boundary.py, test_rag_boundary.py, and scripts/platform_smoke.py.
"""

import os

import pytest
from fastapi.testclient import TestClient

os.environ["NEXUSIQ_PREWARM_LIVE"] = "false"

from api.main import app  # noqa: E402
from nexus_platform import store  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _login(client, email, password):
    return client.post("/api/v1/platform/login",
                       json={"email": email, "password": password})


def _hdr(token):
    return {"X-NexusIQ-Session": token}


@pytest.fixture(scope="module")
def acme_admin(client):
    return _login(client, "admin@acmecloud.test", "demo-admin-2026").json()["token"]


@pytest.fixture(scope="module")
def acme_analyst(client):
    return _login(client, "analyst@acmecloud.test", "demo-analyst-2026").json()["token"]


@pytest.fixture(scope="module")
def medcore_ceo(client):
    return _login(client, "ceo@medcore.test", "demo-ceo-2026").json()["token"]


# ── Login routing ───────────────────────────────────────────────────────

def test_login_routes_to_company(client):
    r = _login(client, "analyst@acmecloud.test", "demo-analyst-2026")
    assert r.status_code == 200
    profile = r.json()["profile"]
    assert profile["company"]["slug"] == "acmecloud"
    assert profile["role"] == "Analyst"
    assert profile["access"]["read_only"] is True


def test_login_wrong_password(client):
    assert _login(client, "analyst@acmecloud.test", "nope").status_code == 401


def test_login_unknown_employee(client):
    assert _login(client, "ghost@acmecloud.test", "demo").status_code == 401


def test_tampered_token_rejected(client, acme_analyst):
    bad = acme_analyst[:-4] + "beef"
    assert client.get("/api/v1/platform/me", headers=_hdr(bad)).status_code == 401


def test_missing_token_rejected(client):
    assert client.get("/api/v1/platform/me").status_code == 401


# ── Workspace role filtering ────────────────────────────────────────────

def test_analyst_workspace_hides_hr(client, acme_analyst):
    ws = client.get("/api/v1/platform/workspace", headers=_hdr(acme_analyst)).json()
    assert "employees_hr" not in ws["tables"]
    assert "orders" in ws["tables"]
    depts = {d["department"] for d in ws["documents"]}
    assert "hr" not in depts


def test_admin_workspace_sees_all(client, acme_admin):
    ws = client.get("/api/v1/platform/workspace", headers=_hdr(acme_admin)).json()
    assert "employees_hr" in ws["tables"]
    depts = {d["department"] for d in ws["documents"]}
    assert "hr" in depts


def test_employee_workspace_hides_rebuild_internals(client, acme_analyst):
    ws = client.get("/api/v1/platform/workspace", headers=_hdr(acme_analyst)).json()
    assert "changed_files" not in ws["brain"]


# ── Admin-only surfaces ─────────────────────────────────────────────────

def test_rebuild_denied_for_analyst(client, acme_analyst):
    r = client.post("/api/v1/platform/brain/rebuild", headers=_hdr(acme_analyst))
    assert r.status_code == 403


def test_brain_status_admin_only(client, acme_analyst, acme_admin):
    assert client.get("/api/v1/platform/brain/status",
                      headers=_hdr(acme_analyst)).status_code == 403
    r = client.get("/api/v1/platform/brain/status", headers=_hdr(acme_admin))
    assert r.status_code == 200
    assert r.json()["status"] in ("ready", "needs_rebuild", "not_built")


# ── Feedback: company-scoped review ─────────────────────────────────────

def test_feedback_flow_and_isolation(client, acme_analyst, acme_admin, medcore_ceo):
    r = client.post("/api/v1/platform/feedback", headers=_hdr(acme_analyst),
                    json={"category": "missing-data",
                          "message": "Need access to invoice aging detail",
                          "page": "ask"})
    assert r.status_code == 200
    fid = r.json()["feedback_id"]

    # Admin of same company sees it
    listing = client.get("/api/v1/platform/admin/feedback",
                         headers=_hdr(acme_admin)).json()["feedback"]
    assert any(f["id"] == fid for f in listing)
    assert all(f["company"] == "acmecloud" for f in listing)

    # CEO of another company never sees it
    other = client.get("/api/v1/platform/admin/feedback",
                       headers=_hdr(medcore_ceo)).json()["feedback"]
    assert all(f["company"] == "medcore" for f in other)
    assert not any(f["id"] == fid for f in other)

    # Cross-company status update fails
    r = client.patch(f"/api/v1/platform/admin/feedback/{fid}",
                     headers=_hdr(medcore_ceo), json={"status": "reviewed"})
    assert r.status_code == 404

    # Same-company status update works
    r = client.patch(f"/api/v1/platform/admin/feedback/{fid}",
                     headers=_hdr(acme_admin), json={"status": "reviewed"})
    assert r.status_code == 200


def test_feedback_review_admin_only(client, acme_analyst):
    r = client.get("/api/v1/platform/admin/feedback", headers=_hdr(acme_analyst))
    assert r.status_code == 403


# ── Traces: employee/company scoping ────────────────────────────────────

def test_trace_scoping(client, acme_admin, acme_analyst, medcore_ceo):
    tid = store.save_trace("acmecloud", "analyst@acmecloud.test", "Analyst",
                           "test question", "allowed",
                           {"employee": "analyst@acmecloud.test", "role": "Analyst"})

    # Owner can read own trace
    assert client.get(f"/api/v1/platform/traces/{tid}",
                      headers=_hdr(acme_analyst)).status_code == 200
    # Same-company admin can read it
    assert client.get(f"/api/v1/platform/traces/{tid}",
                      headers=_hdr(acme_admin)).status_code == 200
    # Other company CEO cannot — 404, not even existence is revealed
    assert client.get(f"/api/v1/platform/traces/{tid}",
                      headers=_hdr(medcore_ceo)).status_code == 404

    # Admin trace list is company-scoped and filterable by employee
    traces = client.get("/api/v1/platform/admin/traces",
                        params={"employee": "analyst@acmecloud.test"},
                        headers=_hdr(acme_admin)).json()["traces"]
    assert any(t["id"] == tid for t in traces)
    assert all(t["company"] == "acmecloud" for t in traces)


def test_employee_cannot_read_others_trace(client, acme_analyst):
    tid = store.save_trace("acmecloud", "hr@acmecloud.test", "HR",
                           "hr question", "allowed", {"employee": "hr@acmecloud.test"})
    r = client.get(f"/api/v1/platform/traces/{tid}", headers=_hdr(acme_analyst))
    assert r.status_code == 403


def test_admin_traces_denied_for_employee(client, acme_analyst):
    assert client.get("/api/v1/platform/admin/traces",
                      headers=_hdr(acme_analyst)).status_code == 403


# ── Query endpoint (engine mocked) ──────────────────────────────────────

def test_query_uses_server_side_context(client, acme_analyst, monkeypatch):
    captured = {}

    def fake_run_query(ctx, question, session_id, repeat_action=None):
        captured["company"] = ctx.company.slug
        captured["role"] = ctx.employee.role
        return {"answer": "42", "confidence": "HIGH", "source_type": "sql_only",
                "sources": [], "platform": {"trace_id": "tr_x", "refused": False,
                                            "access_decision": "allowed",
                                            "resolved_question": question,
                                            "followup_rewritten": False,
                                            "chart": None, "role": ctx.employee.role,
                                            "company": ctx.company.name}}

    import nexus_platform.query_service as qs
    monkeypatch.setattr(qs, "run_query", fake_run_query)
    r = client.post("/api/v1/platform/query", headers=_hdr(acme_analyst),
                    json={"question": "What was revenue in Q3?",
                          "session_id": "test-session"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "42"
    assert body["platform"]["trace_id"] == "tr_x"
    # Context came from the token, not the request body
    assert captured == {"company": "acmecloud", "role": "Analyst"}


# ── Memory isolation ────────────────────────────────────────────────────

def test_memory_isolation():
    store.save_turn("acmecloud", "a@x.test", "s1", "q1", "q1", "ans", "sql", None, False)
    store.save_turn("medcore", "b@y.test", "s1", "secret medcore q", "q", "ans", "sql", None, False)
    turns = store.recent_turns("acmecloud", "a@x.test", "s1")
    assert all(t["company"] == "acmecloud" for t in turns)
    assert not any("medcore" in t["question"] for t in turns)
    # Same employee, different session: no bleed
    assert store.recent_turns("acmecloud", "a@x.test", "s2") == []
    # Same company, different employee: no bleed
    assert store.recent_turns("acmecloud", "other@x.test", "s1") == []


# ── Analyst Health Check (Admin/CEO only) ───────────────────────────────

def test_admin_can_run_health_check(client, acme_admin):
    r = client.post("/api/v1/platform/admin/health-check",
                    headers=_hdr(acme_admin), json={"window_days": 30})
    assert r.status_code == 200
    body = r.json()
    assert body["company"] == "acmecloud"
    assert "findings" in body and "summary" in body and "stats" in body
    assert body["llm_summary_status"] == "not_requested"
    rid = body["report_id"]

    lst = client.get("/api/v1/platform/admin/health-reports",
                     headers=_hdr(acme_admin)).json()["reports"]
    assert any(rep["id"] == rid for rep in lst)

    detail = client.get(f"/api/v1/platform/admin/health-reports/{rid}",
                        headers=_hdr(acme_admin))
    assert detail.status_code == 200


def test_non_admin_cannot_run_health_check(client, acme_analyst):
    r = client.post("/api/v1/platform/admin/health-check",
                    headers=_hdr(acme_analyst), json={})
    assert r.status_code == 403


def test_health_report_is_company_scoped(client, acme_admin, medcore_ceo):
    rid = client.post("/api/v1/platform/admin/health-check",
                      headers=_hdr(acme_admin), json={}).json()["report_id"]
    r = client.get(f"/api/v1/platform/admin/health-reports/{rid}",
                   headers=_hdr(medcore_ceo))
    assert r.status_code == 404
