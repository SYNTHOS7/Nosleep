"""Tests for extractor: schema enforcement, exact evidence validation, polarity, modality, and caching."""

import pytest

from backend.contracts.models import Chunk
from backend.ingestion.extractor import (
    ALLOWED_ENTITY_LABELS,
    ALLOWED_RELATION_PREDICATES,
    _cache,
    extract_chunk,
)


@pytest.fixture(autouse=True)
def clear_extraction_cache():
    _cache.clear()
    yield
    _cache.clear()


def test_schema_and_exact_evidence_provenance():
    """Verifies that extracted relations link to exact substring quotes in the source chunk."""
    text = (
        "Enterprise System Alpha is a part of Global Core.\n"
        "Service Alpha uses Service Beta."
    )
    chunk = Chunk(
        id="chunk-test-01",
        workspace_id="ws-1",
        document_id="doc-1",
        revision=1,
        chunk_index=0,
        page_number=1,
        text=text,
        token_count=20,
        start_char=0,
        end_char=len(text),
    )

    cgraph = extract_chunk(chunk, use_cache=False)

    assert not cgraph.is_empty
    assert len(cgraph.relations) >= 2

    for rel in cgraph.relations:
        assert rel.predicate in ALLOWED_RELATION_PREDICATES
        assert rel.source_entity_label in ALLOWED_ENTITY_LABELS
        # EXACT EVIDENCE VERIFICATION
        assert rel.provenance.exact_quote in chunk.text
        # Verify char offsets match the exact quote in chunk.text
        start = rel.provenance.char_start
        end = rel.provenance.char_end
        assert chunk.text[start:end] == rel.provenance.exact_quote


def test_negation_polarity_handling():
    """Verifies that negative sentences are extracted with NEGATIVE polarity."""
    text = "Database Alpha does not depend on Legacy Mainframe."
    chunk = Chunk(
        id="chunk-neg-01",
        workspace_id="ws-1",
        document_id="doc-1",
        revision=1,
        chunk_index=0,
        page_number=1,
        text=text,
        token_count=10,
        start_char=0,
        end_char=len(text),
    )

    cgraph = extract_chunk(chunk, use_cache=False)

    assert len(cgraph.relations) >= 1
    rel = cgraph.relations[0]
    assert rel.predicate == "DEPENDS_ON"
    assert rel.polarity == "NEGATIVE"
    assert rel.provenance.exact_quote in chunk.text


def test_conditional_modality_handling():
    """Verifies that conditional sentences are extracted with CONDITIONAL modality and condition string."""
    text = "Service Alpha uses Cache Beta only if high availability mode is enabled."
    chunk = Chunk(
        id="chunk-cond-01",
        workspace_id="ws-1",
        document_id="doc-1",
        revision=1,
        chunk_index=0,
        page_number=1,
        text=text,
        token_count=12,
        start_char=0,
        end_char=len(text),
    )

    cgraph = extract_chunk(chunk, use_cache=False)

    assert len(cgraph.relations) >= 1
    rel = cgraph.relations[0]
    assert rel.predicate == "USES"
    assert rel.modality == "CONDITIONAL"
    assert rel.condition is not None
    assert "if high availability mode is enabled" in rel.condition
    assert rel.provenance.exact_quote in chunk.text


def test_value_node_extraction():
    """Verifies that values (statuses, versions) produce Value nodes rather than overwriting entity attributes."""
    text = "Release Pipeline has status ACTIVE."
    chunk = Chunk(
        id="chunk-val-01",
        workspace_id="ws-1",
        document_id="doc-1",
        revision=1,
        chunk_index=0,
        page_number=1,
        text=text,
        token_count=8,
        start_char=0,
        end_char=len(text),
    )

    cgraph = extract_chunk(chunk, use_cache=False)

    assert len(cgraph.values) >= 1
    val = cgraph.values[0]
    assert val.val_type == "status"
    assert val.raw_value == "ACTIVE"

    # Must be linked via HAS_VALUE relation
    has_val_rels = [r for r in cgraph.relations if r.predicate == "HAS_VALUE"]
    assert len(has_val_rels) == 1
    assert has_val_rels[0].target_value_id == val.id


def test_caching_behavior():
    """Verifies that caching prevents re-extraction and invalidates when chunk text changes."""
    text_1 = "Service Alpha uses Service Beta."
    chunk_1 = Chunk(
        id="chunk-cache-01",
        workspace_id="ws-1",
        document_id="doc-1",
        revision=1,
        chunk_index=0,
        page_number=1,
        text=text_1,
        token_count=6,
        start_char=0,
        end_char=len(text_1),
    )

    # First call - cache miss
    g1 = extract_chunk(chunk_1, use_cache=True)
    # Second call - cache hit
    g2 = extract_chunk(chunk_1, use_cache=True)
    assert g1.chunk_id == g2.chunk_id
    assert len(g1.relations) == len(g2.relations)

    # Modified chunk text - cache miss
    chunk_modified = Chunk(
        id="chunk-cache-01",
        workspace_id="ws-1",
        document_id="doc-1",
        revision=2,
        chunk_index=0,
        page_number=1,
        text="Service Alpha does not depend on Legacy Mainframe.",
        token_count=8,
        start_char=0,
        end_char=len("Service Alpha does not depend on Legacy Mainframe."),
    )
    g3 = extract_chunk(chunk_modified, use_cache=True)
    assert g3.relations[0].predicate == "DEPENDS_ON"
    assert g3.relations[0].polarity == "NEGATIVE"
