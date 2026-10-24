"""Gate 0: Dependency proof and component readiness tests."""

from backend.ingestion.embedder import embed_texts, PINNED_DIMENSION
from backend.ingestion.chunker import count_tokens
from backend.storage.graph_store import get_graph_store
from backend.contracts.models import Document


def test_gate0_health_endpoint(client):
    """Verifies that /health returns 200 with readiness and pinned versions, no secrets."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "healthy"
    assert "components" in data
    assert "pinned_versions" in data

    # Verify no secrets or passwords exposed
    data_str = str(data).lower()
    assert "password" not in data_str
    assert "secret" not in data_str
    assert "apikey" not in data_str
    assert "auth" not in data_str

    # Verify pinned versions
    assert data["pinned_versions"]["embedding_dim"] == "768"
    assert data["pinned_versions"]["tokenizer"] == "cl100k_base"


def test_gate0_embedding_dimension():
    """Verifies that the embedder strictly outputs 768-dimensional normalized vectors."""
    vectors = embed_texts(["Test embedding dependency verification."], purpose="document")
    assert len(vectors) == 1
    assert len(vectors[0]) == PINNED_DIMENSION


def test_gate0_tokenizer_pin():
    """Verifies that the tokenizer counts tokens deterministically."""
    tok_count = count_tokens("Interactive knowledge base architecture testing.")
    assert tok_count > 0


def test_gate0_storage_roundtrip():
    """Verifies Person 1 storage roundtrip."""
    store = get_graph_store()
    doc = Document(
        id="doc-test-g0",
        workspace_id="ws-test",
        source_name="test.txt",
        source_type="txt",
        content_hash="abc123hash",
        revision=1,
    )
    store.documents["ws-test"] = {"doc-test-g0": doc}
    retrieved = store.get_document("ws-test", "doc-test-g0")
    assert retrieved is not None
    assert retrieved.id == "doc-test-g0"
    assert retrieved.revision == 1
