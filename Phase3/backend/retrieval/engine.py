"""
Retrieval engine module.
Coordinates vector search, lexical search, RRF fusion, bounded graph traversal,
thematic summary packaging, and topic scope enforcement.
"""

from __future__ import annotations
from typing import List, Optional, Set

from backend.contracts.models import (
    Chunk,
    EvidencePackage,
    EvidencePath,
    QueryPlan,
    QueryRequest,
    Topic,
)
from backend.storage.interface import CorpusSnapshot, StorageRepositoryProtocol
from backend.adapters.embedding import EmbeddingAdapterProtocol, DeterministicMultilingualEmbeddingAdapter
from backend.retrieval.fusion import reciprocal_rank_fusion


def retrieve(
    plan: QueryPlan,
    request: QueryRequest,
    snapshot: CorpusSnapshot,
    storage_repo: StorageRepositoryProtocol,
    embedding_adapter: Optional[EmbeddingAdapterProtocol] = None,
) -> EvidencePackage:
    """
    Executes retrieval according to the QueryPlan.
    Enforces active-revision isolation and topic scope filtering.
    """
    embedding_adapter = embedding_adapter or DeterministicMultilingualEmbeddingAdapter()
    target_topics = plan.target_topic_ids if request.scope == "selected" else None

    # Handle Thematic Query
    if plan.query_type == "thematic":
        active_topics = [
            t for t in snapshot.topics.values()
            if t.active and (target_topics is None or t.id in target_topics)
        ]
        # Collect representative chunks from active topics
        rep_chunk_ids: Set[str] = set()
        for t in active_topics:
            for cid in t.representative_chunk_ids:
                if cid in snapshot.chunks and snapshot.is_chunk_active(snapshot.chunks[cid]):
                    rep_chunk_ids.add(cid)

        # Fetch evidence for representative chunks
        package = storage_repo.fetch_evidence(list(rep_chunk_ids), snapshot)
        package.topics = active_topics

        # Check bounds and truncation
        total_active_chunks = len(snapshot.get_active_chunks())
        package.searched_count = len(package.chunks)
        package.available_count = total_active_chunks

        # If active corpus has more chunks than the bounded summary package, flag truncation
        if total_active_chunks > len(package.chunks):
            package.truncated = True
            package.limitations.append(
                f"Thematic overview represents top {len(active_topics)} clusters across {len(package.chunks)} "
                f"representative chunks. Corpus contains {total_active_chunks} total active chunks. "
                "Broad answer cannot claim exhaustive themes from top-k alone."
            )

        return package

    # Handle Local or Hybrid Query
    # 1. Vector candidates
    vector_candidates: List[str] = []
    if plan.use_vector:
        query_vectors = embedding_adapter.embed_texts([request.question], purpose="query")
        query_vec = query_vectors[0]
        vector_candidates = storage_repo.vector_candidates(
            query_vec,
            snapshot,
            limit=plan.top_k * 2,
            topic_ids=target_topics,
        )

    # 2. Lexical candidates
    lexical_candidates: List[str] = []
    if plan.use_lexical:
        lexical_candidates = storage_repo.lexical_candidates(
            request.question,
            snapshot,
            limit=plan.top_k * 2,
            topic_ids=target_topics,
        )

    # 3. Reciprocal Rank Fusion
    ranked_lists = []
    if vector_candidates:
        ranked_lists.append(vector_candidates)
    if lexical_candidates:
        ranked_lists.append(lexical_candidates)

    if ranked_lists:
        fused = reciprocal_rank_fusion(ranked_lists, k=60, limit=plan.top_k)
        candidate_chunk_ids = [cid for cid, _ in fused]
    else:
        candidate_chunk_ids = []

    # If active-filtered ANN returns no candidates or underfilled
    package = storage_repo.fetch_evidence(candidate_chunk_ids, snapshot)

    total_active_chunks = len(snapshot.get_active_chunks())
    package.searched_count = len(candidate_chunk_ids)
    package.available_count = total_active_chunks

    if not candidate_chunk_ids:
        package.limitations.append(
            "Underfilled active-filtered retrieval: No matching active chunks found under the current topic scope."
        )
        return package

    # 4. Graph expansion for local/hybrid
    if plan.use_graph:
        # Find entities involved in retrieved chunks or matching question terms
        entity_ids = [e.id for e in package.entities]
        # Also check for query entity matches
        q_lower = request.question.lower()
        for e in snapshot.entities.values():
            if e.name.lower() in q_lower and e.id not in entity_ids:
                entity_ids.append(e.id)

        if entity_ids:
            paths = storage_repo.expand_paths(
                entity_ids=entity_ids[:10],
                snapshot=snapshot,
                max_hops=plan.max_hops,
                topic_ids=target_topics,
            )
            package.paths = paths

    return package
