from datetime import datetime, timezone
import os
from unittest.mock import MagicMock

import pytest

from backend.contracts.integration import CorpusSnapshot, DerivedDelta, ExtractionBatch
from backend.contracts.models import Chunk, ChunkLocation, Document, Entity, Evidence, Operation, Relation, Revision
from backend.storage import (
    EpochConflict,
    GraphRepository,
    Neo4jGraphRepository,
    OperationConflict,
    StorageError,
    WorkspaceViolation,
)
from backend.storage.neo4j import ALLOWED_RELATION_TYPES, _safe_relation_type

UTC = datetime(2026, 10, 24, tzinfo=timezone.utc)


def test_neo4j_protocol_conformance() -> None:
    mock_driver = MagicMock()
    repo = Neo4jGraphRepository(driver=mock_driver)
    assert isinstance(repo, GraphRepository)


def test_safe_relation_type_allowlist() -> None:
    assert _safe_relation_type("supports") == "SUPPORTS"
    assert _safe_relation_type("CONTRADICTS") == "CONTRADICTS"
    assert _safe_relation_type("RELATED_TO") == "RELATED_TO"
    # Injection or unknown model text never becomes raw Cypher syntax
    assert _safe_relation_type("random_predicate'); DROP ALL") == "RELATED_TO"
    assert _safe_relation_type("unknown_relation_type") == "RELATED_TO"


def test_neo4j_mocked_document_registration_workspace_violation() -> None:
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session

    mock_tx = MagicMock()
    mock_session.execute_write.side_effect = lambda fn: fn(mock_tx)

    # Document already belongs to another workspace
    mock_tx.run.return_value.single.return_value = {"ws": "ws-other"}

    repo = Neo4jGraphRepository(driver=mock_driver)
    doc = Document(id="doc-1", workspace_id="ws-my", filename="doc.txt", source_type="txt", created_at=UTC)

    with pytest.raises(WorkspaceViolation, match="already belongs to another workspace"):
        repo.register_document(doc)


def test_neo4j_mocked_operation_not_found() -> None:
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_session.run.return_value.single.return_value = None

    repo = Neo4jGraphRepository(driver=mock_driver)
    with pytest.raises(StorageError, match="operation not found"):
        repo.get_operation("op-missing", "ws-1")


def test_neo4j_mocked_claim_operation() -> None:
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_tx = MagicMock()
    mock_session.execute_write.side_effect = lambda fn: fn(mock_tx)

    op_queued = Operation(
        id="op-1", workspace_id="ws-1", document_id="doc-1", kind="add",
        new_revision_id="rev-1", stage="queued", accepted_at=UTC, deadline_at=UTC,
    )
    mock_tx.run.return_value.single.return_value = {"ws": "ws-1", "json": op_queued.model_dump_json()}

    repo = Neo4jGraphRepository(driver=mock_driver)
    claimed = repo.claim_operation("op-1", "ws-1")
    assert claimed.stage == "running"
    assert claimed.state.value == "running"


def test_neo4j_mocked_stage_revision_validations() -> None:
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_tx = MagicMock()
    mock_session.execute_write.side_effect = lambda fn: fn(mock_tx)

    # 1. Operation is DELETE -> cannot stage revision
    op_delete = Operation(
        id="op-del", workspace_id="ws-1", document_id="doc-1", kind="delete",
        stage="running", state="running", accepted_at=UTC, deadline_at=UTC,
    )
    mock_tx.run.return_value.single.return_value = {"json": op_delete.model_dump_json()}

    repo = Neo4jGraphRepository(driver=mock_driver)
    rev = Revision(
        id="rev-1", document_id="doc-1", content_hash="h", parser_version="p",
        chunker_version="c", extractor_version="x", embedding_version="e", state="staged",
        source_ref="s", created_at=UTC,
    )
    with pytest.raises(OperationConflict, match="delete operations cannot stage revisions"):
        repo.stage_revision("op-del", rev)


def test_neo4j_mocked_publish_epoch_conflict() -> None:
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_tx = MagicMock()
    mock_session.execute_write.side_effect = lambda fn: fn(mock_tx)

    op = Operation(
        id="op-1", workspace_id="ws-1", document_id="doc-1", kind="add",
        new_revision_id="rev-1", stage="running", state="running", accepted_at=UTC, deadline_at=UTC,
    )
    # op_rec
    def mock_run(query: str, **kwargs: object) -> MagicMock:
        res = MagicMock()
        if "o:Operation" in query:
            res.single.return_value = {"json": op.model_dump_json(), "receipt": None}
        elif "w:Workspace" in query:
            # Current epoch is 2
            res.single.return_value = {"epoch": 2, "active_revs": ["rev-0"]}
        else:
            res.single.return_value = None
        return res

    mock_tx.run.side_effect = mock_run

    repo = Neo4jGraphRepository(driver=mock_driver)
    snapshot = CorpusSnapshot(workspace_id="ws-1", epoch=1, active_revision_ids=["rev-0"], captured_at=UTC)
    delta = DerivedDelta(operation_id="op-1", snapshot=snapshot, staged_revision_id="rev-1")

    # expected_epoch is 1, but authoritative epoch is 2
    with pytest.raises(EpochConflict, match="expected epoch no longer matches"):
        repo.publish("op-1", delta, expected_epoch=1)



@pytest.mark.skipif(
    not (os.environ.get("NEO4J_URI") and os.environ.get("NEO4J_PASSWORD")),
    reason="NEO4J_URI and NEO4J_PASSWORD not provided; skipping live AuraDB round-trip test",
)
def test_live_neo4j_auradb_roundtrip() -> None:
    repo = Neo4jGraphRepository()
    try:
        repo._driver.verify_connectivity()
    except Exception as exc:
        pytest.skip(f"Live Neo4j AuraDB unreachable: {exc}")

    ws = f"ws-live-{int(datetime.now().timestamp())}"
    doc_id = f"doc-{ws}"
    op_id = f"op-{ws}"
    rev_id = f"rev-{ws}"

    try:
        repo.ensure_schema()

        # 1. Register Document
        doc = Document(id=doc_id, workspace_id=ws, filename=f"{doc_id}.txt", source_type="txt", created_at=UTC)
        repo.register_document(doc)

        # 2. Create Operation & Stage Revision
        op = Operation(
            id=op_id,
            workspace_id=ws,
            document_id=doc_id,
            kind="add",
            new_revision_id=rev_id,
            stage="queued",
            accepted_at=UTC,
            deadline_at=UTC,
        )
        repo.create_operation(op)
        claimed = repo.claim_operation(op_id, ws)
        assert claimed.stage == "running"

        rev = Revision(
            id=rev_id,
            document_id=doc_id,
            content_hash="h1",
            parser_version="p1",
            chunker_version="c1",
            extractor_version="x1",
            embedding_version="e1",
            state="staged",
            source_ref="s1",
            created_at=UTC,
        )
        repo.stage_revision(op_id, rev)

        # 3. Stage Batch
        chunk_text = "Alice founded TechCorp in 2020."
        chunk = Chunk(
            id=f"c-{rev_id}",
            workspace_id=ws,
            document_id=doc_id,
            revision_id=rev_id,
            index=0,
            text=chunk_text,
            text_hash="h-chunk",
            location=ChunkLocation(start_offset=0, end_offset=len(chunk_text)),
        )
        e1 = Entity(id=f"e1-{ws}", workspace_id=ws, name="Alice", normalized_name="alice", type="Person")
        e2 = Entity(id=f"e2-{ws}", workspace_id=ws, name="TechCorp", normalized_name="techcorp", type="Organization")
        rel = Relation(
            id=f"rel-{rev_id}",
            workspace_id=ws,
            revision_id=rev_id,
            subject_id=e1.id,
            object_entity_id=e2.id,
            predicate="FOUNDED_BY",
            predicate_original="founded",
            polarity="positive",
            modality="asserted",
            evidence=Evidence(chunk_id=chunk.id, start=0, end=len(chunk_text), quote=chunk_text),
            extraction_method="fixture",
            extraction_model="fixture",
            extraction_version="v1",
        )
        batch = ExtractionBatch(
            workspace_id=ws,
            document_id=doc_id,
            revision_id=rev_id,
            embedding_version="e1",
            embedding_dimension=2,
            chunks=[chunk],
            entities=[e1, e2],
            relations=[rel],
            chunk_vectors={chunk.id: [0.1, 0.2]},
        )
        repo.stage_batch(op_id, batch)

        staged_batch = repo.get_staged_batch(op_id, ws)
        assert staged_batch.document_id == doc_id

        # 4. Publish
        snap_before = repo.get_snapshot(ws)
        assert snap_before.active_revision_ids == []

        delta = DerivedDelta(operation_id=op_id, snapshot=snap_before, staged_revision_id=rev_id)
        receipt = repo.publish(op_id, delta, snap_before.epoch)
        assert receipt.active_revision_id == rev_id

        snap_after = repo.get_snapshot(ws)
        assert snap_after.active_revision_ids == [rev_id]
        assert snap_after.epoch == snap_before.epoch + 1

        # 5. Active chunk IDs and evidence
        active_chunks = repo.active_chunk_ids(snap_after)
        assert active_chunks == [chunk.id]

        evidence_pkg = repo.fetch_evidence([chunk.id], snap_after)
        assert len(evidence_pkg.chunks) == 1
        assert len(evidence_pkg.relations) == 1

        lexical = repo.lexical_candidates("TechCorp", snap_after, limit=5)
        assert lexical == [chunk.id]

        paths = repo.expand_paths([e1.id], snap_after, max_hops=1)
        assert len(paths) >= 1

        # 6. Cleanup & Mark Ready
        repo.cleanup(op_id, ws)
        repo.mark_ready_after_probe(op_id, ws)

        final_op = repo.get_operation(op_id, ws)
        assert final_op.state.value == "ready"

    finally:
        # Teardown workspace data
        with repo._driver.session(database=repo._database) as session:
            session.run(
                """
                MATCH (n) WHERE n.workspace_id = $ws
                DETACH DELETE n
                """,
                ws=ws,
            ).consume()
            session.run("MATCH (w:Workspace {id: $ws}) DETACH DELETE w", ws=ws).consume()
        repo.close()
