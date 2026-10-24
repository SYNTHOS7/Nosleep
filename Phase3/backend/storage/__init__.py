"""
Storage package initialization.
"""

from backend.storage.interface import (
    CorpusSnapshot,
    StorageRepositoryProtocol,
    InMemoryStorageRepository,
    _cosine_similarity,
)

__all__ = [
    "CorpusSnapshot",
    "StorageRepositoryProtocol",
    "InMemoryStorageRepository",
    "_cosine_similarity",
]
