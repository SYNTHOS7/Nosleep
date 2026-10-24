"""
Topic representative selection and grounded labeling module.
Selects central (medoid) and diverse chunks for each cluster,
and generates labels and descriptions strictly from representative chunks.
"""

from __future__ import annotations
import math
from typing import List, Tuple
import numpy as np

from backend.contracts.models import Chunk, Topic
from backend.adapters.llm import LLMAdapterProtocol, GroundedLLMAdapter


def select_representative_chunks(
    chunk_ids: List[str],
    vectors: List[List[float]],
    max_diverse: int = 2,
) -> Tuple[str, List[str], List[float]]:
    """
    Selects representative chunks for a cluster:
    1. Medoid / central chunk: vector closest to the arithmetic centroid.
    2. Diverse chunks: vectors with maximal Euclidean/cosine distance from medoid.
    Returns:
        medoid_chunk_id, diverse_chunk_ids, centroid_vector
    """
    if not chunk_ids:
        raise ValueError("Cannot select representatives from empty cluster")

    arr = np.array(vectors, dtype=np.float64)
    centroid = np.mean(arr, axis=0)
    # Normalize centroid
    c_norm = np.linalg.norm(centroid)
    if c_norm > 0:
        centroid = centroid / c_norm

    # Distances to centroid
    dists_to_centroid = np.linalg.norm(arr - centroid, axis=1)
    medoid_idx = int(np.argmin(dists_to_centroid))
    medoid_id = chunk_ids[medoid_idx]

    diverse_ids: List[str] = []
    if len(chunk_ids) > 1:
        # Distance to medoid
        medoid_vec = arr[medoid_idx]
        dists_to_medoid = np.linalg.norm(arr - medoid_vec, axis=1)
        # Sort descending
        sorted_indices = np.argsort(dists_to_medoid)[::-1]
        for idx in sorted_indices:
            cid = chunk_ids[idx]
            if cid != medoid_id:
                diverse_ids.append(cid)
                if len(diverse_ids) >= max_diverse:
                    break

    return medoid_id, diverse_ids, centroid.tolist()


def create_grounded_topic(
    workspace_id: str,
    topic_id: str,
    cluster_chunks: List[Chunk],
    cluster_vectors: List[List[float]],
    llm_adapter: LLMAdapterProtocol,
    cluster_version: str = "cluster-v1",
    embedding_version: str = "multilingual-embed-v1",
) -> Topic:
    """
    Creates a Topic record grounded strictly in representative chunks.
    """
    chunk_ids = [c.id for c in cluster_chunks]
    medoid_id, diverse_ids, centroid = select_representative_chunks(chunk_ids, cluster_vectors)

    all_rep_ids = [medoid_id] + diverse_ids
    rep_chunks = [c for c in cluster_chunks if c.id in all_rep_ids]

    label, description = llm_adapter.generate_topic_label(rep_chunks)

    return Topic(
        id=topic_id,
        workspace_id=workspace_id,
        label=label,
        description=description,
        cluster_version=cluster_version,
        embedding_version=embedding_version,
        centroid=centroid,
        representative_chunk_ids=all_rep_ids,
        summary_evidence_ids=all_rep_ids,
        summary_status="fresh",
        active=True,
    )
