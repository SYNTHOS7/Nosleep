"""Test fixtures and test client configuration."""

import pytest
from fastapi.testclient import TestClient
from backend.app import app
from backend.storage.graph_store import get_graph_store
from backend.storage.vector_store import get_vector_store


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_stores():
    """Ensures clean stores before each test execution."""
    g_store = get_graph_store()
    v_store = get_vector_store()
    from backend.ingestion.extractor import _cache
    _cache.clear()
    g_store.clear()
    v_store.clear()
    yield
    _cache.clear()
    g_store.clear()
    v_store.clear()

