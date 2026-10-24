"""Tests for chunker: deterministic chunks, no cross-page merge, token limits, and oversize warnings."""

import pytest

from backend.contracts.models import Document, Element, ParsedSource
from backend.ingestion.chunker import (
    MAX_TOKENS,
    TARGET_TOKENS,
    chunk_source,
    count_tokens,
)


def test_no_cross_page_merge():
    """Strictly verifies that chunks never merge elements across different pages."""
    elements = [
        Element(element_id="el-1", page_number=1, element_type="Text", text="Page 1 sentence.", start_char=0, end_char=16),
        Element(element_id="el-2", page_number=1, element_type="Text", text="Page 1 extra.", start_char=18, end_char=30),
        Element(element_id="el-3", page_number=2, element_type="Text", text="Page 2 starting content.", start_char=32, end_char=56),
    ]
    parsed = ParsedSource(
        source_ref="test.pdf",
        source_type="pdf",
        content_hash="dummyhash",
        byte_size=100,
        page_count=2,
        elements=elements,
        normalized_text="Page 1 sentence.\n\nPage 1 extra.\n\nPage 2 starting content.",
    )
    doc = Document(id="doc-123", workspace_id="ws-1", source_name="test.pdf", source_type="pdf", content_hash="dummyhash")

    chunks = chunk_source(parsed, doc, revision=1)

    assert len(chunks) >= 2
    # Check that no single chunk has elements from multiple pages
    for c in chunks:
        # Every chunk must belong strictly to one page
        assert c.page_number in (1, 2)
        if "Page 2" in c.text:
            assert c.page_number == 2
            assert "Page 1" not in c.text


def test_deterministic_chunking():
    """Verifies that running chunker multiple times yields identical chunk IDs, boundaries, and tokens."""
    elements = [
        Element(element_id=f"el-{i}", page_number=1, element_type="Text", text=f"Paragraph {i} describing system components.", start_char=i*45, end_char=(i+1)*45)
        for i in range(15)
    ]
    parsed = ParsedSource(
        source_ref="test.txt",
        source_type="txt",
        content_hash="hashabc",
        byte_size=500,
        page_count=1,
        elements=elements,
        normalized_text="\n\n".join(e.text for e in elements),
    )
    doc = Document(id="doc-det", workspace_id="ws-1", source_name="test.txt", source_type="txt", content_hash="hashabc")

    run_1 = chunk_source(parsed, doc, revision=1)
    run_2 = chunk_source(parsed, doc, revision=1)

    assert len(run_1) == len(run_2)
    for c1, c2 in zip(run_1, run_2):
        assert c1.id == c2.id
        assert c1.text == c2.text
        assert c1.token_count == c2.token_count
        assert c1.start_char == c2.start_char
        assert c1.end_char == c2.end_char


def test_oversize_element_warning_and_splitting():
    """Verifies that elements exceeding MAX_TOKENS produce a warning and split deterministically."""
    oversize_text = "word " * 950  # ~950 tokens > MAX_TOKENS (800)
    oversize_el = Element(
        element_id="el-oversize",
        page_number=1,
        element_type="Text",
        text=oversize_text,
        start_char=0,
        end_char=len(oversize_text),
    )
    parsed = ParsedSource(
        source_ref="test_large.txt",
        source_type="txt",
        content_hash="largehash",
        byte_size=len(oversize_text),
        page_count=1,
        elements=[oversize_el],
        normalized_text=oversize_text,
    )
    doc = Document(id="doc-large", workspace_id="ws-1", source_name="test_large.txt", source_type="txt", content_hash="largehash")

    with pytest.warns(UserWarning, match="exceeds MAX_TOKENS"):
        chunks = chunk_source(parsed, doc, revision=1)

    assert len(chunks) >= 2
    for c in chunks:
        assert c.token_count <= MAX_TOKENS
