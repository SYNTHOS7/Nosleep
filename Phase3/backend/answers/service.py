"""
Query execution and response assembly service.
Handles epoch detection, retry-on-epoch-change, GraphSlice construction,
and QueryResponse assembly.
"""

from __future__ import annotations
import time
import uuid
from typing import Dict, List, Optional, Set

from backend.contracts.models import (
    GraphEdgeView,
    GraphNodeView,
    GraphSlice,
    QueryRequest,
    QueryResponse,
)
from backend.storage.interface import CorpusSnapshot, StorageRepositoryProtocol
from backend.adapters.embedding import EmbeddingAdapterProtocol, DeterministicMultilingualEmbeddingAdapter
from backend.adapters.llm import LLMAdapterProtocol, GroundedLLMAdapter
from backend.retrieval.planner import plan_query
from backend.retrieval.engine import retrieve
from backend.answers.synthesizer import synthesize


def build_graph_slice(
    package,
    snapshot: CorpusSnapshot,
    max_nodes: int = 200,
    max_edges: int = 300,
) -> GraphSlice:
    """
    Builds the bounded GraphSlice for UI rendering (max 200 nodes, 300 edges).
    Includes direct domain edges with relation_id & source_chunk_id,
    and topic-membership edges (visually distinct, never count as facts).
    """
    nodes: Dict[str, GraphNodeView] = {}
    edges: List[GraphEdgeView] = []
    truncated = False

    # 1. Add entity nodes
    for ent in package.entities:
        if len(nodes) < max_nodes:
            nodes[ent.id] = GraphNodeView(
                id=ent.id,
                label=ent.name,
                node_type="Entity",
                properties={"type": ent.type, "aliases": ent.aliases},
            )

    # 2. Add value nodes
    for val in package.values:
        if len(nodes) < max_nodes:
            nodes[val.id] = GraphNodeView(
                id=val.id,
                label=val.lexical_value,
                node_type="Value",
                properties={"kind": val.kind, "normalized": val.normalized_value},
            )

    # 3. Add chunk nodes
    for c in package.chunks:
        if len(nodes) < max_nodes:
            nodes[c.id] = GraphNodeView(
                id=c.id,
                label=f"Chunk {c.id}",
                node_type="Chunk",
                properties={"document_id": c.document_id, "revision_id": c.revision_id},
            )

    # 4. Add topic nodes
    for t in package.topics:
        if len(nodes) < max_nodes:
            nodes[t.id] = GraphNodeView(
                id=t.id,
                label=t.label,
                node_type="Topic",
                properties={"description": t.description, "active": t.active},
            )

    # 5. Add relation edges
    for rel in package.relations:
        if len(edges) >= max_edges:
            truncated = True
            break
        target_id = rel.object_entity_id or rel.object_value_id or ""
        edges.append(
            GraphEdgeView(
                id=f"edge_{rel.id}",
                source_id=rel.subject_id,
                target_id=target_id,
                predicate=rel.predicate,
                relation_id=rel.id,
                source_chunk_id=rel.evidence.chunk_id,
                is_topic_membership=False,
                properties={
                    "polarity": rel.polarity,
                    "modality": rel.modality,
                    "quote": rel.evidence.quote,
                },
            )
        )

    # 6. Add topic membership edges (visually distinct)
    chunk_ids = {c.id for c in package.chunks}
    for mem in snapshot.topic_memberships:
        if mem.chunk_id in chunk_ids:
            if len(edges) >= max_edges:
                truncated = True
                break
            edges.append(
                GraphEdgeView(
                    id=f"topic_mem_{mem.topic_id}_{mem.chunk_id}",
                    source_id=mem.topic_id,
                    target_id=mem.chunk_id,
                    predicate="HAS_MEMBER",
                    relation_id=None,
                    source_chunk_id=mem.chunk_id,
                    is_topic_membership=True,
                    properties={"method": mem.method, "score": mem.score},
                )
            )

    return GraphSlice(
        nodes=list(nodes.values()),
        edges=edges,
        truncated=truncated,
    )


def execute_query(
    request: QueryRequest,
    storage_repo: StorageRepositoryProtocol,
    embedding_adapter: Optional[EmbeddingAdapterProtocol] = None,
    llm_adapter: Optional[LLMAdapterProtocol] = None,
) -> QueryResponse:
    """
    Executes a query end-to-end:
    - Obtains snapshot
    - Detects epoch change during building; repeats once or returns retry_required
    - Routes, retrieves, synthesizes, and constructs GraphSlice
    """
    start_time = time.perf_counter()
    embedding_adapter = embedding_adapter or DeterministicMultilingualEmbeddingAdapter()
    llm_adapter = llm_adapter or GroundedLLMAdapter()
    request_id = f"req_{uuid.uuid4().hex[:10]}"
    warnings: List[str] = []

    # Get initial snapshot
    snapshot = storage_repo.get_snapshot(request.workspace_id)
    initial_epoch = snapshot.epoch

    # Attempt execution with up to 1 retry on epoch change
    max_attempts = 2
    for attempt in range(max_attempts):
        plan = plan_query(request, snapshot)
        package = retrieve(
            plan=plan,
            request=request,
            snapshot=snapshot,
            storage_repo=storage_repo,
            embedding_adapter=embedding_adapter,
        )

        # Determine response language
        lang = plan.query_language if request.answer_language == "auto" else request.answer_language
        if lang not in ("en", "hi"):
            lang = "en"

        statements = synthesize(
            request=request,
            package=package,
            llm_adapter=llm_adapter,
            language=lang,
        )

        # Check if epoch changed during retrieval/synthesis
        latest_snapshot = storage_repo.get_snapshot(request.workspace_id)
        if latest_snapshot.epoch != initial_epoch:
            if attempt == 0:
                warnings.append("Epoch change detected during query execution. Retrying once with latest snapshot.")
                snapshot = latest_snapshot
                initial_epoch = snapshot.epoch
                continue
            else:
                # Second attempt also saw epoch change -> return retry_required
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                return QueryResponse(
                    request_id=request_id,
                    corpus_epoch=latest_snapshot.epoch,
                    status="retry_required",
                    language=lang,
                    plan=plan,
                    statements=[],
                    evidence=package,
                    graph=GraphSlice(nodes=[], edges=[], truncated=False),
                    latency_ms=round(latency_ms, 2),
                    warnings=["Corpus epoch changed concurrently during query execution; retry required."],
                )

        # Build GraphSlice
        graph_slice = build_graph_slice(package, snapshot)

        # Check status
        has_evidence = bool(package.chunks or package.relations)
        status = "answered" if has_evidence else "insufficient_evidence"

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        return QueryResponse(
            request_id=request_id,
            corpus_epoch=initial_epoch,
            status=status,
            language=lang,
            plan=plan,
            statements=statements,
            evidence=package,
            graph=graph_slice,
            latency_ms=round(latency_ms, 2),
            warnings=warnings + package.limitations,
        )

    # Fallback return
    latency_ms = (time.perf_counter() - start_time) * 1000.0
    return QueryResponse(
        request_id=request_id,
        corpus_epoch=initial_epoch,
        status="retry_required",
        language="en",
        plan=plan_query(request, snapshot),
        statements=[],
        evidence=package,
        graph=GraphSlice(),
        latency_ms=round(latency_ms, 2),
        warnings=["Query failed to stabilize across epoch changes."],
    )
