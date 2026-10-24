"""Pydantic v2 source of truth for cross-team data contracts."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ids import conflict_id, value_id

# Recursive JSON aliases trigger a schema-generation recursion in supported Pydantic
# versions. Runtime validation below enforces the JSON-safe contract for these fields.
JsonValue: TypeAlias = Any


def _assert_json_safe(value: Any, path: str = "$") -> None:
    """Reject non-JSON values and non-finite numbers in contract payloads."""
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must contain finite numbers")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json_safe(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings")
            _assert_json_safe(item, f"{path}.{key}")
        return
    raise ValueError(f"{path} must be JSON-safe")


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware UTC")
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError("timestamp must be UTC")
    return value


class ContractModel(BaseModel):
    """Immutable transport value object; reparse mutable containers at trust boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_assignment=True)


class SourceType(str, Enum):
    PDF = "pdf"
    TXT = "txt"


class RevisionState(str, Enum):
    STAGED = "staged"
    PUBLISHED = "published"
    RETIRED = "retired"
    FAILED = "failed"


class RelationPolarity(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class RelationModality(str, Enum):
    ASSERTED = "asserted"
    POSSIBLE = "possible"
    PLANNED = "planned"
    CONDITIONAL = "conditional"


class ValueKind(str, Enum):
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"


class TopicMembershipMethod(str, Enum):
    CLUSTER = "cluster"
    CENTROID = "centroid"


class ConflictKind(str, Enum):
    NEGATION = "negation"
    EXCLUSIVE_VALUE = "exclusive_value"
    INCOMPATIBLE_STATEMENT = "incompatible_statement"


class ConflictState(str, Enum):
    POTENTIAL = "potential"
    SUPPORTED = "supported"


class OperationKind(str, Enum):
    ADD = "add"
    EDIT = "edit"
    DELETE = "delete"


class OperationState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


class QueryScope(str, Enum):
    WORKSPACE = "workspace"
    SELECTED = "selected"


class AnswerLanguage(str, Enum):
    AUTO = "auto"
    EN = "en"
    HI = "hi"


class QueryStatus(str, Enum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    RETRY_REQUIRED = "retry_required"


class Document(ContractModel):
    id: str
    workspace_id: str
    filename: str
    source_type: SourceType
    active_revision_id: str | None = None
    deleted: bool = False
    created_at: datetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    _validate_created_at = field_validator("created_at")(_utc)

    @field_validator("metadata")
    @classmethod
    def metadata_is_json_safe(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _assert_json_safe(value)
        return value


class Revision(ContractModel):
    id: str
    document_id: str
    content_hash: str
    parser_version: str
    chunker_version: str
    extractor_version: str
    embedding_version: str
    state: RevisionState
    source_ref: str
    created_at: datetime

    _validate_created_at = field_validator("created_at")(_utc)


class ChunkLocation(ContractModel):
    page: int | None = Field(default=None, ge=1)
    element_ids: list[str] = Field(default_factory=list)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)

    @model_validator(mode="after")
    def offsets_are_ordered(self) -> "ChunkLocation":
        if self.end_offset < self.start_offset:
            raise ValueError("end_offset must be greater than or equal to start_offset")
        return self


class Chunk(ContractModel):
    id: str
    workspace_id: str
    document_id: str
    revision_id: str
    index: int = Field(ge=0)
    text: str
    text_hash: str
    location: ChunkLocation
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def location_is_within_text(self) -> "Chunk":
        if self.location.end_offset > len(self.text):
            raise ValueError("location end_offset must not exceed chunk text length")
        return self

    @field_validator("metadata")
    @classmethod
    def metadata_is_json_safe(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _assert_json_safe(value)
        return value


class Entity(ContractModel):
    id: str
    workspace_id: str
    name: str
    normalized_name: str
    type: str
    aliases: list[str] = Field(default_factory=list)


class EntityMention(ContractModel):
    """A source-bound occurrence of a canonical Entity."""

    id: str
    workspace_id: str
    document_id: str
    revision_id: str
    entity_id: str
    chunk_id: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    quote: str
    created_at: datetime

    _validate_created_at = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def offsets_are_ordered(self) -> "EntityMention":
        if self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        return self


class Value(ContractModel):
    id: str
    workspace_id: str
    kind: ValueKind
    lexical_value: str
    normalized_value: str
    unit: str | None = None

    @model_validator(mode="after")
    def id_is_canonical(self) -> "Value":
        if self.id != value_id(self.workspace_id, self.kind.value, self.normalized_value, self.unit):
            raise ValueError("value id must match its canonical normalized identity")
        return self


class Evidence(ContractModel):
    chunk_id: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    quote: str

    @model_validator(mode="after")
    def offsets_are_ordered(self) -> "Evidence":
        if self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        return self


class Relation(ContractModel):
    id: str
    workspace_id: str
    revision_id: str
    subject_id: str
    object_entity_id: str | None = None
    object_value_id: str | None = None
    predicate: str
    predicate_original: str
    polarity: RelationPolarity
    modality: RelationModality
    condition: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    evidence: Evidence
    extraction_method: str
    extraction_model: str
    extraction_version: str

    _validate_valid_from = field_validator("valid_from")(_utc)
    _validate_valid_to = field_validator("valid_to")(_utc)

    @model_validator(mode="after")
    def endpoint_and_condition_rules(self) -> "Relation":
        if (self.object_entity_id is None) == (self.object_value_id is None):
            raise ValueError("exactly one relation object endpoint is required")
        if self.modality is RelationModality.CONDITIONAL and not self.condition:
            raise ValueError("conditional relation requires condition")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to must not precede valid_from")
        return self


class Topic(ContractModel):
    id: str
    workspace_id: str
    label: str
    description: str
    cluster_version: str
    embedding_version: str
    centroid: list[float]
    representative_chunk_ids: list[str] = Field(default_factory=list)
    summary_evidence_ids: list[str] = Field(default_factory=list)
    summary_status: str
    active: bool = True

    @field_validator("centroid")
    @classmethod
    def centroid_is_finite(cls, value: list[float]) -> list[float]:
        if not all(math.isfinite(item) for item in value):
            raise ValueError("centroid must contain finite numbers")
        return value


class TopicMembership(ContractModel):
    topic_id: str
    chunk_id: str
    revision_id: str
    method: TopicMembershipMethod
    score: float
    assignment_version: str

    @field_validator("score")
    @classmethod
    def score_is_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("score must be finite")
        return value


class Conflict(ContractModel):
    id: str
    workspace_id: str
    left_relation_id: str
    right_relation_id: str
    kind: ConflictKind
    state: ConflictState
    explanation: str
    evidence_chunk_ids: list[str] = Field(default_factory=list)
    detector_version: str

    @model_validator(mode="after")
    def id_and_pair_order_are_canonical(self) -> "Conflict":
        if self.left_relation_id >= self.right_relation_id:
            raise ValueError("conflict relation IDs must be distinct and lexicographically ordered")
        expected_id = conflict_id(self.workspace_id, self.kind.value, self.left_relation_id, self.right_relation_id)
        if self.id != expected_id:
            raise ValueError("conflict id must match its canonical unordered relation pair")
        return self


class Operation(ContractModel):
    id: str
    workspace_id: str
    document_id: str
    kind: OperationKind
    expected_revision_id: str | None = None
    new_revision_id: str | None = None
    state: OperationState = OperationState.QUEUED
    stage: str
    accepted_at: datetime
    visible_at: datetime | None = None
    finished_at: datetime | None = None
    deadline_at: datetime
    checkpoint: dict[str, JsonValue] = Field(default_factory=dict)
    counts: dict[str, int] = Field(default_factory=dict)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    _validate_accepted_at = field_validator("accepted_at")(_utc)
    _validate_visible_at = field_validator("visible_at")(_utc)
    _validate_finished_at = field_validator("finished_at")(_utc)
    _validate_deadline_at = field_validator("deadline_at")(_utc)

    @field_validator("checkpoint")
    @classmethod
    def checkpoint_is_json_safe(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _assert_json_safe(value)
        return value

    @field_validator("counts")
    @classmethod
    def counts_are_nonnegative(cls, value: dict[str, int]) -> dict[str, int]:
        if any(item < 0 for item in value.values()):
            raise ValueError("counts must be non-negative")
        return value

    @field_validator("timings_ms")
    @classmethod
    def timings_are_finite(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not math.isfinite(item) or item < 0 for item in value.values()):
            raise ValueError("timings_ms must contain finite non-negative numbers")
        return value


class QueryRequest(ContractModel):
    workspace_id: str
    question: str
    topic_ids: list[str] = Field(default_factory=list)
    scope: QueryScope = QueryScope.WORKSPACE
    answer_language: AnswerLanguage = AnswerLanguage.AUTO
    top_k: int = Field(default=10, ge=1, le=30)
    max_hops: int = Field(default=4, ge=1, le=4)


class QueryResponse(ContractModel):
    request_id: str
    corpus_epoch: int = Field(ge=0)
    status: QueryStatus
    language: Literal["en", "hi"]
    plan: dict[str, JsonValue]
    statements: list[JsonValue]
    evidence: dict[str, JsonValue]
    graph: dict[str, JsonValue]
    latency_ms: float
    warnings: list[str] = Field(default_factory=list)

    @field_validator("plan", "evidence", "graph")
    @classmethod
    def mappings_are_json_safe(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _assert_json_safe(value)
        return value

    @field_validator("statements")
    @classmethod
    def statements_are_json_safe(cls, value: list[JsonValue]) -> list[JsonValue]:
        _assert_json_safe(value)
        return value

    @field_validator("latency_ms")
    @classmethod
    def latency_is_finite(cls, value: float) -> float:
        if not math.isfinite(value) or value < 0:
            raise ValueError("latency_ms must be finite and non-negative")
        return value


