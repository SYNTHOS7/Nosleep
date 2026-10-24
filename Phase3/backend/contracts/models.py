"""
Core data contracts for Knowledge Graph system.
Conforms strictly to 01-storage-contracts-lifecycle.md and 03-topics-retrieval-answers-and-conflicts.md.
Uses Pydantic v2 with extra='forbid', UTC timestamps, JSON-safe structures.
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ContractBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Location(ContractBaseModel):
    page: Optional[int] = None
    element_ids: List[str] = Field(default_factory=list)
    start_offset: int
    end_offset: int


class Evidence(ContractBaseModel):
    chunk_id: str
    start: int
    end: int
    quote: str


class Document(ContractBaseModel):
    id: str
    workspace_id: str
    filename: str
    source_type: Literal["pdf", "txt"]
    active_revision_id: Optional[str] = None
    deleted: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class Revision(ContractBaseModel):
    id: str
    document_id: str
    content_hash: str
    parser_version: str
    chunker_version: str
    extractor_version: str
    embedding_version: str
    state: Literal["staged", "published", "retired", "failed"]
    source_ref: str
    created_at: datetime = Field(default_factory=utc_now)


class Chunk(ContractBaseModel):
    id: str
    workspace_id: str
    document_id: str
    revision_id: str
    index: int
    text: str
    text_hash: str
    location: Location


class Entity(ContractBaseModel):
    id: str
    workspace_id: str
    name: str
    normalized_name: str
    type: str
    aliases: List[str] = Field(default_factory=list)


class Value(ContractBaseModel):
    id: str
    workspace_id: str
    kind: Literal["text", "number", "date"]
    lexical_value: str
    normalized_value: str
    unit: Optional[str] = None


class Relation(ContractBaseModel):
    id: str
    workspace_id: str
    revision_id: str
    subject_id: str
    object_entity_id: Optional[str] = None
    object_value_id: Optional[str] = None
    predicate: str
    predicate_original: str
    polarity: Literal["positive", "negative"] = "positive"
    modality: Literal["asserted", "possible", "planned", "conditional"] = "asserted"
    condition: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    evidence: Evidence
    extraction_method: str = "llm"
    extraction_model: str
    extraction_version: str

    @model_validator(mode="after")
    def validate_xor_and_condition(self) -> Relation:
        # object_entity_id XOR object_value_id
        has_entity = self.object_entity_id is not None
        has_value = self.object_value_id is not None
        if has_entity == has_value:
            raise ValueError("Relation must have exactly one of object_entity_id XOR object_value_id")
        if self.modality == "conditional" and not self.condition:
            raise ValueError("Conditional relation requires condition")
        return self


class Topic(ContractBaseModel):
    id: str
    workspace_id: str
    label: str
    description: str
    cluster_version: str
    embedding_version: str
    centroid: List[float]
    representative_chunk_ids: List[str]
    summary_evidence_ids: List[str]
    summary_status: Literal["fresh", "needs_refresh"] = "fresh"
    active: bool = True


class TopicMembership(ContractBaseModel):
    topic_id: str
    chunk_id: str
    revision_id: str
    method: Literal["cluster", "centroid"]
    score: float
    assignment_version: str


class Conflict(ContractBaseModel):
    id: str
    workspace_id: str
    left_relation_id: str
    right_relation_id: str
    kind: Literal["negation", "exclusive_value", "incompatible_statement"]
    state: Literal["potential", "supported"]
    explanation: str
    evidence_chunk_ids: List[str]
    detector_version: str


class Operation(ContractBaseModel):
    id: str
    workspace_id: str
    document_id: str
    kind: Literal["add", "edit", "delete"]
    expected_revision_id: Optional[str] = None
    new_revision_id: Optional[str] = None
    state: Literal["queued", "running", "ready", "failed"]
    stage: str
    accepted_at: datetime = Field(default_factory=utc_now)
    visible_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    deadline_at: datetime
    checkpoint: Dict[str, Any] = Field(default_factory=dict)
    counts: Dict[str, int] = Field(default_factory=dict)
    timings_ms: Dict[str, float] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class QueryRequest(ContractBaseModel):
    workspace_id: str
    question: str
    topic_ids: List[str] = Field(default_factory=list)
    scope: Literal["workspace", "selected"] = "workspace"
    answer_language: Literal["auto", "en", "hi"] = "auto"
    top_k: int = Field(default=10, ge=1, le=30)
    max_hops: int = Field(default=2, ge=1, le=4)


class QueryPlan(ContractBaseModel):
    query_type: Literal["thematic", "local", "hybrid"]
    rationale_code: str
    query_language: Literal["en", "hi"]
    target_topic_ids: List[str] = Field(default_factory=list)
    use_vector: bool = True
    use_lexical: bool = True
    use_graph: bool = True
    max_hops: int = 2
    top_k: int = 10


class AnswerStatement(ContractBaseModel):
    statement_text: str
    citation_chunk_ids: List[str] = Field(default_factory=list)
    citation_path_ids: List[str] = Field(default_factory=list)
    is_inference: bool = False
    confidence: float = 1.0
    contradiction_ref_ids: List[str] = Field(default_factory=list)


class ProvenanceLink(ContractBaseModel):
    chunk_id: str
    revision_id: str
    document_id: str


class GraphNodeView(ContractBaseModel):
    id: str
    label: str
    node_type: str
    properties: Dict[str, Any] = Field(default_factory=dict)


class GraphEdgeView(ContractBaseModel):
    id: str
    source_id: str
    target_id: str
    predicate: str
    relation_id: Optional[str] = None
    source_chunk_id: Optional[str] = None
    is_topic_membership: bool = False
    properties: Dict[str, Any] = Field(default_factory=dict)


class EvidencePath(ContractBaseModel):
    path_id: str
    node_ids: List[str] = Field(default_factory=list)
    edges: List[GraphEdgeView] = Field(default_factory=list)
    provenance_links: List[ProvenanceLink] = Field(default_factory=list)


class GraphSlice(ContractBaseModel):
    nodes: List[GraphNodeView] = Field(default_factory=list)
    edges: List[GraphEdgeView] = Field(default_factory=list)
    truncated: bool = False


class EvidencePackage(ContractBaseModel):
    workspace_id: str
    corpus_epoch: int
    chunks: List[Chunk] = Field(default_factory=list)
    relations: List[Relation] = Field(default_factory=list)
    entities: List[Entity] = Field(default_factory=list)
    values: List[Value] = Field(default_factory=list)
    paths: List[EvidencePath] = Field(default_factory=list)
    topics: List[Topic] = Field(default_factory=list)
    conflicts: List[Conflict] = Field(default_factory=list)
    truncated: bool = False
    searched_count: int = 0
    available_count: int = 0
    limitations: List[str] = Field(default_factory=list)


class QueryResponse(ContractBaseModel):
    request_id: str
    corpus_epoch: int
    status: Literal["answered", "insufficient_evidence", "retry_required"]
    language: Literal["en", "hi"]
    plan: QueryPlan
    statements: List[AnswerStatement] = Field(default_factory=list)
    evidence: EvidencePackage
    graph: GraphSlice
    latency_ms: float
    warnings: List[str] = Field(default_factory=list)


class DerivedDelta(ContractBaseModel):
    operation_id: str
    staged_revision_id: str
    new_topics: List[Topic] = Field(default_factory=list)
    updated_topics: List[Topic] = Field(default_factory=list)
    new_memberships: List[TopicMembership] = Field(default_factory=list)
    deleted_membership_ids: List[Tuple[str, str]] = Field(default_factory=list)
    new_conflicts: List[Conflict] = Field(default_factory=list)
    retired_conflict_ids: List[str] = Field(default_factory=list)
