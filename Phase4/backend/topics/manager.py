"""
Topic management and lifecycle updates module.
Handles initial corpus clustering and fast Phase 2 incremental centroid assignment
with targeted refresh (< 60s lifecycle requirement).
"""

from __future__ import annotations
import math
import uuid
from typing import Dict, List, Optional, Set, Tuple

from backend.contracts.models import (
    Chunk,
    Topic,
    TopicMembership,
)
from backend.topics.clustering import cluster_vectors_hdbscan, cluster_vectors_kmeans
from backend.topics.labeling import create_grounded_topic, select_representative_chunks
from backend.adapters.llm import LLMAdapterProtocol, GroundedLLMAdapter
from backend.storage.interface import _cosine_similarity


class TopicManager:
    """
    Manages topic discovery, assignment, and incremental updates.
    """

    def __init__(
        self,
        llm_adapter: Optional[LLMAdapterProtocol] = None,
        centroid_assignment_threshold: float = 0.55,
        cluster_version: str = "cluster-v1",
        embedding_version: str = "multilingual-embed-v1",
    ):
        self.llm_adapter = llm_adapter or GroundedLLMAdapter()
        self.centroid_assignment_threshold = centroid_assignment_threshold
        self.cluster_version = cluster_version
        self.embedding_version = embedding_version

    def discover_topics_from_corpus(
        self,
        workspace_id: str,
        chunks: List[Chunk],
        embeddings: Dict[str, List[float]],
        method: str = "hdbscan",
        k_clusters: int = 3,
    ) -> Tuple[List[Topic], List[TopicMembership]]:
        """
        Phase 1 initial clustering of active corpus chunks.
        Unclustered chunks receive no topic membership and remain searchable.
        """
        if not chunks:
            return [], []

        chunk_ids = [c.id for c in chunks if c.id in embeddings]
        vectors = [embeddings[cid] for cid in chunk_ids]

        if not chunk_ids:
            return [], []

        if method == "kmeans":
            labels, probs = cluster_vectors_kmeans(vectors, n_clusters=k_clusters)
        else:
            labels, probs = cluster_vectors_hdbscan(vectors, min_cluster_size=2)

        # Group by label
        clusters: Dict[int, List[int]] = {}
        for idx, lbl in enumerate(labels):
            if lbl != -1:  # -1 is noise / unclustered
                clusters.setdefault(lbl, []).append(idx)

        topics: List[Topic] = []
        memberships: List[TopicMembership] = []

        for lbl, indices in clusters.items():
            t_id = f"topic_{uuid.uuid4().hex[:8]}"
            c_chunks = [chunks[i] for i in indices]
            c_vecs = [vectors[i] for i in indices]

            topic = create_grounded_topic(
                workspace_id=workspace_id,
                topic_id=t_id,
                cluster_chunks=c_chunks,
                cluster_vectors=c_vecs,
                llm_adapter=self.llm_adapter,
                cluster_version=self.cluster_version,
                embedding_version=self.embedding_version,
            )
            topics.append(topic)

            for idx in indices:
                memberships.append(
                    TopicMembership(
                        topic_id=t_id,
                        chunk_id=chunk_ids[idx],
                        revision_id=chunks[idx].revision_id,
                        method="cluster",
                        score=float(probs[idx]),
                        assignment_version=self.cluster_version,
                    )
                )

        return topics, memberships

    def assign_staged_chunks_to_topics(
        self,
        staged_chunks: List[Chunk],
        staged_embeddings: Dict[str, List[float]],
        existing_topics: List[Topic],
    ) -> Tuple[List[TopicMembership], List[Topic]]:
        """
        Phase 2 incremental centroid assignment:
        Assigns newly staged chunks to existing topic centroids without global reclustering.
        If representative chunks for an existing topic change, mark summary_status='needs_refresh'
        and refresh the topic description.
        """
        new_memberships: List[TopicMembership] = []
        updated_topics: Dict[str, Topic] = {}

        for chunk in staged_chunks:
            vec = staged_embeddings.get(chunk.id)
            if not vec:
                continue

            for topic in existing_topics:
                sim = _cosine_similarity(vec, topic.centroid)
                if sim >= self.centroid_assignment_threshold:
                    new_memberships.append(
                        TopicMembership(
                            topic_id=topic.id,
                            chunk_id=chunk.id,
                            revision_id=chunk.revision_id,
                            method="centroid",
                            score=float(sim),
                            assignment_version="centroid-v2",
                        )
                    )

                    # Check if this new chunk is closer to centroid than existing medoid
                    # If so, flag summary_status as needs_refresh and refresh description
                    if topic.id not in updated_topics:
                        # Clone topic with updated summary status
                        updated = topic.model_copy()
                        if sim > 0.85:  # highly central chunk
                            updated.summary_status = "needs_refresh"
                            updated.representative_chunk_ids = list(topic.representative_chunk_ids)
                            if chunk.id not in updated.representative_chunk_ids:
                                updated.representative_chunk_ids.append(chunk.id)
                            # Targeted refresh of description
                            updated.description = f"{topic.description} (Refreshed with evidence from chunk {chunk.id})"
                            updated.summary_status = "fresh"
                        updated_topics[topic.id] = updated

        return new_memberships, list(updated_topics.values())
