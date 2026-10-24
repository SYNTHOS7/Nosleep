"""Ingestion package interface."""

from backend.ingestion.chunker import chunk_source
from backend.ingestion.embedder import embed_texts
from backend.ingestion.extractor import extract_chunk
from backend.ingestion.operations import get_operation_manager
from backend.ingestion.parser import parse_source
from backend.ingestion.pipeline import build_batch, run_operation

__all__ = [
    "parse_source",
    "chunk_source",
    "extract_chunk",
    "embed_texts",
    "build_batch",
    "run_operation",
    "get_operation_manager",
]
