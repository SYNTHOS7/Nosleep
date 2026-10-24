"""Durable operation runner with disk checkpointing, bounded concurrency, and restart recovery."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, Optional

from backend.contracts.models import (
    ExtractionBatch,
    Operation,
    OperationStatus,
    OperationType,
)

OPERATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "operations")


class OperationManager:
    """Manages durable operations with disk checkpointing and bounded execution."""

    def __init__(self, storage_dir: str = OPERATIONS_DIR, max_workers: int = 4):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ingest-op")
        self.active_operations: Dict[str, Operation] = {}
        self.staged_batches: Dict[str, ExtractionBatch] = {}
        self.document_locks: Dict[str, str] = {}  # document_id -> operation_id

    def create_operation(
        self,
        workspace_id: str,
        document_id: str,
        operation_type: OperationType,
        source_ref: Optional[str] = None,
        source_type: Optional[str] = None,
        current_revision: int = 1,
        new_revision: int = 1,
    ) -> Operation:
        """Creates a new durable operation and saves initial checkpoint."""
        op_id = f"op-{operation_type.value.lower()}-{document_id[:8]}-{int(time.time()*1000)}"

        # Enforce: one operation owns one document at a time
        if document_id in self.document_locks:
            existing_op = self.document_locks[document_id]
            if existing_op in self.active_operations and self.active_operations[existing_op].status not in [
                OperationStatus.COMPLETED,
                OperationStatus.FAILED,
                OperationStatus.STAGED,
            ]:
                raise RuntimeError(f"Document {document_id} is currently locked by active operation {existing_op}.")

        op = Operation(
            id=op_id,
            workspace_id=workspace_id,
            document_id=document_id,
            operation_type=operation_type,
            source_ref=source_ref,
            source_type=source_type,
            status=OperationStatus.ACCEPTED,
            accepted_at=time.time(),
            current_revision=current_revision,
            new_revision=new_revision,
            checkpoint_path=self._get_checkpoint_path(op_id),
        )

        self.active_operations[op_id] = op
        self.document_locks[document_id] = op_id
        self.save_checkpoint(op)
        return op

    def _get_checkpoint_path(self, operation_id: str) -> str:
        op_folder = os.path.join(self.storage_dir, operation_id)
        os.makedirs(op_folder, exist_ok=True)
        return os.path.join(op_folder, "checkpoint.json")

    def save_checkpoint(self, operation: Operation, batch: Optional[ExtractionBatch] = None):
        """Persists the operation and staged batch to private disk artifacts."""
        path = operation.checkpoint_path or self._get_checkpoint_path(operation.id)
        op_dict = operation.model_dump()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(op_dict, f, indent=2)

        if batch is not None:
            batch_path = os.path.join(os.path.dirname(path), "staged_batch.json")
            with open(batch_path, "w", encoding="utf-8") as f:
                json.dump(batch.model_dump(), f, indent=2)
            self.staged_batches[operation.id] = batch

    def load_checkpoint(self, operation_id: str) -> Optional[Operation]:
        """Loads an operation from its disk checkpoint."""
        path = self._get_checkpoint_path(operation_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Operation.model_validate(data)

    def load_staged_batch(self, operation_id: str) -> Optional[ExtractionBatch]:
        """Loads staged extraction batch for an operation."""
        if operation_id in self.staged_batches:
            return self.staged_batches[operation_id]
        batch_path = os.path.join(os.path.dirname(self._get_checkpoint_path(operation_id)), "staged_batch.json")
        if os.path.exists(batch_path):
            with open(batch_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            batch = ExtractionBatch.model_validate(data)
            self.staged_batches[operation_id] = batch
            return batch
        return None

    def recover_on_restart(self, resume_handler: Callable[[str], None]):
        """
        Scans checkpoint directory on restart and resumes all non-terminal operations.
        """
        if not os.path.exists(self.storage_dir):
            return

        for op_dir in os.listdir(self.storage_dir):
            checkpoint_file = os.path.join(self.storage_dir, op_dir, "checkpoint.json")
            if os.path.exists(checkpoint_file):
                try:
                    with open(checkpoint_file, "r", encoding="utf-8") as f:
                        op = Operation.model_validate(json.load(f))
                    if op.status not in [OperationStatus.STAGED, OperationStatus.COMPLETED, OperationStatus.FAILED]:
                        # Resume non-terminal operation
                        self.active_operations[op.id] = op
                        self.document_locks[op.document_id] = op.id
                        self.executor.submit(resume_handler, op.id)
                except Exception:
                    pass

    def release_lock(self, document_id: str):
        self.document_locks.pop(document_id, None)


# Global operations manager instance
_op_manager = OperationManager()


def get_operation_manager() -> OperationManager:
    return _op_manager
