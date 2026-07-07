"""SQL boundary tests: schema subset + AST table allowlist (no LLM calls)."""

import pytest

from nexus_platform.contexts import build_context


@pytest.fixture(scope="module")
def analyst_agent():
    from agents.sql_agent import SQLAgent
    return SQLAgent(mode="development", data_context=build_context("acmecloud", "Analyst"))


@pytest.fixture(scope="module")
def hr_agent():
    from agents.sql_agent import SQLAgent
    return SQLAgent(mode="development", data_context=build_context("acmecloud", "HR"))


def test_analyst_schema_excludes_hr_table(analyst_agent):
    assert "employees_hr" not in analyst_agent.schema_context
    assert "orders" in analyst_agent.schema_context


def test_hr_schema_only_hr_table(hr_agent):
    assert "employees_hr" in hr_agent.schema_context
    assert "TABLE: orders" not in hr_agent.schema_context


def test_analyst_denied_hr_table_in_ast(analyst_agent):
    ok, err = analyst_agent._validate_query("SELECT COUNT(*) FROM employees_hr")
    assert not ok and "ACCESS_DENIED_TABLE" in err


def test_analyst_denied_join_leak(analyst_agent):
    ok, err = analyst_agent._validate_query(
        "SELECT o.region, COUNT(e.emp_id) FROM orders o JOIN employees_hr e "
        "ON o.region = e.region GROUP BY o.region"
    )
    assert not ok and "ACCESS_DENIED_TABLE" in err


def test_analyst_allowed_query_passes(analyst_agent):
    ok, err = analyst_agent._validate_query(
        "SELECT SUM(total_amount) FROM orders WHERE status='completed'")
    assert ok, err


def test_cte_alias_not_mistaken_for_table(analyst_agent):
    ok, err = analyst_agent._validate_query(
        "WITH q3 AS (SELECT * FROM orders) SELECT COUNT(*) FROM q3")
    assert ok, err


def test_destructive_sql_still_denied(hr_agent):
    ok, err = hr_agent._validate_query("DELETE FROM employees_hr")
    assert not ok


def test_hr_denied_orders(hr_agent):
    ok, err = hr_agent._validate_query("SELECT SUM(total_amount) FROM orders")
    assert not ok and "ACCESS_DENIED_TABLE" in err
