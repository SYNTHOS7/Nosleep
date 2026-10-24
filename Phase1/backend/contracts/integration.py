"""Strict cross-team transport contracts; repository checks remain separate."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal, Sequence

from pydantic import Field, field_validator, model_validator

from .ids import evidence_path_id
from .models import (
    Chunk,
    Conflict,
    ContractModel,
    Document,
    Entity,
    EntityMention,
    Relation,
    Revision,
    Topic,
    TopicMembership,
    Value,
    _utc,
)
from .validation import validate_entity_mention_for_chunk, validate_evidence_for_chunk, validate_relation_context


def _unique(values: list[str], description: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{description} must be unique")


def _by_id(records: Sequence[ContractModel], description: str) -> dict[str, ContractModel]:
    result = {record.id: record for record in records}
    if len(result) != len(records):
        raise ValueError(f"{description} must have unique IDs")
    return result


class ExtractionBatch(ContractModel):
    """Task 2's source-supported staging payload, validated locally before repository checks."""

    workspace_id: str
    document_id: str
    revision_id: str
    embedding_version: str
    embedding_dimension: int = Field(gt=0)
    chunks: list[Chunk] = Field(min_length=1)
    entities: list[Entity] = Field(default_factory=list)
    entity_mentions: list[EntityMention] = Field(default_factory=list)
    values: list[Value] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    chunk_vectors: dict[str, list[float]]
    warnings: list[str] = Field(default_factory=list)

    @field_validator("chunk_vectors", mode="before")
    @classmethod
    def vector_components_are_numeric(cls, value: object) -> object:
        """Reject coercion from strings/bools while allowing ordinary int/float inputs."""
        if not isinstance(value, dict):
            return value
        for vector in value.values():
            if not isinstance(vector, list):
                continue
            if any(isinstance(component, bool) or not isinstance(component, (int, float)) for component in vector):
                raise ValueError("chunk vector components must be numeric int or float values")
        return value

    @model_validator(mode="after")
    def batch_is_locally_consistent(self) -> "ExtractionBatch":
        chunks = {chunk.id: chunk for chunk in self.chunks}
        if len(chunks) != len(self.chunks):
            raise ValueError("chunk IDs must be unique")
        for chunk in self.chunks:
            if (chunk.workspace_id, chunk.document_id, chunk.revision_id) != (
                self.workspace_id, self.document_id, self.revision_id
            ):
                raise ValueError("chunks must share batch workspace, document, and revision")

        entities = {entity.id: entity for entity in self.entities}
        values = {value.id: value for value in self.values}
        if len(entities) != len(self.entities) or len(values) != len(self.values):
            raise ValueError("entity and value IDs must be unique")
        if any(entity.workspace_id != self.workspace_id for entity in self.entities):
            raise ValueError("entities must share batch workspace")
        if any(value.workspace_id != self.workspace_id for value in self.values):
            raise ValueError("values must share batch workspace")

        _unique([mention.id for mention in self.entity_mentions], "entity mention IDs")
        for mention in self.entity_mentions:
            if mention.entity_id not in entities:
                raise ValueError("entity mentions must reference included entities")
            try:
                validate_entity_mention_for_chunk(mention, chunks[mention.chunk_id])
            except KeyError as error:
                raise ValueError("entity mentions must reference included chunks") from error

        _unique([relation.id for relation in self.relations], "relation IDs")
        for relation in self.relations:
            if relation.workspace_id != self.workspace_id or relation.revision_id != self.revision_id:
                raise ValueError("relations must share batch workspace and revision")
            if relation.subject_id not in entities:
                raise ValueError("relation subjects must reference included entities")
            if relation.object_entity_id is not None and relation.object_entity_id not in entities:
                raise ValueError("relation entity objects must reference included entities")
            if relation.object_value_id is not None and relation.object_value_id not in values:
                raise ValueError("relation value objects must reference included values")
            try:
                validate_relation_context(relation, chunks[relation.evidence.chunk_id])
            except KeyError as error:
                raise ValueError("relation evidence must reference included chunks") from error

        if set(self.chunk_vectors) != set(chunks):
            raise ValueError("chunk vectors must cover exactly the batch chunk IDs")
        for vector in self.chunk_vectors.values():
            if len(vector) != self.embedding_dimension:
                raise ValueError("every chunk vector must match embedding_dimension")
            if not all(math.isfinite(component) for component in vector):
                raise ValueError("chunk vectors must contain finite values")
            if not any(component != 0.0 for component in vector):
                raise ValueError("chunk vectors must not be zero vectors")
        return self


class CorpusSnapshot(ContractModel):
    """Task 1's consistent read boundary from authoritative Neo4j publication state."""

    workspace_id: str
    epoch: int = Field(ge=0)
    active_revision_ids: list[str] = Field(default_factory=list)
    captured_at: datetime

    _validate_captured_at = field_validator("captured_at")(_utc)

    @model_validator(mode="after")
    def active_revisions_are_unique(self) -> "CorpusSnapshot":
        _unique(self.active_revision_ids, "active revision IDs")
        return self


class DerivedDelta(ContractModel):
    """Task 3's staged topic/conflict changes; Task 1 alone validates and publishes them."""

    operation_id: str
    snapshot: CorpusSnapshot
    staged_revision_id: str | None = None
    topics_to_upsert: list[Topic] = Field(default_factory=list)
    topic_memberships_to_upsert: list[TopicMembership] = Field(default_factory=list)
    conflicts_to_upsert: list[Conflict] = Field(default_factory=list)
    conflict_ids_to_retire: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def delta_is_locally_consistent(self) -> "DerivedDelta":
        _unique([topic.id for topic in self.topics_to_upsert], "topic IDs")
        _unique([conflict.id for conflict in self.conflicts_to_upsert], "conflict IDs")
        _unique(self.conflict_ids_to_retire, "conflict retirement IDs")
        if set(self.conflict_ids_to_retire).intersection(conflict.id for conflict in self.conflicts_to_upsert):
            raise ValueError("a conflict cannot be upserted and retired in the same delta")
        if any(topic.workspace_id != self.snapshot.workspace_id for topic in self.topics_to_upsert):
            raise ValueError("topics must share snapshot workspace")
        if any(conflict.workspace_id != self.snapshot.workspace_id for conflict in self.conflicts_to_upsert):
            raise ValueError("conflicts must share snapshot workspace")
        allowed_revisions = set(self.snapshot.active_revision_ids)
        if self.staged_revision_id is not None:
            if self.staged_revision_id in allowed_revisions:
                raise ValueError("staged revision must not already be active in its base snapshot")
            allowed_revisions.add(self.staged_revision_id)
        membership_keys = [(item.topic_id, item.chunk_id, item.revision_id) for item in self.topic_memberships_to_upsert]
        if len(membership_keys) != len(set(membership_keys)):
            raise ValueError("topic membership keys must be unique")
        if any(item.revision_id not in allowed_revisions for item in self.topic_memberships_to_upsert):
            raise ValueError("topic memberships must reference snapshot-active or staged revisions")
        return self


class PublishReceipt(ContractModel):
    """Neo4j authoritative publication result; cleanup and read probe remain operation work."""

    operation_id: str
    workspace_id: str
    document_id: str
    publication_kind: Literal["initial", "replacement", "deletion", "noop"]
    previous_epoch: int = Field(ge=0)
    resulting_epoch: int = Field(ge=0)
    previous_active_revision_id: str | None = None
    active_revision_id: str | None = None
    neo4j_publication_applied: bool
    vectors_verified_before_publication: bool | None = None
    post_publication_cleanup_required: bool
    read_probe_required: bool
    published_at: datetime

    _validate_published_at = field_validator("published_at")(_utc)

    @model_validator(mode="after")
    def receipt_matches_publication_kind(self) -> "PublishReceipt":
        changed = self.publication_kind != "noop"
        if self.neo4j_publication_applied != changed:
            raise ValueError("neo4j publication flag must match publication kind")
        expected_epoch = self.previous_epoch + 1 if changed else self.previous_epoch
        if self.resulting_epoch != expected_epoch:
            raise ValueError("resulting epoch must match publication kind")
        if self.publication_kind == "initial":
            valid = self.previous_active_revision_id is None and self.active_revision_id is not None
        elif self.publication_kind == "replacement":
            valid = (
                self.previous_active_revision_id is not None
                and self.active_revision_id is not None
                and self.previous_active_revision_id != self.active_revision_id
            )
        elif self.publication_kind == "deletion":
            valid = self.previous_active_revision_id is not None and self.active_revision_id is None
        else:
            valid = self.previous_active_revision_id == self.active_revision_id
        if not valid:
            raise ValueError("active revision fields do not match publication kind")
        if self.publication_kind in {"initial", "replacement"}:
            if self.vectors_verified_before_publication is not True:
                raise ValueError("new active revisions require verified staged vectors")
        elif self.vectors_verified_before_publication is not None:
            raise ValueError("deletion and noop receipts must not claim vector staging")
        cleanup_expected = self.publication_kind in {"replacement", "deletion"}
        if self.post_publication_cleanup_required != cleanup_expected:
            raise ValueError("cleanup requirement must match publication kind")
        if self.read_probe_required != changed:
            raise ValueError("read probe requirement must match publication kind")
        return self


class EvidencePathStep(ContractModel):
    """One directed traversal of a source-specific relation with its source provenance."""

    relation_id: str
    subject_id: str
    object_entity_id: str | None = None
    object_value_id: str | None = None
    traversal_direction: Literal["forward", "reverse"]
    evidence_chunk_id: str
    revision_id: str
    document_id: str

    @model_validator(mode="after")
    def object_endpoint_is_exclusive(self) -> "EvidencePathStep":
        if (self.object_entity_id is None) == (self.object_value_id is None):
            raise ValueError("exactly one path-step object endpoint is required")
        return self

    @property
    def object_id(self) -> str:
        return self.object_entity_id or self.object_value_id  # XOR validator guarantees non-None.

    @property
    def traversal_start_id(self) -> str:
        return self.subject_id if self.traversal_direction == "forward" else self.object_id

    @property
    def traversal_end_id(self) -> str:
        return self.object_id if self.traversal_direction == "forward" else self.subject_id


class EvidencePath(ContractModel):
    """A connected, directed factual path; topic memberships never appear as steps."""

    id: str
    workspace_id: str
    snapshot_epoch: int = Field(ge=0)
    steps: list[EvidencePathStep] = Field(min_length=1)

    @model_validator(mode="after")
    def path_is_connected_and_canonical(self) -> "EvidencePath":
        for previous, current in zip(self.steps, self.steps[1:]):
            if previous.traversal_end_id != current.traversal_start_id:
                raise ValueError("ordered path steps must be connected")
        expected_id = evidence_path_id(
            self.workspace_id,
            self.snapshot_epoch,
            [step.model_dump(mode="json") for step in self.steps],
        )
        if self.id != expected_id:
            raise ValueError("evidence path id must match its snapshot-scoped ordered steps")
        return self


def revalidate_extraction_batch(batch: ExtractionBatch) -> ExtractionBatch:
    """Defensively reparse a batch after any mutable-container boundary."""
    return ExtractionBatch.model_validate(batch.model_dump(mode="python"))


def revalidate_evidence_path(path: EvidencePath) -> EvidencePath:
    """Defensively reparse a path after any mutable-container boundary."""
    return EvidencePath.model_validate(path.model_dump(mode="python"))


def validate_evidence_path_provenance(
    path: EvidencePath,
    *,
    relations: Sequence[Relation],
    chunks: Sequence[Chunk],
    revisions: Sequence[Revision],
    documents: Sequence[Document],
) -> EvidencePath:
    """Validate a standalone path using the source records a repository supplies.

    This is deliberately not a database lookup. Repositories must obtain records
    under their workspace/active-revision filters, then call this helper before
    returning an EvidencePath outside an EvidencePackage.
    """
    checked_path = revalidate_evidence_path(path)
    checked_relations = [Relation.model_validate(item.model_dump(mode="python")) for item in relations]
    checked_chunks = [Chunk.model_validate(item.model_dump(mode="python")) for item in chunks]
    checked_revisions = [Revision.model_validate(item.model_dump(mode="python")) for item in revisions]
    checked_documents = [Document.model_validate(item.model_dump(mode="python")) for item in documents]
    relation_map = _by_id(checked_relations, "path relations")
    chunk_map = _by_id(checked_chunks, "path chunks")
    revision_map = _by_id(checked_revisions, "path revisions")
    document_map = _by_id(checked_documents, "path documents")

    for document in checked_documents:
        if document.workspace_id != checked_path.workspace_id:
            raise ValueError("path documents must share path workspace")
    for step in checked_path.steps:
        try:
            relation = relation_map[step.relation_id]
            chunk = chunk_map[step.evidence_chunk_id]
            revision = revision_map[step.revision_id]
            document = document_map[step.document_id]
        except KeyError as error:
            raise ValueError("path steps must reference supplied source records") from error
        validate_relation_context(relation, chunk)
        if relation.workspace_id != checked_path.workspace_id:
            raise ValueError("path relations must share path workspace")
        if (
            relation.subject_id != step.subject_id
            or relation.object_entity_id != step.object_entity_id
            or relation.object_value_id != step.object_value_id
            or relation.evidence.chunk_id != step.evidence_chunk_id
            or relation.revision_id != step.revision_id
            or chunk.document_id != step.document_id
            or revision.document_id != step.document_id
            or document.id != step.document_id
        ):
            raise ValueError("path step must match relation endpoints and source provenance")
    return checked_path


class EvidencePackage(ContractModel):
    """A reference-closed, potentially partial evidence set from one CorpusSnapshot."""

    snapshot: CorpusSnapshot
    documents: list[Document] = Field(default_factory=list)
    revisions: list[Revision] = Field(default_factory=list)
    chunks: list[Chunk] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    entity_mentions: list[EntityMention] = Field(default_factory=list)
    values: list[Value] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    topics: list[Topic] = Field(default_factory=list)
    topic_memberships: list[TopicMembership] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    paths: list[EvidencePath] = Field(default_factory=list)
    truncated: bool = False
    available_chunk_count: int | None = Field(default=None, ge=0)
    searched_chunk_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def package_is_reference_closed(self) -> "EvidencePackage":
        documents = {item.id: item for item in self.documents}
        revisions = {item.id: item for item in self.revisions}
        chunks = {item.id: item for item in self.chunks}
        entities = {item.id: item for item in self.entities}
        values = {item.id: item for item in self.values}
        relations = {item.id: item for item in self.relations}
        topics = {item.id: item for item in self.topics}
        for records, name in (
            (self.documents, "document IDs"), (self.revisions, "revision IDs"), (self.chunks, "chunk IDs"),
            (self.entities, "entity IDs"), (self.entity_mentions, "entity mention IDs"), (self.values, "value IDs"),
            (self.relations, "relation IDs"), (self.topics, "topic IDs"), (self.conflicts, "conflict IDs"),
            (self.paths, "path IDs"),
        ):
            _unique([item.id for item in records], name)
        workspace_id = self.snapshot.workspace_id
        if any(item.workspace_id != workspace_id for item in self.documents + self.chunks + self.entities + self.entity_mentions + self.values + self.relations + self.topics + self.conflicts):
            raise ValueError("all package records must share snapshot workspace")
        active_revisions = set(self.snapshot.active_revision_ids)
        for document in self.documents:
            if document.deleted or document.active_revision_id is None:
                raise ValueError("package documents must be active and non-deleted")
            if document.active_revision_id not in active_revisions or document.active_revision_id not in revisions:
                raise ValueError("package documents must include their snapshot-active revision")
        for revision in self.revisions:
            if revision.id not in active_revisions:
                raise ValueError("package revisions must be active in the snapshot")
            try:
                document = documents[revision.document_id]
            except KeyError as error:
                raise ValueError("package revisions must reference included documents") from error
            if document.deleted or document.active_revision_id != revision.id:
                raise ValueError("package documents must expose their included active revision")
        for chunk in self.chunks:
            if chunk.revision_id not in revisions or chunk.document_id not in documents:
                raise ValueError("package chunks must reference included document and revision")
            if revisions[chunk.revision_id].document_id != chunk.document_id:
                raise ValueError("package chunk document must match its revision")
        for mention in self.entity_mentions:
            if mention.entity_id not in entities:
                raise ValueError("package mentions must reference included entities")
            try:
                validate_entity_mention_for_chunk(mention, chunks[mention.chunk_id])
            except KeyError as error:
                raise ValueError("package mentions must reference included chunks") from error
        for relation in self.relations:
            if relation.subject_id not in entities:
                raise ValueError("package relations must reference included subjects")
            if relation.object_entity_id is not None and relation.object_entity_id not in entities:
                raise ValueError("package relations must reference included entity objects")
            if relation.object_value_id is not None and relation.object_value_id not in values:
                raise ValueError("package relations must reference included value objects")
            try:
                validate_relation_context(relation, chunks[relation.evidence.chunk_id])
            except KeyError as error:
                raise ValueError("package relations must reference included evidence chunks") from error
        membership_keys = [(item.topic_id, item.chunk_id, item.revision_id) for item in self.topic_memberships]
        if len(membership_keys) != len(set(membership_keys)):
            raise ValueError("package topic memberships must be unique")
        for membership in self.topic_memberships:
            if membership.topic_id not in topics or membership.chunk_id not in chunks:
                raise ValueError("package topic memberships must reference included topic and chunk")
            if chunks[membership.chunk_id].revision_id != membership.revision_id:
                raise ValueError("package topic membership revision must match its chunk")
        for topic in self.topics:
            if any(chunk_id not in chunks for chunk_id in topic.representative_chunk_ids):
                raise ValueError("included topic representative chunks must be included")
            # summary_evidence_ids intentionally has no validation: its referent type is unresolved.
        for conflict in self.conflicts:
            if conflict.left_relation_id not in relations or conflict.right_relation_id not in relations:
                raise ValueError("package conflicts must reference included relations")
            source_chunks = {
                relations[conflict.left_relation_id].evidence.chunk_id,
                relations[conflict.right_relation_id].evidence.chunk_id,
            }
            if not source_chunks.issubset(set(conflict.evidence_chunk_ids)):
                raise ValueError("package conflicts must include both relation evidence chunks")
            if any(chunk_id not in chunks for chunk_id in conflict.evidence_chunk_ids):
                raise ValueError("package conflict evidence chunks must be included")
        for path in self.paths:
            if path.workspace_id != workspace_id or path.snapshot_epoch != self.snapshot.epoch:
                raise ValueError("package paths must share snapshot workspace and epoch")
            validate_evidence_path_provenance(
                path,
                relations=self.relations,
                chunks=self.chunks,
                revisions=self.revisions,
                documents=self.documents,
            )
        counts_present = self.available_chunk_count is not None or self.searched_chunk_count is not None
        if counts_present and (self.available_chunk_count is None or self.searched_chunk_count is None):
            raise ValueError("chunk counts must be supplied together")
        if self.truncated and not counts_present:
            raise ValueError("truncated packages require chunk counts")
        if counts_present and self.searched_chunk_count > self.available_chunk_count:
            raise ValueError("searched chunk count must not exceed available chunk count")
        return self


def revalidate_evidence_package(package: EvidencePackage) -> EvidencePackage:
    """Defensively reparse a package after any mutable-container boundary."""
    return EvidencePackage.model_validate(package.model_dump(mode="python"))
