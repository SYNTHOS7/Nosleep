"""Task 1 storage repositories and lifecycle coordinator."""

try:
    from .chroma import ChromaVectorRepository
except ImportError:
    ChromaVectorRepository = None  # type: ignore

from .interfaces import EpochConflict, GraphRepository, OperationConflict, StorageError, VectorRepository, VectorStageError, WorkspaceViolation
from .lifecycle import StorageLifecycle
from .memory import InMemoryGraphRepository, InMemoryVectorRepository

try:
    from .neo4j import Neo4jGraphRepository
except ImportError:
    Neo4jGraphRepository = None  # type: ignore

__all__ = [
    "ChromaVectorRepository",
    "EpochConflict", "GraphRepository", "InMemoryGraphRepository", "InMemoryVectorRepository",
    "Neo4jGraphRepository", "OperationConflict", "StorageError", "StorageLifecycle",
    "VectorRepository", "VectorStageError", "WorkspaceViolation",
]
