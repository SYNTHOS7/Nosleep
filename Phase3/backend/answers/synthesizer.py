"""
Answer synthesis and validation module.
Enforces grounded answer synthesis, server-side citation validation,
one repair attempt, and extractive fallback if validation fails.
"""

from __future__ import annotations
from typing import List, Optional, Set

from backend.contracts.models import AnswerStatement, EvidencePackage, QueryRequest
from backend.adapters.llm import LLMAdapterProtocol, GroundedLLMAdapter


def validate_citations(
    statements: List[AnswerStatement],
    valid_chunk_ids: Set[str],
    valid_path_ids: Set[str],
) -> bool:
    """
    Validates that every citation_chunk_id and citation_path_id in statements
    exists in the EvidencePackage.
    """
    for stmt in statements:
        for cid in stmt.citation_chunk_ids:
            if cid not in valid_chunk_ids:
                return False
        for pid in stmt.citation_path_ids:
            if pid not in valid_path_ids:
                return False
    return True


def synthesize(
    request: QueryRequest,
    package: EvidencePackage,
    llm_adapter: Optional[LLMAdapterProtocol] = None,
    language: str = "en",
) -> List[AnswerStatement]:
    """
    Synthesizes grounded answer statements from the EvidencePackage.
    Validates citations, performs up to 1 repair attempt, and falls back to
    insufficient-evidence if validation fails.
    """
    llm_adapter = llm_adapter or GroundedLLMAdapter()
    valid_chunk_ids = {c.id for c in package.chunks}
    valid_path_ids = {p.path_id for p in package.paths}

    # If package has no active chunks and no active relations, return insufficient-evidence immediately
    if not valid_chunk_ids and not package.relations:
        if language == "hi":
            text = "सक्रिय कार्यक्षेत्र में अनुरोधित प्रश्न के लिए कोई सहायक साक्ष्य नहीं मिला।"
        else:
            text = "No supporting evidence found in the active workspace for the requested query."
        return [
            AnswerStatement(
                statement_text=text,
                citation_chunk_ids=[],
                citation_path_ids=[],
                is_inference=False,
                confidence=1.0,
            )
        ]

    # Generate initial statements
    statements = llm_adapter.synthesize_statements(
        question=request.question,
        package=package,
        language=language,
    )

    # First validation pass
    if validate_citations(statements, valid_chunk_ids, valid_path_ids):
        return statements

    # 1 Repair attempt if invalid citations are present
    repaired_statements = llm_adapter.repair_citations(statements, valid_chunk_ids, valid_path_ids)

    # Validate repair
    if repaired_statements and validate_citations(repaired_statements, valid_chunk_ids, valid_path_ids):
        return repaired_statements

    # Extractive insufficient-evidence fallback if repair fails
    if language == "hi":
        fallback_text = "अपर्याप्त साक्ष्य: निकाले गए तथ्यों को कार्यक्षेत्र के सहायक साक्ष्य से सत्यापित नहीं किया जा सका।"
    else:
        fallback_text = "Insufficient evidence: Extracted facts could not be verified against supporting source paths."

    return [
        AnswerStatement(
            statement_text=fallback_text,
            citation_chunk_ids=[],
            citation_path_ids=[],
            is_inference=False,
            confidence=0.0,
        )
    ]
