from pydantic import BaseModel, Field
from typing import Optional, Literal, List, Any
from datetime import datetime


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)
    source: Literal["auto", "sql", "rag", "web", "all"] = "auto"
    session_id: Optional[str] = None


class SourceCitation(BaseModel):
    type: str  # "sql", "rag", "web"
    content: str
    filename: Optional[str] = None


class SqlEvidence(BaseModel):
    success: bool = False
    query: Optional[str] = None
    row_count: Optional[int] = None
    result_preview: List[dict] = []
    answer_mode: Optional[str] = None
    repair_attempted: bool = False
    error: Optional[str] = None
    time_s: Optional[float] = None


class DocumentEvidence(BaseModel):
    filename: Optional[str] = None
    page: Optional[Any] = None
    relevance: Optional[float] = None
    cited_in_answer: bool = False
    snippet: Optional[str] = None


class WebEvidence(BaseModel):
    source: Optional[str] = None
    category: Optional[str] = None
    products: Optional[int] = None
    sample_data: bool = False


class Evidence(BaseModel):
    sql: Optional[SqlEvidence] = None
    documents: List[DocumentEvidence] = []
    web: List[WebEvidence] = []


class Usage(BaseModel):
    llm_calls: Optional[int] = None
    avoided_llm_calls: Optional[int] = None
    avoided_estimated_tokens: Optional[int] = None
    estimated_tokens: Optional[int] = None
    actual_tokens: Optional[int] = None
    answer_mode: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    confidence: str  # HIGH / MEDIUM / LOW / UNKNOWN
    confidence_reason: Optional[str] = None
    route: str
    sources: List[SourceCitation]
    evidence: Optional[Evidence] = None
    # Deterministic analyst notes (breakdowns, prior-period trend) for
    # aggregate questions; None when not applicable. Never LLM-generated.
    analysis: Optional[dict] = None
    usage: Optional[Usage] = None
    query_time_s: Optional[float] = None
    latency_ms: float
    trace_id: Optional[str] = None
    cached: bool = False
    request_id: str


class StreamEvent(BaseModel):
    step: str
    status: str
    data: dict = {}
    elapsed_ms: float


class HealthResponse(BaseModel):
    status: str  # "healthy" / "degraded"
    agents: dict
    production_features: dict = {}
    chroma_chunks: int
    cache_entries: int
    uptime_seconds: float
    timestamp: str


class ErrorResponse(BaseModel):
    error: str
    detail: str
    request_id: str
