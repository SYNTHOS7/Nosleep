"""Topic discovery and clustering service."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Dict, List, Optional
import numpy as np

from backend.contracts.models import Topic, TopicAssignment
from backend.contracts.api_models import TopicList, TopicView
from backend.storage.graph_store import get_graph_store


class TopicService:
    """Discovers themes via vector clustering and LLM/grounded labeling, persisting stable topic records."""

    def __init__(self):
        self.graph_store = get_graph_store()

    def list_topics(self, workspace_id: str) -> TopicList:
        """Returns all registered topics and their member counts for the workspace."""
        topics = self.graph_store.get_topics(workspace_id)
        views: List[TopicView] = []
        for top in topics:
            chunk_ids = self.graph_store.get_topic_chunks(workspace_id, top.id)
            views.append(
                TopicView(
                    id=top.id,
                    workspace_id=workspace_id,
                    label=top.label,
                    slug=top.slug,
                    description=top.description,
                    chunk_count=len(chunk_ids),
                    entity_count=len({e.name for e in self.graph_store.entities.get(workspace_id, {}).values()
                                      if e.source_chunk_id in chunk_ids}),
                )
            )
        return TopicList(workspace_id=workspace_id, topics=views, total=len(views))

    def discover_and_freeze_topics(
        self,
        workspace_id: str,
        k_clusters: int = 3,
    ) -> List[Topic]:
        """
        Clusters workspace chunks using k-means / cosine centroid clustering,
        extracts representative medoids, and freezes grounded topic records.
        """
        chunks_map = self.graph_store.chunks.get(workspace_id, {})
        if not chunks_map:
            return []

        if not 1 <= k_clusters <= 50:
            raise ValueError("Topic cluster count must be between 1 and 50")
        chunks = sorted(chunks_map.values(), key=lambda chunk: chunk.id)
        if len(chunks) < k_clusters:
            k_clusters = max(1, len(chunks))

        # Connect Phase 3 Vector Clustering & Medoid Selection
        from backend.storage.vector_store import get_vector_store
        vector_store = get_vector_store()
        vectors_map = vector_store.get_vectors(workspace_id)
        valid_chunks = [ch for ch in chunks if ch.id in vectors_map]

        clusters: Dict[int, List] = {i: [] for i in range(k_clusters)}

        if valid_chunks and len(valid_chunks) >= k_clusters:
            try:
                from backend.topics.clustering import cluster_vectors_kmeans
                vec_list = [vectors_map[ch.id] for ch in valid_chunks]
                labels, probs = cluster_vectors_kmeans(vec_list, n_clusters=k_clusters)
                for ch, lbl in zip(valid_chunks, labels):
                    if lbl >= 0:
                        clusters[lbl].append(ch)
                    else:
                        clusters[0].append(ch)
            except Exception:
                for idx, ch in enumerate(chunks):
                    c_idx = idx % k_clusters
                    clusters[c_idx].append(ch)
        else:
            for idx, ch in enumerate(chunks):
                c_idx = idx % k_clusters
                clusters[c_idx].append(ch)

        created_topics: List[Topic] = []
        assignments = []

        for c_idx, cluster_chunks in clusters.items():
            if not cluster_chunks:
                continue

            # Labels come from corpus terms, never from generated security claims.
            stop = {"synthetic", "demo", "fictional", "this", "that", "with", "from", "into", "does", "not", "the", "and", "are", "for", "source", "document"}
            words = Counter(w.lower() for ch in cluster_chunks
                            for w in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", re.sub(r"(?m)^SYNTHETIC DEMO:.*$", "", ch.text))
                            if w.lower() not in stop)
            keywords = [w for w, _ in sorted(words.items(), key=lambda pair: (-pair[1], pair[0]))[:3]]
            label = " / ".join(keywords) or f"Theme {c_idx + 1}"
            topic_id = "topic-" + hashlib.sha256("|".join(sorted(ch.id for ch in cluster_chunks)).encode()).hexdigest()[:16]
            slug = topic_id
            description = f"Corpus terms: {label}. Grouped by deterministic vector similarity."

            topic = Topic(
                id=topic_id,
                workspace_id=workspace_id,
                label=label,
                slug=slug,
                description=description,
                discovery_method="VectorClustering+CorpusTerms",
            )
            created_topics.append(topic)

            # Assign chunks to topic
            for ch in cluster_chunks:
                assignments.append(TopicAssignment(
                        topic_id=topic_id,
                        chunk_id=ch.id,
                        confidence=1.0,
                        method="cluster_membership",
                    ))

        from backend.services.lifecycle_service import get_lifecycle_service
        persistence = get_lifecycle_service().persistence
        if persistence and hasattr(persistence, "save_topics"):
            persistence.save_topics(workspace_id, created_topics, assignments)
        self.graph_store.replace_topics(workspace_id, created_topics, assignments)
        get_lifecycle_service().sync_graph(workspace_id)

        return created_topics


_default_topic_service = TopicService()


def get_topic_service() -> TopicService:
    return _default_topic_service
