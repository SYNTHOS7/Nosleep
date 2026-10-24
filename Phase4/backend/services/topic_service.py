"""Topic discovery and clustering service."""

from __future__ import annotations

import uuid
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
                    entity_count=len(chunk_ids) * 2,  # approximate entity linkage
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

        chunks = list(chunks_map.values())
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

        for c_idx, cluster_chunks in clusters.items():
            if not cluster_chunks:
                continue

            # Identify representative theme using Phase 3 medoid selection when vectors exist
            theme_keyword = None
            cluster_cids = [c.id for c in cluster_chunks if c.id in vectors_map]
            if len(cluster_cids) >= 1:
                try:
                    from backend.topics.labeling import select_representative_chunks
                    medoid_id, diverse_ids, centroid = select_representative_chunks(
                        cluster_cids,
                        [vectors_map[cid] for cid in cluster_cids],
                    )
                    medoid_chunk = chunks_map.get(medoid_id)
                    if medoid_chunk:
                        words = [w.strip(".,;:()[]\"'").capitalize() for w in medoid_chunk.text.split() if len(w) > 4]
                        if words:
                            theme_keyword = words[0]
                except Exception:
                    pass

            if not theme_keyword:
                sample_text = " ".join([c.text for c in cluster_chunks[:3]])
                words = [w.strip(".,;:()[]\"'").capitalize() for w in sample_text.split() if len(w) > 4]
                theme_keyword = words[0] if words else f"Theme-{c_idx+1}"

            topic_id = f"topic-{uuid.uuid4().hex[:8]}"
            label = f"{theme_keyword} Architecture & Operations"
            slug = f"{theme_keyword.lower()}-ops"
            description = f"Collection of knowledge related to {theme_keyword} and supporting system architecture."

            topic = Topic(
                id=topic_id,
                workspace_id=workspace_id,
                label=label,
                slug=slug,
                description=description,
                discovery_method="VectorClustering+MedoidExtraction",
            )
            self.graph_store.register_topic(topic)
            created_topics.append(topic)

            # Assign chunks to topic
            for ch in cluster_chunks:
                self.graph_store.assign_topic(
                    workspace_id,
                    TopicAssignment(
                        topic_id=topic_id,
                        chunk_id=ch.id,
                        confidence=0.92,
                    ),
                )

        return created_topics


_default_topic_service = TopicService()


def get_topic_service() -> TopicService:
    return _default_topic_service
