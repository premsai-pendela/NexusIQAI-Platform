"""RAG boundary tests: department filters on vector, hybrid, and BM25 paths.

Loads the shared embedding model once (module scope); no LLM calls.
"""

import pytest

from nexus_platform.contexts import context_key, register_company_contexts


@pytest.fixture(scope="module", autouse=True)
def _register():
    register_company_contexts()


@pytest.fixture(scope="module")
def analyst_rag():
    from agents.rag_agent import get_rag_agent
    return get_rag_agent(context_key("acmecloud", "Analyst"))


@pytest.fixture(scope="module")
def hr_rag():
    from agents.rag_agent import get_rag_agent
    return get_rag_agent(context_key("acmecloud", "HR"))


def test_hr_can_retrieve_hr_docs(hr_rag):
    chunks = hr_rag.search_documents("How many PTO days do employees get?", n_results=4)
    assert chunks, "HR should retrieve HR policy chunks"
    assert any(c.get("department") == "hr" for c in chunks)


def test_analyst_never_retrieves_hr_docs(analyst_rag):
    chunks = analyst_rag.search_documents(
        "How many PTO days and parental leave weeks do employees get?", n_results=6)
    assert all(c.get("department") != "hr" for c in chunks)


def test_analyst_retrieves_allowed_departments(analyst_rag):
    chunks = analyst_rag.search_documents("What are the support SLA targets?", n_results=4)
    assert any(c.get("department") == "support" for c in chunks)


def test_hybrid_search_respects_boundary(analyst_rag):
    results = analyst_rag.hybrid_search("salary band PTO parental leave policy", n_results=6)
    assert all(r.get("department") != "hr" for r in results)


def test_bm25_index_excludes_restricted_chunks(analyst_rag):
    joined = " ".join(analyst_rag.bm25_documents).lower()
    assert "parental leave" not in joined, "HR doc text leaked into Analyst BM25 index"


def test_hr_bm25_has_hr_only_departments(hr_rag):
    depts = {m.get("department") for m in hr_rag.bm25_metadatas}
    assert depts <= {"general", "hr"}


def test_company_collections_are_separate(analyst_rag):
    metas = analyst_rag.bm25_metadatas
    assert all(m.get("company") == "acmecloud" for m in metas)
