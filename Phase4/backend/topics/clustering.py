"""
Topic clustering and evaluation module.
Implements HDBSCAN and K-means clustering, along with quantitative comparison metrics
as specified in 03-topics-retrieval-answers-and-conflicts.md:
- Topic coherence
- Duplicate/overlap rate
- Coverage
- Stability on rerun
- Broad-question usefulness
- Runtime
- Labeling cost
"""

from __future__ import annotations
import math
import time
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from sklearn.cluster import HDBSCAN, KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score


def _cosine_distance_matrix(vectors: np.ndarray) -> np.ndarray:
    # vectors: (N, D), assumed normalized
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normed = vectors / norms
    sim = np.dot(normed, normed.T)
    # Clamp to [-1.0, 1.0]
    sim = np.clip(sim, -1.0, 1.0)
    return 1.0 - sim


def cluster_vectors_hdbscan(
    vectors: List[List[float]],
    min_cluster_size: int = 2,
    min_samples: Optional[int] = 1,
) -> Tuple[List[int], List[float]]:
    """
    Cluster vectors using HDBSCAN.
    Returns:
        labels: list of cluster IDs (-1 indicates unclustered/noise)
        probabilities: confidence scores for each point
    """
    if len(vectors) < 2:
        return [0] * len(vectors), [1.0] * len(vectors)

    arr = np.array(vectors, dtype=np.float64)
    # HDBSCAN from scikit-learn
    clusterer = HDBSCAN(
        min_cluster_size=min(min_cluster_size, len(vectors)),
        min_samples=min_samples,
        metric="euclidean",
        copy=True,
    )
    labels = clusterer.fit_predict(arr).tolist()
    probs = clusterer.probabilities_.tolist() if hasattr(clusterer, "probabilities_") else [1.0] * len(labels)
    return labels, probs


def cluster_vectors_kmeans(
    vectors: List[List[float]],
    n_clusters: int = 3,
    random_state: int = 42,
) -> Tuple[List[int], List[float]]:
    """
    Cluster vectors using K-means.
    Returns:
        labels: list of cluster IDs
        probabilities: distance-based confidence scores
    """
    n_clusters = max(1, min(n_clusters, len(vectors)))
    arr = np.array(vectors, dtype=np.float64)
    km = KMeans(n_clusters=n_clusters, random_state=random_state, n_init=10)
    labels = km.fit_predict(arr).tolist()

    # Calculate confidence as inverse distance to centroid
    centroids = km.cluster_centers_
    probs = []
    for i, vec in enumerate(arr):
        cluster_id = labels[i]
        c = centroids[cluster_id]
        dist = np.linalg.norm(vec - c)
        prob = 1.0 / (1.0 + float(dist))
        probs.append(prob)

    return labels, probs


def evaluate_clustering_comparison(
    chunk_ids: List[str],
    vectors: List[List[float]],
    texts: List[str],
    k_clusters: int = 3,
    runs: int = 3,
) -> Dict[str, Any]:
    """
    Evaluates HDBSCAN versus K-means on the same frozen pilot corpus.
    Compares:
    1. Topic coherence (Silhouette score)
    2. Duplicate/overlap rate (Centroid cosine similarity)
    3. Coverage (Fraction of non-noise points)
    4. Stability on rerun (Adjusted Rand Index across runs)
    5. Broad-question usefulness (Entropy of cluster distribution)
    6. Runtime (Total milliseconds)
    7. Labeling cost (Number of active clusters)
    """
    arr = np.array(vectors, dtype=np.float64)
    n_samples = len(chunk_ids)

    results: Dict[str, Any] = {
        "corpus_size": n_samples,
        "runs": runs,
        "hdbscan": {},
        "kmeans": {},
        "recommendation": "",
        "freeze_config": {},
    }

    if n_samples < 3:
        # Trivial corpus
        results["hdbscan"] = {"coherence": 1.0, "coverage": 1.0, "stability": 1.0, "runtime_ms": 1.0, "num_clusters": 1}
        results["kmeans"] = {"coherence": 1.0, "coverage": 1.0, "stability": 1.0, "runtime_ms": 1.0, "num_clusters": 1}
        results["recommendation"] = "HDBSCAN"
        results["freeze_config"] = {"method": "hdbscan", "min_cluster_size": 2}
        return results

    # 1. HDBSCAN Evaluation
    hdb_runtimes = []
    hdb_all_labels = []
    for r in range(runs):
        t0 = time.perf_counter()
        labels, _ = cluster_vectors_hdbscan(vectors, min_cluster_size=2)
        dt = (time.perf_counter() - t0) * 1000.0
        hdb_runtimes.append(dt)
        hdb_all_labels.append(labels)

    hdb_main_labels = hdb_all_labels[0]
    hdb_non_noise = [l for l in hdb_main_labels if l != -1]
    hdb_coverage = len(hdb_non_noise) / n_samples if n_samples > 0 else 0.0
    hdb_unique_clusters = set(hdb_non_noise)

    # Coherence (Silhouette on non-noise if > 1 cluster)
    if len(hdb_unique_clusters) > 1 and len(hdb_non_noise) > len(hdb_unique_clusters):
        valid_indices = [i for i, l in enumerate(hdb_main_labels) if l != -1]
        hdb_coherence = float(silhouette_score(arr[valid_indices], [hdb_main_labels[i] for i in valid_indices]))
    else:
        hdb_coherence = 0.5  # Neutral baseline if single cluster

    # Stability ARI across runs
    if runs > 1:
        aris = [adjusted_rand_score(hdb_all_labels[0], hdb_all_labels[r]) for r in range(1, runs)]
        hdb_stability = float(np.mean(aris))
    else:
        hdb_stability = 1.0

    # Overlap rate (cosine similarity between cluster centroids)
    hdb_overlap = 0.0
    if len(hdb_unique_clusters) > 1:
        centroids = []
        for c_id in sorted(hdb_unique_clusters):
            c_indices = [i for i, l in enumerate(hdb_main_labels) if l == c_id]
            centroids.append(np.mean(arr[c_indices], axis=0))
        c_mat = np.array(centroids)
        norms = np.linalg.norm(c_mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        c_normed = c_mat / norms
        sims = np.dot(c_normed, c_normed.T)
        triu = sims[np.triu_indices(len(centroids), k=1)]
        hdb_overlap = float(np.mean(triu)) if len(triu) > 0 else 0.0

    # Broad usefulness (Shannon entropy of cluster distribution)
    counts = [hdb_main_labels.count(c_id) for c_id in hdb_unique_clusters]
    total_non_noise = sum(counts)
    hdb_entropy = 0.0
    if total_non_noise > 0:
        for cnt in counts:
            p = cnt / total_non_noise
            hdb_entropy -= p * math.log2(p)

    results["hdbscan"] = {
        "coherence": round(hdb_coherence, 4),
        "coverage": round(hdb_coverage, 4),
        "stability": round(hdb_stability, 4),
        "overlap_rate": round(hdb_overlap, 4),
        "broad_usefulness_entropy": round(hdb_entropy, 4),
        "runtime_ms": round(float(np.mean(hdb_runtimes)), 2),
        "num_clusters": len(hdb_unique_clusters),
        "unclustered_chunks": hdb_main_labels.count(-1),
    }

    # 2. K-means Evaluation
    km_runtimes = []
    km_all_labels = []
    for r in range(runs):
        t0 = time.perf_counter()
        labels, _ = cluster_vectors_kmeans(vectors, n_clusters=k_clusters, random_state=42 + r)
        dt = (time.perf_counter() - t0) * 1000.0
        km_runtimes.append(dt)
        km_all_labels.append(labels)

    km_main_labels = km_all_labels[0]
    km_coverage = 1.0  # K-means forces 100% coverage
    km_unique_clusters = set(km_main_labels)

    if len(km_unique_clusters) > 1:
        km_coherence = float(silhouette_score(arr, km_main_labels))
    else:
        km_coherence = 0.5

    if runs > 1:
        aris = [adjusted_rand_score(km_all_labels[0], km_all_labels[r]) for r in range(1, runs)]
        km_stability = float(np.mean(aris))
    else:
        km_stability = 1.0

    km_overlap = 0.0
    if len(km_unique_clusters) > 1:
        centroids = []
        for c_id in sorted(km_unique_clusters):
            c_indices = [i for i, l in enumerate(km_main_labels) if l == c_id]
            centroids.append(np.mean(arr[c_indices], axis=0))
        c_mat = np.array(centroids)
        norms = np.linalg.norm(c_mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        c_normed = c_mat / norms
        sims = np.dot(c_normed, c_normed.T)
        triu = sims[np.triu_indices(len(centroids), k=1)]
        km_overlap = float(np.mean(triu)) if len(triu) > 0 else 0.0

    counts = [km_main_labels.count(c_id) for c_id in km_unique_clusters]
    km_entropy = 0.0
    for cnt in counts:
        p = cnt / n_samples
        km_entropy -= p * math.log2(p)

    results["kmeans"] = {
        "coherence": round(km_coherence, 4),
        "coverage": round(km_coverage, 4),
        "stability": round(km_stability, 4),
        "overlap_rate": round(km_overlap, 4),
        "broad_usefulness_entropy": round(km_entropy, 4),
        "runtime_ms": round(float(np.mean(km_runtimes)), 2),
        "num_clusters": len(km_unique_clusters),
        "unclustered_chunks": 0,
    }

    # Recommendation logic:
    # HDBSCAN is preferred when it discovers natural organic density without forcing arbitrary k,
    # and leaves noisy outliers unclustered so they do not contaminate topic labels.
    if hdb_stability >= 0.8 and hdb_coverage >= 0.6:
        results["recommendation"] = "HDBSCAN"
        results["freeze_config"] = {
            "method": "hdbscan",
            "min_cluster_size": 2,
            "min_samples": 1,
            "metric": "euclidean",
            "embedding_version": "multilingual-embed-v1",
        }
    else:
        results["recommendation"] = "K-means"
        results["freeze_config"] = {
            "method": "kmeans",
            "n_clusters": k_clusters,
            "random_state": 42,
            "embedding_version": "multilingual-embed-v1",
        }

    return results
