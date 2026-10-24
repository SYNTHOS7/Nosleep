"""Parser adapter supporting strict UTF-8 TXT and element-aware PDF parsing."""

import hashlib
import os
import uuid
from typing import List, Literal, Optional
import pypdf
import requests

from backend.contracts.models import Element, ParsedSource


class ParsingError(Exception):
    """Raised when parsing fails or input is invalid."""
    pass


class NoExtractableTextError(ParsingError):
    """Raised when PDF has no extractable text (e.g. empty or scanned without OCR)."""
    pass


def parse_source(source_ref: str, source_type: Literal["pdf", "txt"]) -> ParsedSource:
    """
    Parses a source file (PDF or TXT) into a normalized ParsedSource.
    Enforces strict UTF-8 decoding, CRLF normalization, SHA-256 hashing,
    and page/element ID preservation.
    """
    if not os.path.exists(source_ref):
        raise FileNotFoundError(f"Source file not found: {source_ref}")

    # Read original raw bytes and compute content hash
    with open(source_ref, "rb") as f:
        raw_bytes = f.read()

    byte_size = len(raw_bytes)
    content_hash = hashlib.sha256(raw_bytes).hexdigest()

    if source_type == "txt":
        return _parse_txt(source_ref, raw_bytes, content_hash, byte_size)
    elif source_type == "pdf":
        return _parse_pdf(source_ref, raw_bytes, content_hash, byte_size)
    else:
        raise ValueError(f"Unsupported source_type: {source_type}. Only 'pdf' and 'txt' are allowed.")


def _parse_txt(source_ref: str, raw_bytes: bytes, content_hash: str, byte_size: int) -> ParsedSource:
    """
    Strict UTF-8 text parser.
    Normalizes CRLF and CR to LF.
    Removes NUL bytes only.
    Fails on decode errors.
    """
    try:
        decoded = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ParsingError(f"Strict UTF-8 decode error in {source_ref}: {e}") from e

    # Normalize CRLF and CR to LF
    normalized = decoded.replace("\r\n", "\n").replace("\r", "\n")
    # Remove NUL characters only
    normalized = normalized.replace("\x00", "")

    if not normalized.strip():
        # Text file is empty
        elements = []
        page_count = 1
        return ParsedSource(
            source_ref=source_ref,
            source_type="txt",
            content_hash=content_hash,
            byte_size=byte_size,
            page_count=page_count,
            elements=elements,
            normalized_text=normalized,
            provider_job_id="txt-local",
        )

    # Break into logical paragraph elements preserving offsets
    elements: List[Element] = []
    lines = normalized.split("\n\n")
    curr_offset = 0

    for idx, block in enumerate(lines):
        if not block:
            curr_offset += 2  # accounted for '\n\n'
            continue
        start_char = normalized.find(block, curr_offset)
        end_char = start_char + len(block)
        curr_offset = end_char

        elements.append(
            Element(
                element_id=f"el-p1-{idx:04d}",
                page_number=1,
                element_type="NarrativeText",
                text=block,
                start_char=start_char,
                end_char=end_char,
            )
        )

    return ParsedSource(
        source_ref=source_ref,
        source_type="txt",
        content_hash=content_hash,
        byte_size=byte_size,
        page_count=1,
        elements=elements,
        normalized_text=normalized,
        provider_job_id="txt-local",
    )


def _parse_pdf(source_ref: str, raw_bytes: bytes, content_hash: str, byte_size: int) -> ParsedSource:
    """
    PDF parser utilizing Unstructured API if configured, falling back to deterministic local
    PyPDF adapter. Preserves 1-based page numbers and element structure.
    Raises NoExtractableTextError ('NO_EXTRACTABLE_TEXT') if no text is found.
    """
    unstructured_api_key = os.environ.get("UNSTRUCTURED_API_KEY")
    unstructured_url = os.environ.get("UNSTRUCTURED_API_URL")

    if unstructured_api_key and unstructured_url:
        try:
            return _parse_pdf_unstructured(source_ref, raw_bytes, content_hash, byte_size, unstructured_url, unstructured_api_key)
        except Exception:
            # Fallback to local deterministic parser on network or API failure
            pass

    return _parse_pdf_local(source_ref, raw_bytes, content_hash, byte_size)


def _parse_pdf_unstructured(
    source_ref: str,
    raw_bytes: bytes,
    content_hash: str,
    byte_size: int,
    api_url: str,
    api_key: str,
) -> ParsedSource:
    """Call Unstructured API workflow."""
    headers = {
        "unstructured-api-key": api_key,
        "Accept": "application/json",
    }
    files = {"files": (os.path.basename(source_ref), raw_bytes, "application/pdf")}
    data = {
        "strategy": "fast",
        "coordinates": "false",
    }
    resp = requests.post(api_url, headers=headers, files=files, data=data, timeout=30)
    if resp.status_code != 200:
        raise ParsingError(f"Unstructured API returned error {resp.status_code}: {resp.text}")

    payload = resp.json()
    provider_job_id = resp.headers.get("x-job-id", f"unstructured-{uuid.uuid4().hex[:8]}")

    elements: List[Element] = []
    full_text_parts = []
    current_char = 0
    max_page = 1

    for idx, item in enumerate(payload):
        text = item.get("text", "").strip()
        if not text:
            continue
        page_no = item.get("metadata", {}).get("page_number", 1)
        max_page = max(max_page, page_no)
        start_char = current_char
        end_char = start_char + len(text)
        current_char = end_char + 1

        full_text_parts.append(text)
        elements.append(
            Element(
                element_id=item.get("element_id", f"el-p{page_no}-{idx:04d}"),
                page_number=page_no,
                element_type=item.get("type", "NarrativeText"),
                text=text,
                start_char=start_char,
                end_char=end_char,
            )
        )

    normalized_text = "\n".join(full_text_parts)
    if not normalized_text.strip():
        raise NoExtractableTextError("NO_EXTRACTABLE_TEXT")

    return ParsedSource(
        source_ref=source_ref,
        source_type="pdf",
        content_hash=content_hash,
        byte_size=byte_size,
        page_count=max_page,
        elements=elements,
        normalized_text=normalized_text,
        provider_job_id=provider_job_id,
    )


def _parse_pdf_local(
    source_ref: str, raw_bytes: bytes, content_hash: str, byte_size: int
) -> ParsedSource:
    """Local deterministic PDF extractor using PyPDF adapter."""
    try:
        reader = pypdf.PdfReader(source_ref)
    except Exception as e:
        raise ParsingError(f"Failed to open PDF {source_ref}: {e}") from e

    page_count = len(reader.pages)
    if page_count == 0:
        raise NoExtractableTextError("NO_EXTRACTABLE_TEXT")

    elements: List[Element] = []
    full_text_parts = []
    curr_char = 0

    for page_idx, page in enumerate(reader.pages):
        page_no = page_idx + 1  # 1-based page number
        page_text = page.extract_text() or ""
        # Normalize line breaks
        norm_page_text = page_text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
        if not norm_page_text.strip():
            continue

        paragraphs = norm_page_text.split("\n\n")
        for el_idx, para in enumerate(paragraphs):
            para_clean = para.strip()
            if not para_clean:
                continue

            start_char = curr_char
            end_char = start_char + len(para_clean)
            curr_char = end_char + 1

            full_text_parts.append(para_clean)
            elements.append(
                Element(
                    element_id=f"el-p{page_no}-{el_idx:04d}",
                    page_number=page_no,
                    element_type="NarrativeText",
                    text=para_clean,
                    start_char=start_char,
                    end_char=end_char,
                )
            )

    normalized_text = "\n".join(full_text_parts)
    if not normalized_text.strip():
        raise NoExtractableTextError("NO_EXTRACTABLE_TEXT")

    return ParsedSource(
        source_ref=source_ref,
        source_type="pdf",
        content_hash=content_hash,
        byte_size=byte_size,
        page_count=page_count,
        elements=elements,
        normalized_text=normalized_text,
        provider_job_id="pypdf-local-adapter",
    )
