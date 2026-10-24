from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.contracts.integration import CorpusSnapshot, ExtractionBatch
from backend.contracts.models import Chunk, ChunkLocation, Document, Entity, Evidence, Relation
from backend.storage import (
    ChromaVectorRepository,
    InMemoryGraphRepository,
    StorageLifecycle,
    VectorRepository,
    VectorStageError,
)

UTC = datetime(2026, 10, 24, tzinfo=timezone.utc)


def _batch(
    document_id: str,
    revision_id: str,
    *,
    workspace_id: str = "ws-chroma-test",
    suffix: str = "item1",
    dimension: int = 2,
    embedding_version: str = "embed-v1",
    vector: list[float] | None = None,
) -> ExtractionBatch:
    chunk_id = f"chunk-{revision_id}"
    text = f"{suffix} text content for testing Chroma repository."
    chunk = Chunk(
        id=chunk_id,
        workspace_id=workspace_id,
        document_id=document_id,
        revision_id=revision_id,
        index=0,
        text=text,
        text_hash="hash",
        location=ChunkLocation(start_offset=0, end_offset=len(text)),
    )
    vec = vector or ([0.5, 0.25] if dimension == 2 else [0.1] * dimension)
    return ExtractionBatch(
        workspace_id=workspace_id,
        document_id=document_id,
        revision_id=revision_id,
        embedding_version=embedding_version,
        embedding_dimension=dimension,
        chunks=[chunk],
        entities=[],
        relations=[],
        chunk_vectors={chunk_id: vec},
    )


def test_chroma_protocol_conformance(tmp_path: Path) -> None:
    repo = ChromaVectorRepository(persist_directory=tmp_path)
    assert isinstance(repo, VectorRepository)


def test_chroma_stage_and_verify(tmp_path: Path) -> None:
    repo = ChromaVectorRepository(persist_directory=tmp_path)
    batch = _batch("doc-1", "rev-1")
    repo.stage_batch("ws-chroma-test", batch)
    repo.verify_staged("ws-chroma-test", batch)


def test_chroma_profile_mismatch_rejected(tmp_path: Path) -> None:
    repo = ChromaVectorRepository(persist_directory=tmp_path)
    batch1 = _batch("doc-1", "rev-1", dimension=2, embedding_version="v1")
    repo.stage_batch("ws-chroma-test", batch1)

    batch2 = _batch("doc-2", "rev-2", dimension=3, embedding_version="v1", vector=[0.1, 0.2, 0.3])
    with pytest.raises(VectorStageError, match="reindexing"):
        repo.stage_batch("ws-chroma-test", batch2)


def test_chroma_vector_candidates_filtering(tmp_path: Path) -> None:
    repo = ChromaVectorRepository(persist_directory=tmp_path)
    batch1 = _batch("doc-1", "rev-1", vector=[1.0, 0.0])
    batch2 = _batch("doc-2", "rev-2", vector=[0.0, 1.0])
    repo.stage_batch("ws-chroma-test", batch1)
    repo.stage_batch("ws-chroma-test", batch2)

    # Active revision is only rev-1; rev-2 must not be returned
    snapshot = CorpusSnapshot(
        workspace_id="ws-chroma-test",
        epoch=1,
        active_revision_ids=["rev-1"],
        captured_at=UTC,
    )
    candidates = repo.vector_candidates([1.0, 0.0], snapshot, limit=5)
    assert candidates == ["chunk-rev-1"]

    # When no active revisions, returns empty list
    empty_snapshot = CorpusSnapshot(
        workspace_id="ws-chroma-test",
        epoch=0,
        active_revision_ids=[],
        captured_at=UTC,
    )
    assert repo.vector_candidates([1.0, 0.0], empty_snapshot, limit=5) == []


def test_chroma_cleanup_retires_old_chunks(tmp_path: Path) -> None:
    repo = ChromaVectorRepository(persist_directory=tmp_path)
    batch1 = _batch("doc-1", "rev-1")
    batch2 = _batch("doc-1", "rev-2")
    repo.stage_batch("ws-chroma-test", batch1)
    repo.stage_batch("ws-chroma-test", batch2)

    # Clean up, keeping only rev-2 chunk
    repo.cleanup("ws-chroma-test", active_chunk_ids={"chunk-rev-2"})

    snapshot_rev1 = CorpusSnapshot(
        workspace_id="ws-chroma-test",
        epoch=1,
        active_revision_ids=["rev-1"],
        captured_at=UTC,
    )
    assert repo.vector_candidates([0.5, 0.25], snapshot_rev1, limit=5) == []

    snapshot_rev2 = CorpusSnapshot(
        workspace_id="ws-chroma-test",
        epoch=2,
        active_revision_ids=["rev-2"],
        captured_at=UTC,
    )
    assert repo.vector_candidates([0.5, 0.25], snapshot_rev2, limit=5) == ["chunk-rev-2"]


def test_chroma_lifecycle_coordination(tmp_path: Path) -> None:
    graph = InMemoryGraphRepository()
    vectors = ChromaVectorRepository(persist_directory=tmp_path)
    lifecycle = StorageLifecycle(graph=graph, vectors=vectors)

    ws = "ws-chroma-life"
    doc = Document(id="doc-1", workspace_id=ws, filename="doc-1.txt", source_type="txt", created_at=UTC)
    graph.register_document(doc)

    from tests.storage.test_lifecycle import _operation, _revision
    op = _operation("op-1", "doc-1", "rev-1", workspace_id=ws)
    graph.create_operation(op)
    graph.stage_revision("op-1", _revision("rev-1", "doc-1"))

    batch = _batch("doc-1", "rev-1", workspace_id=ws)
    lifecycle.stage_batch("op-1", ws, batch)

    from backend.contracts.integration import DerivedDelta
    snapshot = graph.get_snapshot(ws)
    lifecycle.publish("op-1", ws, DerivedDelta(operation_id="op-1", snapshot=snapshot, staged_revision_id="rev-1"), snapshot.epoch)
    lifecycle.cleanup("op-1", ws)

    updated_snap = graph.get_snapshot(ws)
    assert updated_snap.active_revision_ids == ["rev-1"]
    assert vectors.vector_candidates([0.5, 0.25], updated_snap, limit=5) == ["chunk-rev-1"]


def test_chroma_persistence_across_process_restart(tmp_path: Path) -> None:
    # 1. First process: stage batch in persistent Chroma and verify
    repo1 = ChromaVectorRepository(persist_directory=tmp_path)
    ws = "ws-chroma-persist"
    batch1 = _batch("doc-1", "rev-1", workspace_id=ws, vector=[0.8, 0.2])
    repo1.stage_batch(ws, batch1)
    repo1.verify_staged(ws, batch1)
    del repo1

    # 2. Simulated restart: open new repository instance pointing to same on-disk directory
    repo2 = ChromaVectorRepository(persist_directory=tmp_path)
    repo2.verify_staged(ws, batch1)

    snapshot = CorpusSnapshot(
        workspace_id=ws,
        epoch=1,
        active_revision_ids=["rev-1"],
        captured_at=UTC,
    )
    assert repo2.vector_candidates([0.8, 0.2], snapshot, limit=5) == ["chunk-rev-1"]

    # 3. Stage second batch, restart again, verify both persist
    batch2 = _batch("doc-2", "rev-2", workspace_id=ws, vector=[0.1, 0.9])
    repo2.stage_batch(ws, batch2)
    del repo2

    repo3 = ChromaVectorRepository(persist_directory=tmp_path)
    repo3.verify_staged(ws, batch1)
    repo3.verify_staged(ws, batch2)
    snapshot2 = CorpusSnapshot(
        workspace_id=ws,
        epoch=2,
        active_revision_ids=["rev-1", "rev-2"],
        captured_at=UTC,
    )
    candidates = repo3.vector_candidates([0.8, 0.2], snapshot2, limit=5)
    assert "chunk-rev-1" in candidates

