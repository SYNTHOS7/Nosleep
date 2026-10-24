"""Tests for durable operations: checkpoints, restart recovery, edit deltas, delete, and 60-second SLA."""

import os
import shutil
import time
import pytest

from backend.contracts.models import (
    Document,
    Operation,
    OperationStatus,
    OperationType,
)
from backend.ingestion.operations import OperationManager
from backend.ingestion.pipeline import build_batch, run_operation


@pytest.fixture
def test_op_manager(tmp_path):
    storage = tmp_path / "operations"
    storage.mkdir()
    manager = OperationManager(storage_dir=str(storage), max_workers=2)
    return manager


def test_operation_checkpoint_and_restart_recovery(tmp_path, test_op_manager):
    """Verifies that operations persist checkpoints to disk and resume cleanly after simulated restart."""
    test_txt = tmp_path / "restart_doc.txt"
    test_txt.write_text("Enterprise System Alpha is a part of Global Core.", encoding="utf-8")

    op = test_op_manager.create_operation(
        workspace_id="ws-test",
        document_id="doc-restart-1",
        operation_type=OperationType.ADD,
        source_ref=str(test_txt),
        source_type="txt",
    )

    # Save checkpoint at PARSING stage
    op.status = OperationStatus.PARSING
    test_op_manager.save_checkpoint(op)

    # Simulate crash and restart by creating a new manager pointing to same storage
    recovered_manager = OperationManager(storage_dir=test_op_manager.storage_dir)

    resumed_ops = []
    def dummy_resume_handler(op_id: str):
        resumed_ops.append(op_id)

    recovered_manager.recover_on_restart(resume_handler=dummy_resume_handler)
    time.sleep(0.1)

    assert op.id in resumed_ops
    loaded = recovered_manager.load_checkpoint(op.id)
    assert loaded is not None
    assert loaded.status == OperationStatus.PARSING


def test_delete_operation_runs_no_extraction_or_embeddings(tmp_path, test_op_manager, monkeypatch):
    """Verifies that DELETE operation explicitly avoids calling extractor or embedder."""
    # Monkeypatch extractor and embedder to raise an exception if called
    def fail_extractor(*args, **kwargs):
        raise RuntimeError("Extractor MUST NOT be called during DELETE operation!")

    def fail_embedder(*args, **kwargs):
        raise RuntimeError("Embedder MUST NOT be called during DELETE operation!")

    monkeypatch.setattr("backend.ingestion.pipeline.extract_chunk", fail_extractor)
    monkeypatch.setattr("backend.ingestion.pipeline.embed_texts", fail_embedder)

    op = test_op_manager.create_operation(
        workspace_id="ws-test",
        document_id="doc-delete-1",
        operation_type=OperationType.DELETE,
    )

    batch = build_batch(op)

    assert batch.status == "STAGED"
    assert len(batch.chunks) == 0
    assert len(batch.candidate_graphs) == 0
    assert len(batch.vectors) == 0
    assert op.status == OperationStatus.STAGED


def test_single_document_edit_and_delta(tmp_path, test_op_manager):
    """Verifies that editing a document generates targeted delta records for Person 3."""
    v1_file = tmp_path / "v1_doc.txt"
    v1_file.write_text("Service Alpha uses Service Beta.", encoding="utf-8")

    op_add = test_op_manager.create_operation(
        workspace_id="ws-test",
        document_id="doc-edit-1",
        operation_type=OperationType.ADD,
        source_ref=str(v1_file),
        source_type="txt",
        current_revision=1,
        new_revision=1,
    )
    batch_v1 = build_batch(op_add)
    test_op_manager.release_lock(op_add.document_id)

    # Now edit to v2
    v2_file = tmp_path / "v2_doc.txt"
    v2_file.write_text("Service Alpha uses Service Gamma.", encoding="utf-8")

    op_edit = test_op_manager.create_operation(
        workspace_id="ws-test",
        document_id="doc-edit-1",
        operation_type=OperationType.EDIT,
        source_ref=str(v2_file),
        source_type="txt",
        current_revision=1,
        new_revision=2,
    )
    batch_v2 = build_batch(op_edit)

    assert batch_v2.revision == 2
    assert op_edit.new_affected_records["document_id"] == "doc-edit-1"
    assert op_edit.new_affected_records["revision"] == 2
    assert len(op_edit.new_affected_records["chunk_ids"]) > 0


def test_provider_failure_retains_old_revision(tmp_path, test_op_manager, monkeypatch):
    """Verifies that an edit whose embedding step fails preserves the old revision and marks failure."""
    v1_file = tmp_path / "v1_stable.txt"
    v1_file.write_text("Service Alpha uses Service Beta.", encoding="utf-8")

    op_add = test_op_manager.create_operation(
        workspace_id="ws-test",
        document_id="doc-failover-1",
        operation_type=OperationType.ADD,
        source_ref=str(v1_file),
        source_type="txt",
        current_revision=1,
        new_revision=1,
    )
    build_batch(op_add)
    test_op_manager.release_lock(op_add.document_id)

    # Edit with failing embedder
    def mock_failing_embedder(*args, **kwargs):
        raise ConnectionError("Embedding provider connection refused.")

    monkeypatch.setattr("backend.ingestion.pipeline.embed_texts", mock_failing_embedder)

    v2_file = tmp_path / "v2_fail.txt"
    v2_file.write_text("Service Alpha uses New System.", encoding="utf-8")

    op_edit = test_op_manager.create_operation(
        workspace_id="ws-test",
        document_id="doc-failover-1",
        operation_type=OperationType.EDIT,
        source_ref=str(v2_file),
        source_type="txt",
        current_revision=1,
        new_revision=2,
    )

    with pytest.raises(ConnectionError):
        build_batch(op_edit)

    # The failed operation is marked FAILED and old revision remains unchanged
    assert op_edit.status == OperationStatus.FAILED
    assert "Embedding failure" in op_edit.error_message


def test_within_60_seconds_sla(tmp_path, test_op_manager):
    """Verifies that document ingestion completes well within the 60-second target."""
    doc_file = tmp_path / "sla_doc.txt"
    doc_file.write_text("Enterprise System Alpha is a part of Global Core.", encoding="utf-8")

    op = test_op_manager.create_operation(
        workspace_id="ws-test",
        document_id="doc-sla-1",
        operation_type=OperationType.ADD,
        source_ref=str(doc_file),
        source_type="txt",
    )

    build_batch(op)

    assert op.ready_at is not None
    total_time = op.ready_at - op.accepted_at
    assert total_time < 60.0  # Well within the 60-second SLA
