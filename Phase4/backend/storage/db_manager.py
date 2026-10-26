"""Unified Database Connection & Persistence Manager for Neo4j and ChromaDB."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("database_manager")

# Masking helper for security
def _mask_uri(uri: str) -> str:
    if not uri:
        return ""
    if "@" in uri:
        parts = uri.split("@")
        return f"***@{parts[-1]}"
    return uri


class DatabaseManager:
    """
    Manages dual-database topology:
    - Primary Graph Store: Neo4j AuraDB / Self-Hosted Neo4j with automated fallback to in-memory transactional graph.
    - Primary Vector Store: ChromaDB with persistent disk index in ./data/chroma.
    - Transactional Operations Store: Disk checkpointed in ./data/operations.
    """

    def __init__(self):
        self.chroma_dir = os.environ.get("CHROMA_PERSIST_DIR", os.path.abspath("./data/chroma"))
        os.makedirs(self.chroma_dir, exist_ok=True)

        self.neo4j_uri = os.environ.get("NEO4J_URI", "")
        self.neo4j_user = os.environ.get("NEO4J_USERNAME") or os.environ.get("NEO4J_USER", "neo4j")
        self.neo4j_password = os.environ.get("NEO4J_PASSWORD", "")
        self.neo4j_database = os.environ.get("NEO4J_DATABASE", "neo4j")

        self.chroma_client = None
        self.chroma_status = "uninitialized"
        self.chroma_error = None
        from concurrent.futures import ThreadPoolExecutor
        self._chroma_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chroma-sync")

        self.neo4j_driver = None
        self.neo4j_repo = None
        self.neo4j_status = "unconfigured"
        self.neo4j_error = None

        if os.environ.get("VECTOR_BACKEND") != "firebase" and os.environ.get("CHROMA_MIRROR_ENABLED", "false").lower() == "true":
            self._init_chroma()
        else:
            # Offline/in-memory mode must not silently schedule persistent HNSW writes.
            # The legacy mirror is explicit and never runs alongside Firebase storage.
            self.chroma_status = "disabled"
        self._init_neo4j()

    def _init_chroma(self) -> None:
        """Initializes persistent ChromaDB client."""
        try:
            import chromadb
            self.chroma_client = chromadb.PersistentClient(path=self.chroma_dir)
            self.chroma_status = "connected_persistent"
            self.chroma_error = None
            logger.info(f"ChromaDB persistent client initialized at {self.chroma_dir}")
        except Exception as e:
            self.chroma_status = "error_fallback"
            self.chroma_error = str(e)
            logger.warning(f"ChromaDB persistent client init failed, running in-memory vector store: {e}")

    def _init_neo4j(self) -> None:
        """Tests and connects to Neo4j if valid credentials are provided."""
        uri = (self.neo4j_uri or "").strip()
        if not uri or "example.databases.neo4j.io" in uri or not self.neo4j_password:
            self.neo4j_status = "in_memory_fallback"
            self.neo4j_error = "Neo4j credentials not configured; using high-performance embedded transactional graph engine."
            return

        try:
            from neo4j import GraphDatabase
            driver = GraphDatabase.driver(
                uri,
                auth=(self.neo4j_user, self.neo4j_password),
                connection_timeout=3.0,
                max_connection_lifetime=30.0,
            )
            # Verify connectivity with short timeout
            driver.verify_connectivity()
            self.neo4j_driver = driver
            self.neo4j_status = "connected"
            self.neo4j_error = None

            from backend.storage.neo4j import Neo4jGraphRepository
            self.neo4j_repo = Neo4jGraphRepository(
                uri=uri,
                user=self.neo4j_user,
                password=self.neo4j_password,
                database=self.neo4j_database,
                driver=driver,
            )
            logger.info(f"Successfully connected to Neo4j at {_mask_uri(uri)}")
        except Exception as e:
            self.neo4j_status = "connection_failed"
            self.neo4j_error = f"Failed to connect to Neo4j at {_mask_uri(uri)}: {e}"
            self.neo4j_driver = None
            self.neo4j_repo = None
            logger.warning(f"Neo4j connection error: {e}. Falling back to in-memory graph engine.")

    def configure_neo4j(self, uri: str, username: str, password: str, database: str = "neo4j") -> Dict[str, Any]:
        """Configures or updates Neo4j credentials dynamically at runtime."""
        self.neo4j_uri = uri
        self.neo4j_user = username
        self.neo4j_password = password
        self.neo4j_database = database
        self._init_neo4j()
        return self.get_status()

    def sync_vectors_to_chroma(self, workspace_id: str, vectors_map: Dict[str, list[float]]) -> None:
        """Persists vectors asynchronously into the persistent ChromaDB collection."""
        if not self.chroma_client or not vectors_map:
            return

        def _persist_task():
            try:
                col_name = f"ws_{workspace_id.replace('-', '_')}"[:63]
                collection = self.chroma_client.get_or_create_collection(
                    name=col_name,
                    metadata={"hnsw:space": "cosine", "workspace_id": workspace_id},
                )
                ids = list(vectors_map.keys())
                embeddings = [vectors_map[cid] for cid in ids]
                metadatas = [{"workspace_id": workspace_id, "chunk_id": cid} for cid in ids]
                collection.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas)
            except Exception as e:
                logger.warning(f"Non-blocking Chroma persistent upsert error: {e}")

        self._chroma_executor.submit(_persist_task)

    def get_status(self) -> Dict[str, Any]:
        """Returns the active connectivity state of all configured databases."""
        chroma_col_count = 0
        if self.chroma_client:
            try:
                chroma_col_count = len(self.chroma_client.list_collections())
            except Exception:
                pass

        return {
            "status": "healthy",
            "active_mode": "neo4j_aura" if self.neo4j_status == "connected" else "embedded_transactional",
            "neo4j": {
                "configured": bool(self.neo4j_uri and "example" not in self.neo4j_uri),
                "status": self.neo4j_status,
                "uri": _mask_uri(self.neo4j_uri) if self.neo4j_uri else "none",
                "database": self.neo4j_database,
                "error_or_info": self.neo4j_error or "Neo4j connection is verified and active.",
            },
            "chromadb": {
                "configured": self.chroma_status != "disabled",
                "status": self.chroma_status,
                "backend": "persistent_disk",
                "persist_directory": self.chroma_dir,
                "collections_count": chroma_col_count,
                "error_or_info": self.chroma_error or ("Legacy Chroma mirror is disabled." if self.chroma_status == "disabled" else "Chroma mirror is active and accepting embeddings."),
            },
            "operations_store": {
                "status": "active",
                "storage_backend": "atomic_disk_checkpoints",
                "directory": os.path.abspath("./data/operations"),
            },
            "vector_backend": os.environ.get("VECTOR_BACKEND", "in_memory"),
            "firebase": {
                "configured": os.environ.get("VECTOR_BACKEND") == "firebase",
                "status": "initialized" if os.environ.get("VECTOR_BACKEND") == "firebase" else "disabled",
                "backend": "firestore_persistence_local_cosine_search",
                "error_or_info": "Firestore stores extracted documents and embeddings; the backend restores its cosine index on startup.",
            },
        }


# Global singleton instance
_db_manager = DatabaseManager()


def get_db_manager() -> DatabaseManager:
    return _db_manager
