"""Access-policy unit tests: role boundaries, refusals, restricted intent."""

import pytest

from nexus_platform.access_policy import (classify_restricted_intent,
                                          get_policy, refusal_message)


def test_admin_sees_everything():
    p = get_policy("Admin")
    assert "employees_hr" in p.allowed_tables
    assert "hr" in p.allowed_departments


def test_analyst_cannot_see_hr():
    p = get_policy("Analyst")
    assert "employees_hr" not in p.allowed_tables
    assert "hr" not in p.allowed_departments
    assert "orders" in p.allowed_tables


def test_hr_cannot_see_revenue():
    p = get_policy("HR")
    assert p.allowed_tables == ("employees_hr",)
    assert "finance" not in p.allowed_departments


def test_unknown_role_denied_by_default():
    p = get_policy("Intern")
    assert p.allowed_tables == ()
    assert p.allowed_departments == ()


@pytest.mark.parametrize("question,role,expect_denied", [
    ("How many employees were terminated in 2024?", "Analyst", True),
    ("What is the average salary band distribution?", "Analyst", True),
    ("How many PTO days do employees get?", "Analyst", True),
    ("What was total revenue in Q3 2024?", "Analyst", False),
    ("What was total revenue in Q3 2024?", "HR", True),
    ("Show overdue invoices by month", "HR", True),
    ("What is our attrition rate?", "HR", False),
    ("What are the support SLA targets?", "Support", False),
    ("Show me revenue by region", "Support", True),
])
def test_restricted_intent(question, role, expect_denied):
    reason = classify_restricted_intent(question, get_policy(role))
    assert (reason is not None) == expect_denied, f"{role}: {question} → {reason}"


def test_refusal_message_is_polite_and_specific():
    msg = refusal_message("HR", "AcmeCloud Analytics")
    assert "access level" in msg
    assert "HR role" in msg
    assert "AcmeCloud Analytics" in msg
    assert "Feedback" in msg
