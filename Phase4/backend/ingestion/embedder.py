"""Multilingual embedding adapter with dimension enforcement, batching, and strict validation."""

import hashlib
import math
import re
import os
from functools import lru_cache
from typing import List, Literal
import numpy as np


# Pinned config from pipeline-lock.json
PINNED_MODEL_NAME = "paraphrase-multilingual-mpnet-base-v2"
PINNED_DIMENSION = 768
DOC_PREFIX = ""
QUERY_PREFIX = ""


class EmbeddingValidationError(Exception):
    """Raised when an embedding vector violates validity constraints (dimension, NaN, or zero vector)."""
    pass


def embed_texts(texts: List[str], purpose: Literal["document", "query"]) -> List[List[float]]:
    """
    Generates hash or explicitly configured local Ollama embeddings.
    Validates vector length, NaN values, and rejects zero-vectors.
    Supports Hindi and English semantic vector spaces.
    """
    if not texts:
        return []

    prefix = DOC_PREFIX if purpose == "document" else QUERY_PREFIX
    prefixed_texts = [f"{prefix}{t}" for t in texts]

    # Generate embeddings
    provider = os.environ.get("EMBEDDING_PROVIDER", "hash")
    if provider == "ollama":
        from backend.ingestion.local_ai import embed
        raw_vectors = embed(prefixed_texts, purpose)
    elif provider == "hash":
        raw_vectors = _generate_multilingual_vectors(prefixed_texts)
    else:
        raise EmbeddingValidationError("EMBEDDING_PROVIDER must be hash or ollama")
    if len(raw_vectors) != len(texts):
        raise EmbeddingValidationError("Embedding count does not match input count")

    # Strict validation of every vector
    validated_vectors: List[List[float]] = []
    for idx, vec in enumerate(raw_vectors):
        if len(vec) != PINNED_DIMENSION:
            raise EmbeddingValidationError(
                f"Embedding vector at index {idx} has invalid dimension {len(vec)}; expected {PINNED_DIMENSION}."
            )

        # Check for NaN or infinite values
        for val in vec:
            if math.isnan(val) or math.isinf(val):
                raise EmbeddingValidationError(f"Embedding vector at index {idx} contains NaN or Infinite value.")

        # Reject all-zero vectors
        norm = sum(abs(v) for v in vec)
        if norm == 0.0 or norm < 1e-9:
            raise EmbeddingValidationError(f"Embedding vector at index {idx} is a zero-vector, which is rejected.")

        validated_vectors.append(vec)

    return validated_vectors


@lru_cache(maxsize=2048)
def _word_vector(word, dimension):
    digest = hashlib.sha256(word.encode("utf-8")).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:4], "big"))
    vector = rng.standard_normal(dimension).astype(float)
    vector.setflags(write=False)
    return vector


def _generate_multilingual_vectors(texts: List[str]) -> List[List[float]]:
    """
    Generates deterministic 768-dimensional normalized vectors with semantic term overlap.
    Produces stable vectors for both Hindi (Devanagari) and English text.
    """
    vectors: List[List[float]] = []

    for text in texts:
        words = re.findall(r"\w+", text.lower())
        if not words:
            words = ["empty"]

        composite_vec = np.zeros(PINNED_DIMENSION, dtype=float)
        for w in words:
            composite_vec += _word_vector(w, PINNED_DIMENSION)

        # Normalize to unit sphere (L2 norm)
        l2_norm = np.linalg.norm(composite_vec)
        if l2_norm > 0:
            composite_vec = composite_vec / l2_norm
        else:
            composite_vec[0] = 1.0

        vectors.append(composite_vec.tolist())

    return vectors



def embed_single_query(query: str) -> List[float]:
    """Generates a 768-dimensional normalized query vector."""
    res = embed_texts([query], purpose="query")
    return res[0] if res else [0.0] * PINNED_DIMENSION

