from datetime import datetime, timedelta, timezone

import pytest

from backend.contracts.integration import DerivedDelta, ExtractionBatch
from backend.contracts.ids import conflict_id
from backend.contracts.models import Chunk, ChunkLocation, Conflict, Document, Entity, Evidence, Operation, Relation, Revision
from backend.storage import EpochConflict, InMemoryGraphRepository, InMemoryVectorRepository, StorageError, StorageLifecycle, VectorStageError, WorkspaceViolation


UTC = datetime(2026, 10, 24, tzinfo=timezone.utc)


def _operation(operation_id: str, document_id: str, revision_id: str | None, *, kind: str = "add", expected: str | None = None, workspace_id: str = "ws-1") -> Operation:
    return Operation(
        id=operation_id, workspace_id=workspace_id, document_id=document_id, kind=kind,
        expected_revision_id=expected, new_revision_id=revision_id, stage="queued",
        accepted_at=UTC, deadline_at=UTC + timedelta(minutes=1),
    )


def _revision(revision_id: str, document_id: str) -> Revision:
    return Revision(
        id=revision_id, document_id=document_id, content_hash=f"hash-{revision_id}", parser_version="p1",
        chunker_version="c1", extractor_version="x1", embedding_version="embed-v1", state="staged",
        source_ref=f"source-{revision_id}", created_at=UTC,
    )


def _batch(document_id: str, revision_id: str, *, workspace_id: str = "ws-1", suffix: str = "one") -> ExtractionBatch:
    chunk_id, subject_id, object_id, relation_id = (f"chunk-{revision_id}", f"entity-{suffix}", "entity-shared", f"relation-{revision_id}")
    text = f"{suffix} supports IPv6."
    chunk = Chunk(id=chunk_id, workspace_id=workspace_id, document_id=document_id, revision_id=revision_id, index=0, text=text, text_hash="hash", location=ChunkLocation(start_offset=0, end_offset=len(text)))
    entities = [
        Entity(id=subject_id, workspace_id=workspace_id, name=suffix, normalized_name=suffix, type="Organization"),
        Entity(id=object_id, workspace_id=workspace_id, name="IPv6", normalized_name="ipv6", type="Technology"),
    ]
    relation = Relation(
        id=relation_id, workspace_id=workspace_id, revision_id=revision_id, subject_id=subject_id,
        object_entity_id=object_id, predicate="SUPPORTS", predicate_original="supports", polarity="positive",
        modality="asserted", evidence=Evidence(chunk_id=chunk_id, start=0, end=len(text), quote=text),
        extraction_method="fixture", extraction_model="fixture", extraction_version="v1",
    )
    return ExtractionBatch(workspace_id=workspace_id, document_id=document_id, revision_id=revision_id, embedding_version="embed-v1", embedding_dimension=2, chunks=[chunk], entities=entities, relations=[relation], chunk_vectors={chunk_id: [0.5, 0.25]})


def _setup_add(graph: InMemoryGraphRepository, lifecycle: StorageLifecycle, *, document_id: str = "doc-1", operation_id: str = "op-1", revision_id: str = "rev-1", workspace_id: str = "ws-1", suffix: str = "one") -> ExtractionBatch:
    graph.register_document(Document(id=document_id, workspace_id=workspace_id, filename=f"{document_id}.txt", source_type="txt", created_at=UTC))
    graph.create_operation(_operation(operation_id, document_id, revision_id, workspace_id=workspace_id))
    graph.stage_revision(operation_id, _revision(revision_id, document_id))
    batch = _batch(document_id, revision_id, workspace_id=workspace_id, suffix=suffix)
    lifecycle.stage_batch(operation_id, workspace_id, batch)
    return batch


def _publish_add(graph: InMemoryGraphRepository, lifecycle: StorageLifecycle, *, operation_id: str = "op-1", workspace_id: str = "ws-1", revision_id: str = "rev-1") -> None:
    snapshot = graph.get_snapshot(workspace_id)
    lifecycle.publish(operation_id, workspace_id, DerivedDelta(operation_id=operation_id, snapshot=snapshot, staged_revision_id=revision_id), snapshot.epoch)
    lifecycle.cleanup(operation_id, workspace_id)


def test_add_publish_and_cleanup_make_only_active_vectors_visible() -> None:
    graph, vectors = InMemoryGraphRepository(), InMemoryVectorRepository()
    lifecycle = StorageLifecycle(graph, vectors)
    batch = _setup_add(graph, lifecycle)
    _publish_add(graph, lifecycle)
    snapshot = graph.get_snapshot("ws-1")
    assert snapshot.active_revision_ids == ["rev-1"]
    assert vectors.vector_candidates([0.2, 0.1], snapshot, 10) == [batch.chunks[0].id]
    assert graph.expand_paths([batch.entities[0].id], snapshot, 1)[0].steps[0].relation_id == batch.relations[0].id
    assert graph.get_operation("op-1", "ws-1").state.value == "ready"


def test_vector_stage_and_graph_publish_failures_leave_old_content_visible() -> None:
    graph, vectors = InMemoryGraphRepository(), InMemoryVectorRepository()
    lifecycle = StorageLifecycle(graph, vectors)
    first = _setup_add(graph, lifecycle)
    _publish_add(graph, lifecycle)

    graph.create_operation(_operation("op-2", "doc-1", "rev-2", kind="edit", expected="rev-1"))
    graph.stage_revision("op-2", _revision("rev-2", "doc-1"))
    vectors.fail_next_stage = True
    with pytest.raises(VectorStageError):
        lifecycle.stage_batch("op-2", "ws-1", _batch("doc-1", "rev-2", suffix="two"))
    assert graph.get_snapshot("ws-1").active_revision_ids == ["rev-1"]

    lifecycle.stage_batch("op-2", "ws-1", _batch("doc-1", "rev-2", suffix="two"))
    snapshot = graph.get_snapshot("ws-1")
    graph.fail_next_publish = True
    with pytest.raises(Exception, match="graph publication"):
        lifecycle.publish("op-2", "ws-1", DerivedDelta(operation_id="op-2", snapshot=snapshot, staged_revision_id="rev-2"), snapshot.epoch)
    assert graph.get_snapshot("ws-1").active_revision_ids == ["rev-1"]
    assert vectors.vector_candidates([0.2, 0.1], graph.get_snapshot("ws-1"), 10) == [first.chunks[0].id]


def test_epoch_conflict_and_workspace_isolation_are_enforced() -> None:
    graph, vectors = InMemoryGraphRepository(), InMemoryVectorRepository()
    lifecycle = StorageLifecycle(graph, vectors)
    _setup_add(graph, lifecycle)
    snapshot = graph.get_snapshot("ws-1")
    with pytest.raises(EpochConflict):
        lifecycle.publish("op-1", "ws-1", DerivedDelta(operation_id="op-1", snapshot=snapshot, staged_revision_id="rev-1"), 99)
    with pytest.raises(WorkspaceViolation):
        graph.get_operation("op-1", "ws-2")


def test_publish_retry_returns_original_receipt_and_conflict_retirement_is_safe() -> None:
    graph, vectors = InMemoryGraphRepository(), InMemoryVectorRepository()
    lifecycle = StorageLifecycle(graph, vectors)
    first = _setup_add(graph, lifecycle, document_id="doc-1", operation_id="op-1", revision_id="rev-1", suffix="one")
    _publish_add(graph, lifecycle, operation_id="op-1", revision_id="rev-1")
    second = _setup_add(graph, lifecycle, document_id="doc-2", operation_id="op-2", revision_id="rev-2", suffix="two")
    snapshot = graph.get_snapshot("ws-1")
    conflict = Conflict(
        id=conflict_id("ws-1", "incompatible_statement", first.relations[0].id, second.relations[0].id),
        workspace_id="ws-1", left_relation_id=first.relations[0].id, right_relation_id=second.relations[0].id,
        kind="incompatible_statement", state="supported", explanation="fixture", evidence_chunk_ids=[first.chunks[0].id, second.chunks[0].id], detector_version="v1",
    )
    delta = DerivedDelta(operation_id="op-2", snapshot=snapshot, staged_revision_id="rev-2", conflicts_to_upsert=[conflict])
    receipt = lifecycle.publish("op-2", "ws-1", delta, snapshot.epoch)
    assert lifecycle.publish("op-2", "ws-1", delta, snapshot.epoch) == receipt
    lifecycle.cleanup("op-2", "ws-1")

    graph.register_document(Document(id="doc-3", workspace_id="ws-1", filename="doc-3.txt", source_type="txt", created_at=UTC))
    graph.create_operation(_operation("op-3", "doc-3", "rev-3"))
    graph.stage_revision("op-3", _revision("rev-3", "doc-3"))
    lifecycle.stage_batch("op-3", "ws-1", _batch("doc-3", "rev-3", suffix="three"))
    snapshot = graph.get_snapshot("ws-1")
    with pytest.raises(StorageError, match="still supported"):
        lifecycle.publish("op-3", "ws-1", DerivedDelta(operation_id="op-3", snapshot=snapshot, staged_revision_id="rev-3", conflict_ids_to_retire=[conflict.id]), snapshot.epoch)


def test_delete_keeps_other_active_source_and_cleanup_recovers() -> None:
    graph, vectors = InMemoryGraphRepository(), InMemoryVectorRepository()
    lifecycle = StorageLifecycle(graph, vectors)
    first = _setup_add(graph, lifecycle, document_id="doc-1", operation_id="op-1", revision_id="rev-1", suffix="one")
    _publish_add(graph, lifecycle, operation_id="op-1", revision_id="rev-1")
    second = _setup_add(graph, lifecycle, document_id="doc-2", operation_id="op-2", revision_id="rev-2", suffix="two")
    _publish_add(graph, lifecycle, operation_id="op-2", revision_id="rev-2")

    graph.create_operation(_operation("delete-1", "doc-1", None, kind="delete", expected="rev-1"))
    snapshot = graph.get_snapshot("ws-1")
    receipt = lifecycle.publish("delete-1", "ws-1", DerivedDelta(operation_id="delete-1", snapshot=snapshot), snapshot.epoch)
    assert receipt.publication_kind == "deletion"
    vectors.fail_next_cleanup = True
    with pytest.raises(VectorStageError):
        lifecycle.cleanup("delete-1", "ws-1")
    assert graph.get_snapshot("ws-1").active_revision_ids == ["rev-2"]
    assert graph.get_operation("delete-1", "ws-1").state.value == "running"
    lifecycle.recover_cleanup("delete-1", "ws-1")
    snapshot = graph.get_snapshot("ws-1")
    assert vectors.vector_candidates([0.2, 0.1], snapshot, 10) == [second.chunks[0].id]
    assert first.chunks[0].id not in graph.active_chunk_ids(snapshot)
    assert graph.get_operation("delete-1", "ws-1").state.value == "ready"


def test_fetch_evidence_bounds_nodes_and_edges_with_truncation_flag() -> None:
    graph, vectors = InMemoryGraphRepository(), InMemoryVectorRepository()
    lifecycle = StorageLifecycle(graph, vectors)
    batch = _setup_add(graph, lifecycle)
    _publish_add(graph, lifecycle)
    snapshot = graph.get_snapshot("ws-1")

    # Add 250 dummy chunks to test the 200 node / chunk bounding and truncation flag
    for idx in range(250):
        cid = f"extra-chunk-{idx}"
        graph.chunks[cid] = Chunk(
            id=cid,
            workspace_id="ws-1",
            document_id="doc-1",
            revision_id="rev-1",
            index=idx + 1,
            text=f"Extra chunk {idx}",
            text_hash=f"hash-{idx}",
            location=ChunkLocation(start_offset=0, end_offset=10),
        )

    all_ids = [f"extra-chunk-{idx}" for idx in range(250)]
    evidence = graph.fetch_evidence(all_ids, snapshot)
    assert len(evidence.chunks) == 200
    assert evidence.truncated is True

    # Under limit: truncation flag is False
    small_evidence = graph.fetch_evidence(all_ids[:5], snapshot)
    assert len(small_evidence.chunks) == 5
    assert small_evidence.truncated is False

