"""
Tests for topic clustering and evaluation (HDBSCAN vs K-means comparison).
"""

import unittest
import numpy as np

from backend.topics.clustering import (
    cluster_vectors_hdbscan,
    cluster_vectors_kmeans,
    evaluate_clustering_comparison,
)


class TestClusteringComparison(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        # Create 3 distinct synthetic vector clusters in 64-dim space
        cluster_a = np.random.normal(loc=1.0, scale=0.1, size=(5, 64))
        cluster_b = np.random.normal(loc=-1.0, scale=0.1, size=(5, 64))
        cluster_c = np.random.normal(loc=0.0, scale=0.1, size=(5, 64))
        noise = np.random.uniform(low=-2.0, high=2.0, size=(2, 64))

        all_vecs = np.vstack([cluster_a, cluster_b, cluster_c, noise])
        norms = np.linalg.norm(all_vecs, axis=1, keepdims=True)
        self.vectors = (all_vecs / norms).tolist()
        self.chunk_ids = [f"chunk_{i}" for i in range(len(self.vectors))]
        self.texts = [f"Text for chunk {i}" for i in range(len(self.vectors))]

    def test_hdbscan_clustering(self):
        labels, probs = cluster_vectors_hdbscan(self.vectors, min_cluster_size=2)
        self.assertEqual(len(labels), len(self.vectors))
        self.assertEqual(len(probs), len(self.vectors))
        # Verify that clusters were discovered
        unique_labels = set(labels)
        self.assertTrue(len(unique_labels) >= 2)

    def test_kmeans_clustering(self):
        labels, probs = cluster_vectors_kmeans(self.vectors, n_clusters=3, random_state=42)
        self.assertEqual(len(labels), len(self.vectors))
        self.assertEqual(len(probs), len(self.vectors))
        unique_labels = set(labels)
        self.assertEqual(len(unique_labels), 3)

    def test_evaluate_clustering_comparison(self):
        results = evaluate_clustering_comparison(
            chunk_ids=self.chunk_ids,
            vectors=self.vectors,
            texts=self.texts,
            k_clusters=3,
            runs=3,
        )

        self.assertIn("hdbscan", results)
        self.assertIn("kmeans", results)
        self.assertIn("recommendation", results)
        self.assertIn("freeze_config", results)

        # Check required metrics for HDBSCAN
        hdb = results["hdbscan"]
        for metric in ["coherence", "coverage", "stability", "overlap_rate", "broad_usefulness_entropy", "runtime_ms", "num_clusters"]:
            self.assertIn(metric, hdb)
            self.assertIsInstance(hdb[metric], (int, float))

        # Check required metrics for K-means
        km = results["kmeans"]
        for metric in ["coherence", "coverage", "stability", "overlap_rate", "broad_usefulness_entropy", "runtime_ms", "num_clusters"]:
            self.assertIn(metric, km)
            self.assertIsInstance(km[metric], (int, float))

        # Verify frozen configuration is recorded
        freeze = results["freeze_config"]
        self.assertIn("method", freeze)
        self.assertIn("embedding_version", freeze)


if __name__ == "__main__":
    unittest.main()
