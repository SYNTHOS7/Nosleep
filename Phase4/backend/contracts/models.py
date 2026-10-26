"""Canonical domain models and contracts for Knowledge Base."""

from __future__ import annotations

from datetime import datetime, timezone
import time
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware UTC")
    return value


class ContractModel(BaseModel):
    """Immutable transport value object."""
    model_config = ConfigDict(extra="ignore", validate_assignment=True)


class OperationType(str, Enum):
    ADD = "ADD"
    EDIT = "EDIT"
    DELETE = "DELETE"


class OperationStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    PARSING = "PARSING"
    CHUNKING = "CHUNKING"
    EXTRACTING = "EXTRACTING"
    EMBEDDING = "EMBEDDING"
    VALIDATING = "VALIDATING"
    STAGED = "STAGED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Element(BaseModel):
    """An element extracted from a document with page and order preservation."""
    element_id: str
    page_number: int = Field(ge=1, description="One-based page number")
    element_type: str = "NarrativeText"
    text: str
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)


class ParsedSource(BaseModel):
    """Normalized parse result for a source file."""
    source_ref: str
    source_type: Literal["pdf", "txt"]
    content_hash: str
    byte_size: int = Field(ge=0)
    page_count: int = Field(ge=1)
    elements: List[Element] = Field(default_factory=list)
    normalized_text: str
    provider_job_id: Optional[str] = None


class Document(BaseModel):
    """Canonical document record."""
    id: str
    workspace_id: str
    source_name: str
    source_type: Literal["pdf", "txt"]
    content_hash: str
    revision: int = Field(default=1, ge=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    """A deterministic chunk of text with exact page and offset provenance."""
    id: str
    workspace_id: str
    document_id: str
    revision: int = Field(default=1, ge=1)
    chunk_index: int = Field(ge=0)
    page_number: int = Field(ge=1, description="One-based page number, cross-page merge prohibited")
    text: str
    token_count: int = Field(ge=0)
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    element_ids: List[str] = Field(default_factory=list)
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Entity(BaseModel):
    """Canonical entity mention."""
    id: str
    name: str
    label: str
    source_chunk_id: str
    properties: Dict[str, Any] = Field(default_factory=dict)


class ValueNode(BaseModel):
    """Canonical value node for dates, quantities, and statuses."""
    id: str
    val_type: str  # date, quantity, status, version, etc.
    raw_value: str
    normalized_value: Optional[str] = None
    source_chunk_id: str


class Provenance(BaseModel):
    """Exact evidence provenance linking an assertion to a chunk quote."""
    source_chunk_id: str
    exact_quote: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    extraction_method: str = "neo4j-graphrag-adapter"


class Relation(BaseModel):
    """Canonical relationship with modality, polarity, and exact quote provenance."""
    id: str
    source_entity_name: str
    source_entity_label: str
    predicate: str
    target_entity_name: Optional[str] = None
    target_entity_label: Optional[str] = None
    target_value_id: Optional[str] = None
    polarity: Literal["AFFIRMATIVE", "NEGATIVE"] = "AFFIRMATIVE"
    modality: Literal["CERTAIN", "CONDITIONAL", "POSSIBLE"] = "CERTAIN"
    condition: Optional[str] = None
    temporal_qualifier: Optional[str] = None
    provenance: Provenance
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class CandidateGraph(BaseModel):
    """Extracted graph candidates from a single chunk."""
    chunk_id: str
    entities: List[Entity] = Field(default_factory=list)
    values: List[ValueNode] = Field(default_factory=list)
    relations: List[Relation] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    is_empty: bool = False


class ExtractionBatch(BaseModel):
    """Batch staged for downstream consumption."""
    operation_id: str
    workspace_id: str
    document: Document
    revision: int
    chunks: List[Chunk]
    candidate_graphs: List[CandidateGraph]
    aggregated_entities: List[Entity]
    aggregated_relations: List[Relation]
    aggregated_values: List[ValueNode]
    vectors: Dict[str, List[float]] = Field(default_factory=dict)  # chunk_id -> vector
    warnings: List[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    status: Literal["STAGED", "FAILED"] = "STAGED"


class Operation(BaseModel):
    """A durable operation tracking add/edit/delete lifecycle with stage timings."""
    id: str
    workspace_id: str
    document_id: str
    operation_type: OperationType
    source_ref: Optional[str] = None
    source_type: Optional[Literal["pdf", "txt"]] = None
    status: OperationStatus = OperationStatus.PENDING
    stage_timings: Dict[str, float] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    checkpoint_path: Optional[str] = None
    error_message: Optional[str] = None
    accepted_at: float = Field(default_factory=time.time)
    ready_at: Optional[float] = None
    current_revision: int = 1
    new_revision: int = 1
    old_affected_records: Dict[str, Any] = Field(default_factory=dict)
    new_affected_records: Dict[str, Any] = Field(default_factory=dict)


class Topic(BaseModel):
    """Persistent topic record for thematic clustering."""
    id: str
    workspace_id: str
    label: str
    slug: str
    description: str
    discovery_method: str = "HDBSCAN+LLM"
    model_version: str = "v1"
    cluster_version: str = "v1"
    created_at: float = Field(default_factory=time.time)


class TopicAssignment(BaseModel):
    """Topic membership linking a chunk to a topic."""
    topic_id: str
    chunk_id: str
    confidence: float = 1.0
    method: str = "vector_clustering"
    model_version: str = "v1"


# Canonical Phase 1 compatibility exports for storage adapters (Neo4j / Chroma)
try:
    from Phase1.backend.contracts.models import (
        ChunkLocation,
        Conflict,
        ConflictKind,
        ConflictState,
        EntityMention,
        Evidence,
        OperationKind,
        OperationState,
        Revision,
        RevisionState,
        TopicMembership,
        Value,
    )
except ImportError:
    pass
