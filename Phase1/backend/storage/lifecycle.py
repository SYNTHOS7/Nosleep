"""Task 1 publication coordinator: graph state is authoritative; vectors are staged first."""

from __future__ import annotations

from backend.contracts.integration import DerivedDelta, ExtractionBatch, PublishReceipt, revalidate_extraction_batch
from backend.contracts.models import OperationKind

from .interfaces import GraphRepository, StorageError, VectorRepository, VectorStageError


class StorageLifecycle:
    """Coordinates non-atomic graph/vector writes without claiming distributed atomicity."""

    def __init__(self, graph: GraphRepository, vectors: VectorRepository) -> None:
        self.graph = graph
        self.vectors = vectors

    def stage_batch(self, operation_id: str, workspace_id: str, batch: ExtractionBatch) -> None:
        """Stage graph data then vectors; failed vector stage never changes active graph state."""
        checked = revalidate_extraction_batch(batch)
        self.graph.claim_operation(operation_id, workspace_id)
        self.graph.stage_batch(operation_id, checked)
        try:
            self.vectors.stage_batch(workspace_id, checked)
            self.vectors.verify_staged(workspace_id, checked)
        except VectorStageError as error:
            self.graph.mark_cleanup_pending(operation_id, workspace_id, f"vector_stage_pending: {error}")
            raise

    def publish(self, operation_id: str, workspace_id: str, delta: DerivedDelta, expected_epoch: int) -> PublishReceipt:
        """Verify staged vectors before the authoritative graph publication switch."""
        operation = self.graph.get_operation(operation_id, workspace_id)
        if operation.kind is not OperationKind.DELETE:
            batch = self.graph.get_staged_batch(operation_id, workspace_id)
            self.vectors.verify_staged(workspace_id, batch)
        receipt = self.graph.publish(operation_id, delta, expected_epoch)
        return receipt

    def cleanup(self, operation_id: str, workspace_id: str) -> None:
        """Idempotent cleanup/recovery; never reverts a successful graph publication."""
        try:
            self.graph.cleanup(operation_id, workspace_id)
            snapshot = self.graph.get_snapshot(workspace_id)
            self.vectors.cleanup(workspace_id, set(self.graph.active_chunk_ids(snapshot)))
            # A current snapshot and active vector candidate filter together form the read probe.
            self.graph.active_chunk_ids(snapshot)
            self.graph.mark_ready_after_probe(operation_id, workspace_id)
        except StorageError as error:
            self.graph.mark_cleanup_pending(operation_id, workspace_id, f"cleanup_pending: {error}")
            raise

    def recover_cleanup(self, operation_id: str, workspace_id: str) -> None:
        self.cleanup(operation_id, workspace_id)
