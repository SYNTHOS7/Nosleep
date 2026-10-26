"""Vector store with cosine similarity and workspace isolation."""

from typing import Dict, List, Optional, Tuple
import numpy as np


class VectorStore:
    """Thread-safe vector store with workspace partitioning."""

    def __init__(self):
        # workspace_id -> chunk_id -> vector (numpy array)
        self._vectors: Dict[str, Dict[str, np.ndarray]] = {}

    def upsert_vectors(self, workspace_id: str, chunk_vectors: Dict[str, List[float]]) -> None:
        """Stores or updates vectors for a specific workspace."""
        if workspace_id not in self._vectors:
            self._vectors[workspace_id] = {}
        for chunk_id, vec in chunk_vectors.items():
            arr = np.array(vec, dtype=np.float32)
            norm = np.linalg.norm(arr)
            if norm > 0:
                arr = arr / norm
            self._vectors[workspace_id][chunk_id] = arr

    def remove_chunks(self, workspace_id: str, chunk_ids: List[str]) -> None:
        """Removes specific chunks from the vector index."""
        if workspace_id in self._vectors:
            for cid in chunk_ids:
                self._vectors[workspace_id].pop(cid, None)

    def query(
        self,
        workspace_id: str,
        query_vector: List[float],
        top_k: int = 5,
        allowed_chunk_ids: Optional[List[str]] = None,
    ) -> List[Tuple[str, float]]:
        """
        Retrieves top_k chunks by cosine similarity within workspace.
        Returns list of (chunk_id, similarity_score).
        """
        if workspace_id not in self._vectors or not self._vectors[workspace_id]:
            return []

        q_arr = np.array(query_vector, dtype=np.float32)
        q_norm = np.linalg.norm(q_arr)
        if q_norm > 0:
            q_arr = q_arr / q_norm

        candidates = self._vectors[workspace_id]
        if allowed_chunk_ids is not None:
            allowed_set = set(allowed_chunk_ids)
            candidates = {cid: vec for cid, vec in candidates.items() if cid in allowed_set}

        if not candidates:
            return []

        scores: List[Tuple[str, float]] = []
        for chunk_id, vec in candidates.items():
            score = float(np.dot(q_arr, vec))
            scores.append((chunk_id, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def get_vectors(self, workspace_id: str) -> Dict[str, List[float]]:
        """Returns all vectors for the workspace as float lists."""
        if workspace_id not in self._vectors:
            return {}
        return {cid: vec.tolist() for cid, vec in self._vectors[workspace_id].items()}

    def clear(self) -> None:
        self._vectors.clear()


import os

_vector_backend = os.environ.get("VECTOR_BACKEND", "in_memory")
if _vector_backend == "firebase":
    from backend.storage.firebase_store import FirebaseVectorStore
    _default_vector_store = FirebaseVectorStore()
elif _vector_backend == "in_memory":
    _default_vector_store = VectorStore()
else:
    raise ValueError("VECTOR_BACKEND must be in_memory or firebase")


def get_vector_store() -> VectorStore:
    return _default_vector_store
