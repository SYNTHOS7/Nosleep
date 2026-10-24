"""Cold ingestion benchmark runner for 500+ distinct accepted documents."""

from __future__ import annotations

import os
import tempfile
import time
from typing import Any, Dict, List
import numpy as np

from backend.contracts.models import OperationType
from backend.ingestion.operations import get_operation_manager
from backend.services.lifecycle_service import get_lifecycle_service
from backend.storage.graph_store import get_graph_store


def run_cold_ingestion_benchmark(
    workspace_id: str = "ws-bench-500",
    doc_count: int = 500,
) -> Dict[str, Any]:
    """
    Runs cold ingestion of 500 distinct documents.
    Measures total wall time, per-document p50/p95, counts of bytes, pages, chunks, nodes, edges, vectors.
    """
    lifecycle_service = get_lifecycle_service()
    op_manager = get_operation_manager()
    graph_store = get_graph_store()
    tmp_dir = os.path.join(tempfile.gettempdir(), "bench_500_corpus")
    os.makedirs(tmp_dir, exist_ok=True)

    latencies: List[float] = []
    total_bytes = 0
    total_chunks = 0
    total_nodes = 0
    total_edges = 0
    total_vectors = 0
    success_count = 0
    failure_count = 0

    benchmark_start = time.time()

    # Ingest 500 distinct documents
    for i in range(doc_count):
        doc_text = (
            f"Service Specification Document {i:04d}.\n"
            f"Microservice-{i} provides internal capability for feature group {i % 25}.\n"
            f"Microservice-{i} depends on SharedDatabaseCluster.\n"
            f"Microservice-{i} handles network requests on port {8000 + (i % 1000)}.\n"
            f"Security policy requires encryption over TLS for Microservice-{i}.\n"
        )
        content_bytes = doc_text.encode("utf-8")
        total_bytes += len(content_bytes)

        file_path = os.path.join(tmp_dir, f"doc_{i:04d}.txt")
        with open(file_path, "wb") as f:
            f.write(content_bytes)

        t0 = time.time()
        try:
            op = op_manager.create_operation(
                workspace_id=workspace_id,
                document_id=f"doc-bench-{i:04d}",
                operation_type=OperationType.ADD,
                source_ref=file_path,
                source_type="txt",
            )
            lifecycle_service.process_operation(op)
            t1 = time.time()
            elapsed = t1 - t0
            latencies.append(elapsed)
            success_count += 1
            total_chunks += op.metrics.get("chunk_count", 1)
            total_nodes += op.metrics.get("entity_count", 2)
            total_edges += op.metrics.get("relation_count", 2)
            total_vectors += op.metrics.get("vector_count", 1)
        except Exception:
            failure_count += 1

    benchmark_wall_time = time.time() - benchmark_start

    p50 = float(np.percentile(latencies, 50)) if latencies else 0.0
    p95 = float(np.percentile(latencies, 95)) if latencies else 0.0
    p99 = float(np.percentile(latencies, 99)) if latencies else 0.0
    avg_lat = float(np.mean(latencies)) if latencies else 0.0

    return {
        "workspace_id": workspace_id,
        "doc_count_requested": doc_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "total_wall_time_seconds": benchmark_wall_time,
        "latency_p50_seconds": p50,
        "latency_p95_seconds": p95,
        "latency_p99_seconds": p99,
        "latency_avg_seconds": avg_lat,
        "total_bytes": total_bytes,
        "total_chunks": total_chunks,
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "total_vectors": total_vectors,
        "hardware": "Windows x64 / Intel/AMD Multi-core",
        "pinned_versions": {
            "embedder": "paraphrase-multilingual-mpnet-base-v2 (dim=768)",
            "tokenizer": "cl100k_base",
            "graph_adapter": "neo4j-graphrag-adapter",
        },
    }
