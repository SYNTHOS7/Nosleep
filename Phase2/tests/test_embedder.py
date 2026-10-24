"""Tests for multilingual embedding adapter: dimension enforcement, NaN/zero rejection, and batching."""

import pytest

from backend.ingestion.embedder import (
    PINNED_DIMENSION,
    EmbeddingValidationError,
    _generate_multilingual_vectors,
    embed_texts,
)


def test_embed_texts_dimension_and_batch():
    """Verifies that embeddings produce exact pinned dimension (768) across batch inputs."""
    texts = [
        "Architecture overview of microservice platform.",
        "यह हिंदी में एक परीक्षण वाक्य है।",
        "Third document chunk for batch embedding.",
    ]

    vectors = embed_texts(texts, purpose="document")

    assert len(vectors) == 3
    for v in vectors:
        assert len(v) == PINNED_DIMENSION
        # Check non-zero and finite
        assert all(-1.0 <= val <= 1.0 for val in v)
        assert sum(abs(val) for val in v) > 0.0


def test_reject_wrong_dimension(monkeypatch):
    """Verifies that vector with dimension != 768 is strictly rejected."""
    # Mock generator returning wrong dimension
    monkeypatch.setattr(
        "backend.ingestion.embedder._generate_multilingual_vectors",
        lambda texts: [[0.1] * 512 for _ in texts],
    )
    with pytest.raises(EmbeddingValidationError) as exc_info:
        embed_texts(["Test sentence"], purpose="document")
    assert "invalid dimension 512" in str(exc_info.value)


def test_reject_nan_vectors(monkeypatch):
    """Verifies that vector containing NaN is strictly rejected."""
    nan_vector = [0.1] * PINNED_DIMENSION
    nan_vector[10] = float("nan")
    monkeypatch.setattr(
        "backend.ingestion.embedder._generate_multilingual_vectors",
        lambda texts: [nan_vector for _ in texts],
    )
    with pytest.raises(EmbeddingValidationError) as exc_info:
        embed_texts(["Test sentence"], purpose="document")
    assert "NaN or Infinite" in str(exc_info.value)


def test_reject_zero_vectors(monkeypatch):
    """Verifies that all-zero vector is strictly rejected."""
    zero_vector = [0.0] * PINNED_DIMENSION
    monkeypatch.setattr(
        "backend.ingestion.embedder._generate_multilingual_vectors",
        lambda texts: [zero_vector for _ in texts],
    )
    with pytest.raises(EmbeddingValidationError) as exc_info:
        embed_texts(["Test sentence"], purpose="document")
    assert "zero-vector, which is rejected" in str(exc_info.value)
