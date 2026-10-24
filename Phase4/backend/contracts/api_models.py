"""Person 4 API response and request models."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from backend.contracts.models import OperationStatus, OperationType


class MutationReceipt(BaseModel):
    """Response returned upon accepting a document mutation (HTTP 202)."""
    status: Literal["accepted"] = "accepted"
    operation_id: str
    document_id: str
    workspace_id: str
    accepted_at: float = Field(default_factory=time.time)
    retry_after: int = 1


class OperationView(BaseModel):
    """Status and metrics of an ingestion/mutation operation."""
    id: str
    workspace_id: str
    document_id: str
    status: OperationStatus
    operation_type: OperationType
    stage_timings: Dict[str, float] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    accepted_at: float
    ready_at: Optional[float] = None


class QueryRequest(BaseModel):
    """Grounded query request with optional topic filter."""
    query: str
    workspace_id: str
    topic_ids: Optional[List[str]] = None
    top_k: int = 5


class SourceView(BaseModel):
    """Source provenance record for evidence citation."""
    chunk_id: str
    document_id: str
    source_name: str
    page_number: int = 1
    start_char: int = 0
    end_char: int = 0
    exact_quote: str = ""
    revision: int = 1


class GraphNode(BaseModel):
    """Visualizable node in the knowledge graph."""
    id: str
    label: str
    name: str
    type: str = "entity"  # "entity", "chunk", "document", "topic", "value"
    properties: Dict[str, Any] = Field(default_factory=dict)
    topic_id: Optional[str] = None
    document_id: Optional[str] = None
    conflict_status: Optional[str] = None  # None, "conflicting"


class GraphEdge(BaseModel):
    """Visualizable edge in the knowledge graph."""
    id: str
    source: str
    target: str
    predicate: str
    edge_type: Literal["factual", "topic_membership", "provenance"] = "factual"
    polarity: Literal["AFFIRMATIVE", "NEGATIVE"] = "AFFIRMATIVE"
    modality: Literal["CERTAIN", "CONDITIONAL", "POSSIBLE"] = "CERTAIN"
    exact_quote: Optional[str] = None
    provenance: Optional[Dict[str, Any]] = None
    conflict_status: Optional[str] = None  # None, "conflicting"


class GraphSlice(BaseModel):
    """Graph neighborhood relevant to the query or UI canvas."""
    nodes: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)
    highlighted_path_ids: List[str] = Field(default_factory=list)


class ConflictPair(BaseModel):
    """Two conflicting statements and their respective source attributions."""
    statement_a: str
    source_a: Dict[str, Any]
    statement_b: str
    source_b: Dict[str, Any]
    description: str


class QueryResponse(BaseModel):
    """Fully grounded response with exact citations, graph paths, and conflict detection."""
    answer: str
    source_chunks: List[SourceView] = Field(default_factory=list)
    graph_path: GraphSlice
    topic_scope_used: List[str] = Field(default_factory=list)
    limitations: Optional[str] = None
    conflict_detected: bool = False
    conflicts: List[ConflictPair] = Field(default_factory=list)


class TopicView(BaseModel):
    """Exposed topic representation for UI and filtering."""
    id: str
    workspace_id: str
    label: str
    slug: str
    description: str
    chunk_count: int = 0
    entity_count: int = 0


class TopicList(BaseModel):
    """List of discovered topics for a workspace."""
    workspace_id: str
    topics: List[TopicView] = Field(default_factory=list)
    total: int = 0


class HealthResponse(BaseModel):
    """Health check response exposing readiness and pinned versions, no secrets."""
    status: Literal["healthy", "degraded", "unhealthy"] = "healthy"
    components: Dict[str, Dict[str, Any]]
    pinned_versions: Dict[str, str]


class ErrorResponse(BaseModel):
    """Typed error envelope."""
    error_code: str
    message: str
    details: Optional[Dict[str, Any]] = None
