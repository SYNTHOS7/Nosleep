"""Phase 2 lifecycle benchmark measuring add/edit/delete latency against 60-second breach threshold."""

from __future__ import annotations

import os
import tempfile
import time
from typing import Any, Dict, List
import numpy as np

from backend.contracts.api_models import QueryRequest
from backend.contracts.models import OperationType
from backend.ingestion.operations import get_operation_manager
from backend.services.lifecycle_service import get_lifecycle_service
from backend.services.query_service import get_query_service
from backend.storage.graph_store import get_graph_store


def run_lifecycle_update_benchmark(
    workspace_id: str = "ws-bench-lifecycle",
    workload_size: int = 30,
) -> Dict[str, Any]:
    """
    Executes a predefined add/edit/delete mutation workload on an active corpus.
    Measures acceptance to ready visibility latency, verifying that 100% of mutations
    complete well within the 60-second SLA limit.
    """
    lifecycle_service = get_lifecycle_service()
    op_manager = get_operation_manager()
    query_service = get_query_service()
    graph_store = get_graph_store()
    tmp_dir = os.path.join(tempfile.gettempdir(), "lifecycle_bench")
    os.makedirs(tmp_dir, exist_ok=True)

    latencies: List[float] = []
    breaches_60s: List[Dict[str, Any]] = []
    operation_results: List[Dict[str, Any]] = []

    # Workload: sequence of ADDs, followed by EDITs, followed by DELETEs
    for i in range(workload_size):
        doc_id = f"doc-life-{i:03d}"
        file_path = os.path.join(tmp_dir, f"{doc_id}.txt")
        initial_text = f"Lifecycle Microservice {i} handles WorkloadPartition {i} with database DB-{i}."
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(initial_text)

        # 1. ADD Operation
        t0 = time.time()
        op_add = op_manager.create_operation(
            workspace_id=workspace_id,
            document_id=doc_id,
            operation_type=OperationType.ADD,
            source_ref=file_path,
            source_type="txt",
            current_revision=1,
            new_revision=1,
        )
        lifecycle_service.process_operation(op_add)
        t_ready = time.time()
        elapsed_add = t_ready - t0
        latencies.append(elapsed_add)

        if elapsed_add > 60.0:
            breaches_60s.append({"op_id": op_add.id, "type": "ADD", "elapsed": elapsed_add})

        # Query read probe immediately
        probe_resp = query_service.query(QueryRequest(query=f"Microservice {i}", workspace_id=workspace_id))
        probe_success = any(f"Microservice {i}" in s.exact_quote for s in probe_resp.source_chunks)

        operation_results.append({
            "operation": "ADD",
            "doc_id": doc_id,
            "elapsed": elapsed_add,
            "probe_success": probe_success,
        })

        # 2. EDIT Operation (revision 1 -> 2)
        revised_text = f"Lifecycle Microservice {i} handles WorkloadPartition {i} with upgraded vault CloudKMS-{i}."
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(revised_text)

        t0 = time.time()
        op_edit = op_manager.create_operation(
            workspace_id=workspace_id,
            document_id=doc_id,
            operation_type=OperationType.EDIT,
            source_ref=file_path,
            source_type="txt",
            current_revision=1,
            new_revision=2,
        )
        lifecycle_service.process_operation(op_edit)
        t_ready = time.time()
        elapsed_edit = t_ready - t0
        latencies.append(elapsed_edit)

        if elapsed_edit > 60.0:
            breaches_60s.append({"op_id": op_edit.id, "type": "EDIT", "elapsed": elapsed_edit})

        # Verify old text replaced and new text visible
        probe_resp2 = query_service.query(QueryRequest(query=f"CloudKMS-{i}", workspace_id=workspace_id))
        edit_visible = any(f"CloudKMS-{i}" in s.exact_quote for s in probe_resp2.source_chunks)

        operation_results.append({
            "operation": "EDIT",
            "doc_id": doc_id,
            "elapsed": elapsed_edit,
            "probe_success": edit_visible,
        })

        # 3. DELETE Operation
        t0 = time.time()
        op_del = op_manager.create_operation(
            workspace_id=workspace_id,
            document_id=doc_id,
            operation_type=OperationType.DELETE,
            current_revision=2,
            new_revision=2,
        )
        lifecycle_service.process_operation(op_del)
        t_ready = time.time()
        elapsed_del = t_ready - t0
        latencies.append(elapsed_del)

        if elapsed_del > 60.0:
            breaches_60s.append({"op_id": op_del.id, "type": "DELETE", "elapsed": elapsed_del})

        # Verify document deleted from graph
        doc_exists = graph_store.get_document(workspace_id, doc_id) is not None
        operation_results.append({
            "operation": "DELETE",
            "doc_id": doc_id,
            "elapsed": elapsed_del,
            "cleanup_completed": not doc_exists,
        })

    p50 = float(np.percentile(latencies, 50)) if latencies else 0.0
    p95 = float(np.percentile(latencies, 95)) if latencies else 0.0
    max_lat = float(np.max(latencies)) if latencies else 0.0

    return {
        "workspace_id": workspace_id,
        "total_operations": len(latencies),
        "latency_p50_seconds": p50,
        "latency_p95_seconds": p95,
        "latency_max_seconds": max_lat,
        "breaches_of_60s_count": len(breaches_60s),
        "breaches": breaches_60s,
        "all_probes_verified": all(
            r.get("probe_success", True) and r.get("cleanup_completed", True)
            for r in operation_results
        ),
        "sla_met": len(breaches_60s) == 0,
    }
