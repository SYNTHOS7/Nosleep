"""Core ingestion pipeline orchestrator implementing the 6 required canonical interfaces."""

import os
import time
from typing import Dict, List, Literal, Optional

from backend.contracts.models import (
    CandidateGraph,
    Chunk,
    Document,
    Entity,
    ExtractionBatch,
    Operation,
    OperationStatus,
    OperationType,
    ParsedSource,
    Relation,
    ValueNode,
)
from backend.ingestion.chunker import chunk_source
from backend.ingestion.embedder import embed_texts
from backend.ingestion.extractor import extract_chunk
from backend.ingestion.metrics import OperationMetricsTracker
from backend.ingestion.operations import get_operation_manager
from backend.ingestion.parser import parse_source


def build_batch(operation: Operation) -> ExtractionBatch:
    """
    Builds and stages a complete ExtractionBatch for an operation.
    Coordinates parsing, chunking, extraction, embeddings, and aggregation.
    """
    op_manager = get_operation_manager()
    metrics = OperationMetricsTracker(operation_id=operation.id, accepted_time=operation.accepted_at)

    if operation.operation_type == OperationType.DELETE:
        # Delete runs NO extraction and NO embedding calls
        doc = Document(
            id=operation.document_id,
            workspace_id=operation.workspace_id,
            source_name=operation.source_ref or "deleted-doc",
            source_type=operation.source_type or "txt",
            content_hash="deleted",
            revision=operation.current_revision,
        )
        batch = ExtractionBatch(
            operation_id=operation.id,
            workspace_id=operation.workspace_id,
            document=doc,
            revision=operation.current_revision,
            chunks=[],
            candidate_graphs=[],
            aggregated_entities=[],
            aggregated_relations=[],
            aggregated_values=[],
            vectors={},
            warnings=["Document marked for deletion; no extraction or embeddings performed."],
            status="STAGED",
        )
        operation.status = OperationStatus.STAGED
        operation.ready_at = time.time()
        op_manager.save_checkpoint(operation, batch)
        return batch

    if not operation.source_ref or not operation.source_type:
        raise ValueError(f"Operation {operation.id} missing source_ref or source_type.")

    # 1. Parsing stage
    operation.status = OperationStatus.PARSING
    op_manager.save_checkpoint(operation)

    with metrics.time_stage("parsing"):
        parsed = parse_source(operation.source_ref, operation.source_type)

    metrics.byte_count = parsed.byte_size
    metrics.page_count = parsed.page_count

    raw_fname = os.path.basename(operation.source_ref)
    clean_fname = raw_fname[len(operation.document_id) + 1 :] if raw_fname.startswith(f"{operation.document_id}_") else raw_fname

    doc = Document(
        id=operation.document_id,
        workspace_id=operation.workspace_id,
        source_name=clean_fname,
        source_type=operation.source_type,
        content_hash=parsed.content_hash,
        revision=operation.new_revision,
    )

    # 2. Chunking stage
    operation.status = OperationStatus.CHUNKING
    op_manager.save_checkpoint(operation)

    with metrics.time_stage("chunk_cache"):
        chunks = chunk_source(parsed, doc, revision=operation.new_revision)

    metrics.chunk_count = len(chunks)

    # 3. Extraction stage
    operation.status = OperationStatus.EXTRACTING
    op_manager.save_checkpoint(operation)

    candidate_graphs: List[CandidateGraph] = []
    aggregated_entities_map: Dict[str, Entity] = {}
    aggregated_values_map: Dict[str, ValueNode] = {}
    aggregated_relations: List[Relation] = []
    batch_warnings: List[str] = []

    with metrics.time_stage("extraction"):
        for chunk in chunks:
            cgraph = extract_chunk(chunk)
            candidate_graphs.append(cgraph)
            batch_warnings.extend(cgraph.warnings)

            # Exact name/type aggregation without fuzzy merge
            for ent in cgraph.entities:
                key = f"{ent.label}::{ent.name}"
                if key not in aggregated_entities_map:
                    aggregated_entities_map[key] = ent

            for val in cgraph.values:
                if val.id not in aggregated_values_map:
                    aggregated_values_map[val.id] = val

            aggregated_relations.extend(cgraph.relations)

    metrics.entity_count = len(aggregated_entities_map)
    metrics.relation_count = len(aggregated_relations)
    metrics.value_count = len(aggregated_values_map)

    # 4. Embeddings stage
    operation.status = OperationStatus.EMBEDDING
    op_manager.save_checkpoint(operation)

    vectors_map: Dict[str, List[float]] = {}
    if chunks:
        chunk_texts = [c.text for c in chunks]
        with metrics.time_stage("embeddings"):
            try:
                raw_vectors = embed_texts(chunk_texts, purpose="document")
                for c, v in zip(chunks, raw_vectors):
                    c.embedding = v
                    vectors_map[c.id] = v
                metrics.vector_count = len(vectors_map)
            except Exception as e:
                # If embedding fails during edit, previous active revision must be preserved
                operation.status = OperationStatus.FAILED
                operation.error_message = f"Embedding failure: {e}"
                op_manager.save_checkpoint(operation)
                raise

    # 5. Build ExtractionBatch
    operation.status = OperationStatus.VALIDATING
    op_manager.save_checkpoint(operation)

    batch = ExtractionBatch(
        operation_id=operation.id,
        workspace_id=operation.workspace_id,
        document=doc,
        revision=operation.new_revision,
        chunks=chunks,
        candidate_graphs=candidate_graphs,
        aggregated_entities=list(aggregated_entities_map.values()),
        aggregated_relations=aggregated_relations,
        aggregated_values=list(aggregated_values_map.values()),
        vectors=vectors_map,
        warnings=batch_warnings,
        status="STAGED",
    )

    # Stage batch artifact
    with metrics.time_stage("stage_batch"):
        op_manager.save_checkpoint(operation, batch)

    metrics.mark_ready()
    operation.ready_at = metrics.ready_time
    operation.stage_timings = metrics.stage_durations
    operation.metrics = metrics.model_dump()
    operation.status = OperationStatus.STAGED

    if operation.operation_type == OperationType.EDIT:
        # Populate delta records for Person 3
        operation.new_affected_records = {
            "document_id": doc.id,
            "revision": doc.revision,
            "chunk_ids": [c.id for c in chunks],
            "entity_ids": [e.id for e in aggregated_entities_map.values()],
            "relation_ids": [r.id for r in aggregated_relations],
        }

    op_manager.save_checkpoint(operation, batch)
    return batch


def run_operation(operation_id: str) -> None:
    """
    Executes a durable operation synchronously or inside the worker pool.
    Updates disk checkpoints and stage metrics.
    """
    op_manager = get_operation_manager()
    operation = op_manager.active_operations.get(operation_id) or op_manager.load_checkpoint(operation_id)
    if not operation:
        raise ValueError(f"Operation {operation_id} not found.")

    try:
        build_batch(operation)
        operation.status = OperationStatus.COMPLETED
        op_manager.save_checkpoint(operation)
    except Exception as e:
        operation.status = OperationStatus.FAILED
        operation.error_message = str(e)
        op_manager.save_checkpoint(operation)
        raise
    finally:
        op_manager.release_lock(operation.document_id)
