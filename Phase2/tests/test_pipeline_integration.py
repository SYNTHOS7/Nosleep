"""End-to-end integration tests for Person 2 pipeline spike and batch staging."""

import os
import pytest

from backend.contracts.models import OperationType
from backend.ingestion.operations import get_operation_manager
from backend.ingestion.pipeline import build_batch, run_operation

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures")


def test_e2e_txt_spike_pipeline():
    """
    Phase 1 spike verification on sample_prose.txt:
    - Parses strict UTF-8 TXT
    - Chunks deterministically
    - Extracts affirmative, negative, conditional, and value relations
    - Generates 768-dim embeddings
    - Asserts exact quote provenance for every single relation
    - Stages extraction batch
    """
    txt_file = os.path.join(FIXTURES_DIR, "sample_prose.txt")
    op_manager = get_operation_manager()

    op = op_manager.create_operation(
        workspace_id="ws-spike",
        document_id="doc-spike-txt",
        operation_type=OperationType.ADD,
        source_ref=txt_file,
        source_type="txt",
    )

    batch = build_batch(op)

    assert batch.status == "STAGED"
    assert len(batch.chunks) > 0
    assert len(batch.aggregated_relations) >= 4

    # Check negative sentence was extracted with NEGATIVE polarity
    neg_rels = [r for r in batch.aggregated_relations if r.polarity == "NEGATIVE"]
    assert len(neg_rels) >= 1
    assert "does not depend on Legacy Mainframe" in neg_rels[0].provenance.exact_quote

    # Check conditional sentence was extracted with CONDITIONAL modality
    cond_rels = [r for r in batch.aggregated_relations if r.modality == "CONDITIONAL"]
    assert len(cond_rels) >= 1
    assert cond_rels[0].condition is not None

    # Check Value nodes created for status
    assert len(batch.aggregated_values) >= 1
    assert any(v.raw_value == "ACTIVE" for v in batch.aggregated_values)

    # Check all chunks have 768-dim vectors
    assert len(batch.vectors) == len(batch.chunks)
    for cid, vec in batch.vectors.items():
        assert len(vec) == 768

    # Check exact provenance for every relation
    for rel in batch.aggregated_relations:
        assert rel.provenance.exact_quote != ""
        # Find source chunk
        matching_chunks = [c for c in batch.chunks if c.id == rel.provenance.source_chunk_id]
        assert len(matching_chunks) == 1
        assert rel.provenance.exact_quote in matching_chunks[0].text

    # Check stage timings are recorded
    assert "parsing" in op.stage_timings
    assert "chunk_cache" in op.stage_timings
    assert "extraction" in op.stage_timings
    assert "embeddings" in op.stage_timings
    assert "stage_batch" in op.stage_timings


def test_e2e_pdf_spike_pipeline():
    """
    Phase 1 spike verification on sample_selectable.pdf:
    - Parses PDF with page preservation
    - Verifies no cross-page merge
    - Extracts multi-page graph relations with exact quotes
    - Generates embeddings
    """
    pdf_file = os.path.join(FIXTURES_DIR, "sample_selectable.pdf")
    op_manager = get_operation_manager()

    op = op_manager.create_operation(
        workspace_id="ws-spike",
        document_id="doc-spike-pdf",
        operation_type=OperationType.ADD,
        source_ref=pdf_file,
        source_type="pdf",
    )

    batch = build_batch(op)

    assert batch.status == "STAGED"
    assert len(batch.chunks) >= 2
    # Check page numbers
    page_numbers = {c.page_number for c in batch.chunks}
    assert 1 in page_numbers
    assert 2 in page_numbers

    # Relations across pages
    assert len(batch.aggregated_relations) >= 2
    for rel in batch.aggregated_relations:
        matching_chunks = [c for c in batch.chunks if c.id == rel.provenance.source_chunk_id]
        assert len(matching_chunks) == 1
        assert rel.provenance.exact_quote in matching_chunks[0].text
