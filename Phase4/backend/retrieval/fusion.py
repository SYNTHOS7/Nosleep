"""
Reciprocal Rank Fusion (RRF) module.
Combines multiple ranked candidate lists (e.g., Chroma vector search + Neo4j lexical search)
into a unified ranking.
"""

from __future__ import annotations
from typing import Dict, List, Tuple


def reciprocal_rank_fusion(
    ranked_lists: List[List[str]],
    k: int = 60,
    limit: int = 10,
) -> List[Tuple[str, float]]:
    """
    Computes reciprocal rank fusion across multiple ranked lists of chunk IDs.
    Score = sum(1.0 / (k + rank)) for each ranking list where chunk appears.
    Returns:
        List of (chunk_id, fused_score) sorted descending by score.
    """
    scores: Dict[str, float] = {}

    for ranked_list in ranked_lists:
        for rank_0, chunk_id in enumerate(ranked_list):
            rank_1 = rank_0 + 1
            scores[chunk_id] = scores.get(chunk_id, 0.0) + (1.0 / (k + rank_1))

    sorted_candidates = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_candidates[:limit]
