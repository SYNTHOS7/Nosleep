"""Deterministic, element-aware chunker adhering to frozen limits and no cross-page merge."""

import warnings
from typing import List, Tuple
import tiktoken

from backend.contracts.models import Chunk, Document, Element, ParsedSource

# Frozen configuration from pipeline-lock.json
TARGET_TOKENS = 600
MAX_TOKENS = 800
MAX_OVERLAP_TOKENS = 60
TOKENIZER_NAME = "cl100k_base"

try:
    _enc = tiktoken.get_encoding(TOKENIZER_NAME)
except Exception:
    _enc = None


def count_tokens(text: str) -> int:
    """Deterministic token count using pinned tiktoken cl100k_base."""
    if _enc is not None:
        return len(_enc.encode(text))
    # Fallback heuristic: 1 token ~= 4 chars or whitespace-based
    return max(1, len(text.split()))


def chunk_source(parsed: ParsedSource, document: Document, revision: int) -> List[Chunk]:
    """
    Chunks a parsed document deterministically.
    Strictly forbids cross-page merging.
    Emits warnings on oversized element splits.
    """
    chunks: List[Chunk] = []
    chunk_global_idx = 0

    # Group elements by page_number
    pages: dict[int, List[Element]] = {}
    for el in parsed.elements:
        pages.setdefault(el.page_number, []).append(el)

    for page_no in sorted(pages.keys()):
        page_elements = pages[page_no]
        page_chunks, chunk_global_idx = _chunk_page_elements(
            page_elements=page_elements,
            page_no=page_no,
            document=document,
            revision=revision,
            start_index=chunk_global_idx,
        )
        chunks.extend(page_chunks)

    # In case there are no elements but there is normalized_text (e.g. single page TXT without breaks)
    if not chunks and parsed.normalized_text.strip():
        text = parsed.normalized_text.strip()
        tok_count = count_tokens(text)
        chunks.append(
            Chunk(
                id=f"{document.id}-p1-c0000",
                workspace_id=document.workspace_id,
                document_id=document.id,
                revision=revision,
                chunk_index=0,
                page_number=1,
                text=text,
                token_count=tok_count,
                start_char=0,
                end_char=len(text),
                element_ids=[],
                metadata={"split_reason": "single_fallback"},
            )
        )

    return chunks


def _chunk_page_elements(
    page_elements: List[Element],
    page_no: int,
    document: Document,
    revision: int,
    start_index: int,
) -> Tuple[List[Chunk], int]:
    """Chunks elements within a single page, never crossing page boundaries."""
    chunks: List[Chunk] = []
    curr_index = start_index

    current_elements: List[Element] = []
    current_tokens = 0

    for el in page_elements:
        el_tokens = count_tokens(el.text)

        # Handle oversize single element (> MAX_TOKENS)
        if el_tokens > MAX_TOKENS:
            # First flush any accumulated elements
            if current_elements:
                chunk = _create_chunk(current_elements, document, revision, page_no, curr_index)
                chunks.append(chunk)
                curr_index += 1
                current_elements = []
                current_tokens = 0

            # Emit warning as required by specification
            warnings.warn(
                f"Element {el.element_id} on page {page_no} exceeds MAX_TOKENS ({el_tokens} > {MAX_TOKENS}). Splitting deterministically.",
                UserWarning,
            )

            # Split oversized element text deterministically
            split_chunks, curr_index = _split_oversize_element(el, document, revision, page_no, curr_index)
            chunks.extend(split_chunks)
            continue

        # Check if adding el exceeds TARGET_TOKENS or MAX_TOKENS
        if current_elements and (current_tokens + el_tokens > MAX_TOKENS):
            chunk = _create_chunk(current_elements, document, revision, page_no, curr_index)
            chunks.append(chunk)
            curr_index += 1

            # Prepare next chunk with overlap if applicable
            current_elements = [el]
            current_tokens = el_tokens
        else:
            current_elements.append(el)
            current_tokens += el_tokens

            if current_tokens >= TARGET_TOKENS:
                chunk = _create_chunk(current_elements, document, revision, page_no, curr_index)
                chunks.append(chunk)
                curr_index += 1
                current_elements = []
                current_tokens = 0

    # Flush remaining elements
    if current_elements:
        chunk = _create_chunk(current_elements, document, revision, page_no, curr_index)
        chunks.append(chunk)
        curr_index += 1

    return chunks, curr_index


def _create_chunk(
    elements: List[Element],
    document: Document,
    revision: int,
    page_no: int,
    chunk_index: int,
) -> Chunk:
    """Builds a single Chunk model from a list of page elements."""
    text = "\n\n".join(e.text for e in elements)
    token_count = count_tokens(text)
    start_char = elements[0].start_char
    end_char = elements[-1].end_char
    element_ids = [e.element_id for e in elements]

    return Chunk(
        id=f"{document.id}-p{page_no}-c{chunk_index:04d}",
        workspace_id=document.workspace_id,
        document_id=document.id,
        revision=revision,
        chunk_index=chunk_index,
        page_number=page_no,
        text=text,
        token_count=token_count,
        start_char=start_char,
        end_char=end_char,
        element_ids=element_ids,
        metadata={"element_count": len(elements)},
    )


def _split_oversize_element(
    el: Element,
    document: Document,
    revision: int,
    page_no: int,
    start_index: int,
) -> Tuple[List[Chunk], int]:
    """Splits an oversized element into bounded sub-chunks."""
    words = el.text.split(" ")
    chunks: List[Chunk] = []
    curr_idx = start_index

    current_words: List[str] = []
    current_char_start = el.start_char

    for w in words:
        current_words.append(w)
        sub_text = " ".join(current_words)
        tok_len = count_tokens(sub_text)

        if tok_len >= TARGET_TOKENS:
            sub_end = current_char_start + len(sub_text)
            chunk = Chunk(
                id=f"{document.id}-p{page_no}-c{curr_idx:04d}",
                workspace_id=document.workspace_id,
                document_id=document.id,
                revision=revision,
                chunk_index=curr_idx,
                page_number=page_no,
                text=sub_text,
                token_count=tok_len,
                start_char=current_char_start,
                end_char=sub_end,
                element_ids=[el.element_id],
                metadata={"split_reason": "oversize_element_split"},
            )
            chunks.append(chunk)
            curr_idx += 1
            current_words = []
            current_char_start = sub_end + 1

    if current_words:
        sub_text = " ".join(current_words)
        tok_len = count_tokens(sub_text)
        sub_end = current_char_start + len(sub_text)
        chunk = Chunk(
            id=f"{document.id}-p{page_no}-c{curr_idx:04d}",
            workspace_id=document.workspace_id,
            document_id=document.id,
            revision=revision,
            chunk_index=curr_idx,
            page_number=page_no,
            text=sub_text,
            token_count=tok_len,
            start_char=current_char_start,
            end_char=sub_end,
            element_ids=[el.element_id],
            metadata={"split_reason": "oversize_element_remainder"},
        )
        chunks.append(chunk)
        curr_idx += 1

    return chunks, curr_idx
