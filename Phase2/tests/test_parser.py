"""Tests for parser adapter: UTF-8 normalization, CRLF, NUL removal, decode failure, and PDF page handling."""

import os
import pytest

from backend.ingestion.parser import (
    NoExtractableTextError,
    ParsingError,
    parse_source,
)

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures")


def test_txt_crlf_and_nul_normalization(tmp_path):
    """Verifies that CRLF and CR are normalized to LF, and NUL is removed only."""
    dirty_content = "Line 1\r\nLine 2\rLine 3\x00 with nul."
    test_file = tmp_path / "crlf_test.txt"
    test_file.write_bytes(dirty_content.encode("utf-8"))

    parsed = parse_source(str(test_file), source_type="txt")

    assert "\r" not in parsed.normalized_text
    assert "\x00" not in parsed.normalized_text
    assert "Line 1\nLine 2\nLine 3 with nul." in parsed.normalized_text
    assert parsed.page_count == 1
    assert len(parsed.content_hash) == 64


def test_txt_strict_utf8_decode_error():
    """Verifies that invalid UTF-8 bytes immediately fail parsing with strict error."""
    invalid_file = os.path.join(FIXTURES_DIR, "invalid_utf8.txt")
    with pytest.raises(ParsingError) as exc_info:
        parse_source(invalid_file, source_type="txt")
    assert "Strict UTF-8 decode error" in str(exc_info.value)


def test_unicode_hindi_support(tmp_path):
    """Verifies that multilingual Hindi/Devanagari text parses cleanly with exact offsets."""
    hindi_content = "यह एक परीक्षण दस्तावेज है। सेवा अल्फा सेवा बीटा पर निर्भर करती है।"
    test_file = tmp_path / "hindi_test.txt"
    test_file.write_text(hindi_content, encoding="utf-8")

    parsed = parse_source(str(test_file), source_type="txt")
    assert parsed.normalized_text == hindi_content
    assert len(parsed.elements) > 0


def test_pdf_selectable_text_and_pages():
    """Verifies 1-based page numbers, element order, and text preservation for PDF."""
    pdf_file = os.path.join(FIXTURES_DIR, "sample_selectable.pdf")
    parsed = parse_source(pdf_file, source_type="pdf")

    assert parsed.page_count == 2
    assert len(parsed.elements) >= 2
    # Check 1-based pages
    page_numbers = {e.page_number for e in parsed.elements}
    assert 1 in page_numbers
    assert 2 in page_numbers
    assert 0 not in page_numbers
    assert "Service Alpha" in parsed.normalized_text


def test_empty_or_scanned_pdf_returns_no_extractable_text():
    """Verifies that empty/scanned PDF raises NO_EXTRACTABLE_TEXT and never succeeds."""
    empty_pdf = os.path.join(FIXTURES_DIR, "empty_scanned.pdf")
    with pytest.raises(NoExtractableTextError) as exc_info:
        parse_source(empty_pdf, source_type="pdf")
    assert "NO_EXTRACTABLE_TEXT" in str(exc_info.value)
