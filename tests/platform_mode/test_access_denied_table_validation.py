"""Regression test for hf_fbccccb7e2: an ACCESS_DENIED_TABLE error naming a
table that isn't in the real catalog (e.g. a hallucinated 'traces' table from
a garbled query like "what were our expnses for quater 5?") must not be
treated as a genuine role-restricted-table refusal. Only a table that is
actually in access_policy.ALL_TABLES should produce the role-refusal wording;
anything else is unknown/hallucinated and must be handled generically.
"""

from nexus_platform import access_policy
from nexus_platform.query_service import _is_access_denied


def test_hallucinated_table_is_not_resolved_as_real_denial():
    result = {"sql_result": {"error": "ACCESS_DENIED_TABLE: 'traces'"}}
    denied = _is_access_denied(result)
    assert "traces" not in access_policy.ALL_TABLES
    assert denied != "traces"
    assert denied not in access_policy.ALL_TABLES


def test_real_restricted_table_produces_role_refusal_wording():
    result = {"sql_result": {"error": "ACCESS_DENIED_TABLE: 'employees_hr'"}}
    denied = _is_access_denied(result)
    assert denied == "employees_hr"
    assert denied in access_policy.ALL_TABLES
    message = access_policy.refusal_message(
        "Finance", "MedCore Systems",
        detail=f"the '{denied}' data area is outside your role")
    assert "outside your role" in message


def test_no_denial_returns_none():
    assert _is_access_denied({"sql_result": {"error": ""}}) is None
    assert _is_access_denied({"sql_result": {}}) is None
    assert _is_access_denied({}) is None
