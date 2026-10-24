"""Deterministic in-memory Task 1 fake repositories for offline lifecycle tests."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Sequence

from backend.contracts.ids import evidence_path_id
from backend.contracts.integration import CorpusSnapshot, DerivedDelta, EvidencePackage, EvidencePath, EvidencePathStep, ExtractionBatch, PublishReceipt, revalidate_extraction_batch, validate_evidence_path_provenance
from backend.contracts.models import Chunk, Conflict, Document, Entity, EntityMention, Operation, OperationKind, OperationState, Relation, Revision, RevisionState, Topic, TopicMembership, Value

from .interfaces import EpochConflict, OperationConflict, StorageError, VectorStageError, WorkspaceViolation


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryGraphRepository:
    """A graph fake with an atomic publication lock and authoritative epoch state."""

    def __init__(self) -> None:
        self._lock = RLock()
        self.documents: dict[str, Document] = {}
        self.revisions: dict[str, Revision] = {}
        self.operations: dict[str, Operation] = {}
        self.batches: dict[str, ExtractionBatch] = {}
        self.chunks: dict[str, Chunk] = {}
        self.entities: dict[str, Entity] = {}
        self.mentions: dict[str, EntityMention] = {}
        self.values: dict[str, Value] = {}
        self.relations: dict[str, Relation] = {}
        self.topics: dict[str, Topic] = {}
        self.memberships: list[TopicMembership] = []
        self.conflicts: dict[str, Conflict] = {}
        self.epochs: dict[str, int] = {}
        self.published_operations: set[str] = set()
        self.receipts: dict[str, PublishReceipt] = {}
        self.fail_next_publish = False

    def register_document(self, document: Document) -> None:
        with self._lock:
            existing = self.documents.get(document.id)
            if existing and existing.workspace_id != document.workspace_id:
                raise WorkspaceViolation("document ID already belongs to another workspace")
            self.documents[document.id] = document
            self.epochs.setdefault(document.workspace_id, 0)

    def create_operation(self, operation: Operation) -> None:
        with self._lock:
            if operation.id in self.operations:
                if self.operations[operation.id] != operation:
                    raise OperationConflict("operation ID is not idempotent")
                return
            document = self.documents.get(operation.document_id)
            if document is None or document.workspace_id != operation.workspace_id:
                raise WorkspaceViolation("operation document must exist in its workspace")
            self.operations[operation.id] = operation
            self.epochs.setdefault(operation.workspace_id, 0)

    def get_operation(self, operation_id: str, workspace_id: str) -> Operation:
        operation = self.operations.get(operation_id)
        if operation is None:
            raise StorageError("operation not found")
        if operation.workspace_id != workspace_id:
            raise WorkspaceViolation("operation does not belong to workspace")
        return operation

    def _replace_operation(self, operation: Operation, **changes: object) -> Operation:
        updated = operation.model_copy(update=changes)
        self.operations[operation.id] = updated
        return updated

    def claim_operation(self, operation_id: str, workspace_id: str) -> Operation:
        with self._lock:
            operation = self.get_operation(operation_id, workspace_id)
            if operation.state is OperationState.QUEUED:
                return self._replace_operation(operation, state=OperationState.RUNNING, stage="running")
            if operation.state is OperationState.RUNNING:
                return operation
            raise OperationConflict("only queued or running operations can be claimed")

    def stage_revision(self, operation_id: str, revision: Revision) -> None:
        with self._lock:
            operation = self.operations.get(operation_id)
            if operation is None:
                raise StorageError("operation not found")
            if operation.kind is OperationKind.DELETE:
                raise OperationConflict("delete operations cannot stage revisions")
            if operation.document_id != revision.document_id or operation.new_revision_id != revision.id:
                raise OperationConflict("revision must match operation document and new_revision_id")
            if revision.state is not RevisionState.STAGED:
                raise OperationConflict("only staged revisions may be registered")
            existing = self.revisions.get(revision.id)
            if existing and existing != revision:
                raise OperationConflict("revision ID is not idempotent")
            self.revisions[revision.id] = revision

    def stage_batch(self, operation_id: str, batch: ExtractionBatch) -> None:
        checked = revalidate_extraction_batch(batch)
        with self._lock:
            operation = self.operations.get(operation_id)
            if operation is None:
                raise StorageError("operation not found")
            if operation.kind is OperationKind.DELETE:
                raise OperationConflict("delete operations cannot stage extraction batches")
            if (operation.workspace_id, operation.document_id, operation.new_revision_id) != (checked.workspace_id, checked.document_id, checked.revision_id):
                raise WorkspaceViolation("batch must match operation workspace, document, and revision")
            revision = self.revisions.get(checked.revision_id)
            if revision is None or revision.state is not RevisionState.STAGED:
                raise OperationConflict("batch requires an existing staged revision")
            existing = self.batches.get(operation_id)
            if existing and existing != checked:
                raise OperationConflict("operation batch is not idempotent")
            self.batches[operation_id] = checked
            self._replace_operation(operation, stage="graph_staged")

    def get_staged_batch(self, operation_id: str, workspace_id: str) -> ExtractionBatch:
        with self._lock:
            self.get_operation(operation_id, workspace_id)
            try:
                return revalidate_extraction_batch(self.batches[operation_id])
            except KeyError as error:
                raise StorageError("staged batch not found") from error

    def get_snapshot(self, workspace_id: str) -> CorpusSnapshot:
        with self._lock:
            active = sorted(document.active_revision_id for document in self.documents.values() if document.workspace_id == workspace_id and not document.deleted and document.active_revision_id)
            return CorpusSnapshot(workspace_id=workspace_id, epoch=self.epochs.get(workspace_id, 0), active_revision_ids=active, captured_at=_now())

    def _active_relation_ids(self, workspace_id: str, revision_ids: set[str]) -> set[str]:
        return {relation.id for relation in self.relations.values() if relation.workspace_id == workspace_id and relation.revision_id in revision_ids}

    def _validate_delta_for_publication(self, delta: DerivedDelta, workspace_id: str, revision_ids: set[str]) -> None:
        if delta.snapshot.workspace_id != workspace_id:
            raise WorkspaceViolation("delta snapshot does not belong to operation workspace")
        relation_ids = self._active_relation_ids(workspace_id, revision_ids)
        staged = self.batches.get(delta.operation_id)
        if staged:
            relation_ids.update(relation.id for relation in staged.relations)
        relation_by_id = {**self.relations, **({relation.id: relation for relation in staged.relations} if staged else {})}
        chunk_ids = {chunk.id for chunk in self.chunks.values() if chunk.workspace_id == workspace_id and chunk.revision_id in revision_ids}
        if staged:
            chunk_ids.update(chunk.id for chunk in staged.chunks)
        for conflict in delta.conflicts_to_upsert:
            if {conflict.left_relation_id, conflict.right_relation_id}.difference(relation_ids):
                raise StorageError("conflict must reference relations active after publication")
            evidence_ids = {relation_by_id[relation_id].evidence.chunk_id for relation_id in (conflict.left_relation_id, conflict.right_relation_id)}
            if not evidence_ids.issubset(chunk_ids) or not evidence_ids.issubset(set(conflict.evidence_chunk_ids)):
                raise StorageError("conflict must retain active source evidence")
        for conflict_id in delta.conflict_ids_to_retire:
            conflict = self.conflicts.get(conflict_id)
            if conflict and {conflict.left_relation_id, conflict.right_relation_id}.issubset(relation_ids):
                raise StorageError("cannot retire a conflict still supported by active relations")

    def publish(self, operation_id: str, delta: DerivedDelta, expected_epoch: int) -> PublishReceipt:
        with self._lock:
            operation = self.operations.get(operation_id)
            if operation is None:
                raise StorageError("operation not found")
            if delta.operation_id != operation_id:
                raise OperationConflict("delta operation ID must match publication operation")
            current = self.get_snapshot(operation.workspace_id)
            if operation_id in self.published_operations:
                return self.receipts[operation_id]
            if expected_epoch != current.epoch or delta.snapshot.epoch != expected_epoch:
                raise EpochConflict("expected epoch no longer matches authoritative graph state")
            if self.fail_next_publish:
                self.fail_next_publish = False
                raise StorageError("injected graph publication failure")
            document = self.documents[operation.document_id]
            old_revision_id = document.active_revision_id
            if operation.expected_revision_id != old_revision_id:
                raise OperationConflict("operation expected_revision_id does not match active document revision")
            if operation.kind is OperationKind.DELETE:
                if old_revision_id is None:
                    kind = "noop"
                else:
                    kind = "deletion"
                new_revision_id = None
                post_revision_ids = {revision_id for revision_id in current.active_revision_ids if revision_id != old_revision_id}
            else:
                batch = self.batches.get(operation_id)
                revision = self.revisions.get(operation.new_revision_id or "")
                if batch is None or revision is None or revision.state is not RevisionState.STAGED:
                    raise OperationConflict("publication requires a staged graph batch and revision")
                if delta.staged_revision_id not in {None, revision.id}:
                    raise OperationConflict("delta staged revision does not match operation")
                new_revision_id = revision.id
                kind = "initial" if old_revision_id is None else "replacement"
                post_revision_ids = set(current.active_revision_ids)
                if old_revision_id:
                    post_revision_ids.discard(old_revision_id)
                post_revision_ids.add(new_revision_id)
            self._validate_delta_for_publication(delta, operation.workspace_id, post_revision_ids)
            if operation.kind is not OperationKind.DELETE:
                batch = self.batches[operation_id]
                self.chunks.update({item.id: item for item in batch.chunks})
                self.entities.update({item.id: item for item in batch.entities})
                self.mentions.update({item.id: item for item in batch.entity_mentions})
                self.values.update({item.id: item for item in batch.values})
                self.relations.update({item.id: item for item in batch.relations})
                self.revisions[new_revision_id] = self.revisions[new_revision_id].model_copy(update={"state": RevisionState.PUBLISHED})
            if old_revision_id and old_revision_id in self.revisions:
                self.revisions[old_revision_id] = self.revisions[old_revision_id].model_copy(update={"state": RevisionState.RETIRED})
            self.documents[document.id] = document.model_copy(update={"active_revision_id": new_revision_id, "deleted": operation.kind is OperationKind.DELETE})
            self.topics.update({item.id: item for item in delta.topics_to_upsert})
            self.memberships = [item for item in self.memberships if item.revision_id not in {old_revision_id}]
            self.memberships.extend(delta.topic_memberships_to_upsert)
            self.conflicts.update({item.id: item for item in delta.conflicts_to_upsert})
            for conflict_id in delta.conflict_ids_to_retire:
                self.conflicts.pop(conflict_id, None)
            resulting_epoch = current.epoch if kind == "noop" else current.epoch + 1
            self.epochs[operation.workspace_id] = resulting_epoch
            self.published_operations.add(operation_id)
            receipt = PublishReceipt(
                operation_id=operation.id, workspace_id=operation.workspace_id, document_id=operation.document_id,
                publication_kind=kind, previous_epoch=current.epoch, resulting_epoch=resulting_epoch,
                previous_active_revision_id=old_revision_id, active_revision_id=new_revision_id,
                neo4j_publication_applied=kind != "noop",
                vectors_verified_before_publication=True if kind in {"initial", "replacement"} else None,
                post_publication_cleanup_required=kind in {"replacement", "deletion"}, read_probe_required=kind != "noop",
                published_at=_now(),
            )
            self.receipts[operation_id] = receipt
            self._replace_operation(operation, state=OperationState.RUNNING, stage="published_cleanup_pending", visible_at=_now(), checkpoint={"published": True, "receipt": receipt.model_dump(mode="json")})
            return receipt

    def cleanup(self, operation_id: str, workspace_id: str) -> None:
        with self._lock:
            operation = self.get_operation(operation_id, workspace_id)
            if operation_id not in self.published_operations:
                raise OperationConflict("cleanup requires published operation")
            active = set(self.get_snapshot(workspace_id).active_revision_ids)
            retired = {revision.id for revision in self.revisions.values() if revision.document_id == operation.document_id and revision.id not in active}
            for chunk_id, chunk in list(self.chunks.items()):
                if chunk.revision_id in retired:
                    del self.chunks[chunk_id]
            self.mentions = {key: value for key, value in self.mentions.items() if value.revision_id not in retired}
            self.relations = {key: value for key, value in self.relations.items() if value.revision_id not in retired}
            self.memberships = [item for item in self.memberships if item.revision_id not in retired]
            active_relations = self._active_relation_ids(workspace_id, active)
            self.conflicts = {key: value for key, value in self.conflicts.items() if {value.left_relation_id, value.right_relation_id}.issubset(active_relations)}
            self._replace_operation(operation, stage="graph_cleanup_complete")

    def mark_cleanup_pending(self, operation_id: str, workspace_id: str, error: str) -> None:
        with self._lock:
            operation = self.get_operation(operation_id, workspace_id)
            self._replace_operation(operation, state=OperationState.RUNNING, stage="cleanup_pending", errors=[*operation.errors, error], checkpoint={**operation.checkpoint, "cleanup_pending": True})

    def mark_ready_after_probe(self, operation_id: str, workspace_id: str) -> None:
        with self._lock:
            operation = self.get_operation(operation_id, workspace_id)
            if operation_id not in self.published_operations:
                raise OperationConflict("only published operations can be marked ready")
            self._replace_operation(operation, state=OperationState.READY, stage="ready", finished_at=_now(), checkpoint={**operation.checkpoint, "cleanup_pending": False})

    def active_chunk_ids(self, snapshot: CorpusSnapshot) -> list[str]:
        self._require_current_snapshot(snapshot)
        return [chunk.id for chunk in self.chunks.values() if chunk.workspace_id == snapshot.workspace_id and chunk.revision_id in snapshot.active_revision_ids]

    def _require_current_snapshot(self, snapshot: CorpusSnapshot) -> None:
        current = self.get_snapshot(snapshot.workspace_id)
        if current.epoch != snapshot.epoch or current.active_revision_ids != snapshot.active_revision_ids:
            raise EpochConflict("snapshot changed; caller must retry")

    def lexical_candidates(self, text: str, snapshot: CorpusSnapshot, limit: int) -> list[str]:
        self._require_current_snapshot(snapshot)
        return [chunk.id for chunk in self.chunks.values() if chunk.workspace_id == snapshot.workspace_id and chunk.revision_id in snapshot.active_revision_ids and text.casefold() in chunk.text.casefold()][:limit]

    def fetch_evidence(self, chunk_ids: Sequence[str], snapshot: CorpusSnapshot) -> EvidencePackage:
        self._require_current_snapshot(snapshot)
        truncated = False
        raw_selected = [self.chunks[chunk_id] for chunk_id in chunk_ids if chunk_id in self.chunks and self.chunks[chunk_id].workspace_id == snapshot.workspace_id and self.chunks[chunk_id].revision_id in snapshot.active_revision_ids]
        if len(raw_selected) > 200:
            selected = raw_selected[:200]
            truncated = True
        else:
            selected = raw_selected
        revision_ids = {item.revision_id for item in selected}
        documents = [document for document in self.documents.values() if document.workspace_id == snapshot.workspace_id and document.active_revision_id in revision_ids and not document.deleted]
        document_ids = {document.id for document in documents}
        revisions = [self.revisions[revision_id] for revision_id in revision_ids if revision_id in self.revisions]
        entities = {entity_id: entity for entity_id, entity in self.entities.items() if entity.workspace_id == snapshot.workspace_id}
        values = {value_id: value for value_id, value in self.values.items() if value.workspace_id == snapshot.workspace_id}
        raw_relations = [relation for relation in self.relations.values() if relation.workspace_id == snapshot.workspace_id and relation.revision_id in revision_ids and relation.evidence.chunk_id in {chunk.id for chunk in selected}]
        if len(raw_relations) > 300:
            relations = raw_relations[:300]
            truncated = True
        else:
            relations = raw_relations
        needed_entities = {relation.subject_id for relation in relations} | {relation.object_entity_id for relation in relations if relation.object_entity_id}
        needed_values = {relation.object_value_id for relation in relations if relation.object_value_id}
        available_count = len(raw_selected) if truncated else None
        searched_count = len(selected) if truncated else None
        return EvidencePackage(
            snapshot=snapshot,
            documents=[document for document in documents if document.id in document_ids],
            revisions=revisions,
            chunks=selected,
            entities=[entities[key] for key in needed_entities if key in entities],
            values=[values[key] for key in needed_values if key in values],
            relations=relations,
            truncated=truncated,
            available_chunk_count=available_count,
            searched_chunk_count=searched_count,
        )

    def expand_paths(self, entity_ids: Sequence[str], snapshot: CorpusSnapshot, max_hops: int) -> list[EvidencePath]:
        self._require_current_snapshot(snapshot)
        if max_hops < 1:
            return []
        requested = set(entity_ids)
        paths: list[EvidencePath] = []
        for relation in self.relations.values():
            if relation.workspace_id != snapshot.workspace_id or relation.revision_id not in snapshot.active_revision_ids:
                continue
            if relation.subject_id not in requested and relation.object_entity_id not in requested:
                continue
            chunk = self.chunks.get(relation.evidence.chunk_id)
            if chunk is None:
                continue
            revision = self.revisions.get(relation.revision_id)
            document = self.documents.get(chunk.document_id)
            if revision is None or document is None:
                continue
            step = EvidencePathStep(
                relation_id=relation.id, subject_id=relation.subject_id, object_entity_id=relation.object_entity_id,
                object_value_id=relation.object_value_id, traversal_direction="forward", evidence_chunk_id=chunk.id,
                revision_id=relation.revision_id, document_id=chunk.document_id,
            )
            path = EvidencePath(id=evidence_path_id(snapshot.workspace_id, snapshot.epoch, [step.model_dump(mode="json")]), workspace_id=snapshot.workspace_id, snapshot_epoch=snapshot.epoch, steps=[step])
            paths.append(validate_evidence_path_provenance(path, relations=[relation], chunks=[chunk], revisions=[revision], documents=[document]))
            if len(paths) == 5:
                break
        return paths


class InMemoryVectorRepository:
    """Persistent-Chroma-shaped fake: staged vectors are invisible until graph snapshot filtering."""

    def __init__(self) -> None:
        self._lock = RLock()
        self.vectors: dict[str, tuple[str, str, int, list[float]]] = {}
        self.workspace_profiles: dict[str, tuple[str, int]] = {}
        self.fail_next_stage = False
        self.fail_next_cleanup = False

    def stage_batch(self, workspace_id: str, batch: ExtractionBatch) -> None:
        checked = revalidate_extraction_batch(batch)
        with self._lock:
            if self.fail_next_stage:
                self.fail_next_stage = False
                raise VectorStageError("injected vector staging failure")
            profile = (checked.embedding_version, checked.embedding_dimension)
            existing_profile = self.workspace_profiles.get(workspace_id)
            if existing_profile is not None and existing_profile != profile:
                raise VectorStageError("workspace embedding profile change requires explicit reindexing")
            self.workspace_profiles.setdefault(workspace_id, profile)
            for chunk_id, vector in checked.chunk_vectors.items():
                existing = self.vectors.get(chunk_id)
                candidate = (workspace_id, checked.revision_id, checked.embedding_dimension, list(vector))
                if existing is not None and existing != candidate:
                    raise VectorStageError("chunk vector ID is not idempotent")
                self.vectors[chunk_id] = candidate

    def verify_staged(self, workspace_id: str, batch: ExtractionBatch) -> None:
        checked = revalidate_extraction_batch(batch)
        with self._lock:
            profile = self.workspace_profiles.get(workspace_id)
            if profile != (checked.embedding_version, checked.embedding_dimension):
                raise VectorStageError("staged vector profile does not match workspace profile")
            for chunk_id, vector in checked.chunk_vectors.items():
                if self.vectors.get(chunk_id) != (workspace_id, checked.revision_id, checked.embedding_dimension, list(vector)):
                    raise VectorStageError("missing or mismatched staged vector")

    def vector_candidates(self, vector: list[float], snapshot: CorpusSnapshot, limit: int) -> list[str]:
        with self._lock:
            profile = self.workspace_profiles.get(snapshot.workspace_id)
            if profile is None or len(vector) != profile[1]:
                return []
            return [chunk_id for chunk_id, (workspace_id, revision_id, _, _) in self.vectors.items() if workspace_id == snapshot.workspace_id and revision_id in snapshot.active_revision_ids][:limit]

    def cleanup(self, workspace_id: str, active_chunk_ids: set[str]) -> None:
        with self._lock:
            if self.fail_next_cleanup:
                self.fail_next_cleanup = False
                raise VectorStageError("injected vector cleanup failure")
            self.vectors = {chunk_id: item for chunk_id, item in self.vectors.items() if item[0] != workspace_id or chunk_id in active_chunk_ids}
