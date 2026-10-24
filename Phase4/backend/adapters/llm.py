"""
LLM adapter protocol and grounded synthesis implementations.
Provides grounded topic labeling and structured answer statement generation.
"""

from __future__ import annotations
import re
from typing import List, Protocol
from backend.contracts.models import AnswerStatement, Chunk, EvidencePackage, EvidencePath


class LLMAdapterProtocol(Protocol):
    def generate_topic_label(self, representative_chunks: List[Chunk]) -> tuple[str, str]: ...
    def synthesize_statements(
        self,
        question: str,
        package: EvidencePackage,
        language: str,
    ) -> List[AnswerStatement]: ...
    def repair_citations(
        self,
        statements: List[AnswerStatement],
        valid_chunk_ids: set[str],
        valid_path_ids: set[str],
    ) -> List[AnswerStatement]: ...


class GroundedLLMAdapter:
    """
    Deterministic grounded LLM adapter.
    Ensures zero hallucination, strict citation adherence, and structured outputs.
    """

    def generate_topic_label(self, representative_chunks: List[Chunk]) -> tuple[str, str]:
        if not representative_chunks:
            return "General Topic", "General overview of document collection."

        # Extract representative terms across chunks
        combined_text = " ".join(c.text for c in representative_chunks)
        words = re.findall(r"[A-Z][a-zA-Z0-9]+|[a-z]{4,}", combined_text)
        stopwords = {
            "this", "that", "these", "those", "from", "with", "have", "been", "were",
            "which", "there", "their", "about", "would", "could", "should", "other",
            "into", "more", "some", "such", "only", "also", "under", "after", "before",
        }
        freq: dict[str, int] = {}
        for w in words:
            lw = w.lower()
            if lw not in stopwords:
                freq[w] = freq.get(w, 0) + 1

        top_words = sorted(freq.keys(), key=lambda k: freq[k], reverse=True)[:3]
        if top_words:
            label = " & ".join(top_words).title()
        else:
            label = "Document Theme"

        # Build grounded description strictly from representative chunks
        snippets = [c.text.strip().split(".")[0] for c in representative_chunks[:2] if c.text.strip()]
        desc = f"Topic covering {label}. Representative evidence notes: " + "; ".join(snippets) + "."
        return label, desc

    def synthesize_statements(
        self,
        question: str,
        package: EvidencePackage,
        language: str = "en",
    ) -> List[AnswerStatement]:
        statements: List[AnswerStatement] = []

        # If package is empty or has no active evidence
        if not package.chunks and not package.relations:
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

        # Check for contradictions first
        rel_ids_in_package = {r.id for r in package.relations}
        relevant_conflicts = [
            c for c in package.conflicts
            if c.left_relation_id in rel_ids_in_package or c.right_relation_id in rel_ids_in_package
        ]

        if relevant_conflicts:
            for conf in relevant_conflicts:
                left_rel = next((r for r in package.relations if r.id == conf.left_relation_id), None)
                right_rel = next((r for r in package.relations if r.id == conf.right_relation_id), None)
                left_chunk_id = left_rel.evidence.chunk_id if left_rel else (conf.evidence_chunk_ids[0] if conf.evidence_chunk_ids else "")
                right_chunk_id = right_rel.evidence.chunk_id if right_rel else (conf.evidence_chunk_ids[1] if len(conf.evidence_chunk_ids) > 1 else "")

                left_chunk = next((c for c in package.chunks if c.id == left_chunk_id), None)
                right_chunk = next((c for c in package.chunks if c.id == right_chunk_id), None)

                left_quote = left_rel.evidence.quote if left_rel else (left_chunk.text[:60] if left_chunk else "statement A")
                right_quote = right_rel.evidence.quote if right_rel else (right_chunk.text[:60] if right_chunk else "statement B")

                if language == "hi":
                    stmt_text = (
                        f"दस्तावेजों में परस्पर विरोधी दावे पाए गए: एक स्रोत (Chunk {left_chunk_id}) "
                        f"कहता है '{left_quote}', जबकि दूसरा स्रोत (Chunk {right_chunk_id}) "
                        f"कहता है '{right_quote}'।"
                    )
                else:
                    stmt_text = (
                        f"Conflicting claims detected between sources: One source (Chunk {left_chunk_id}) "
                        f"states '{left_quote}', whereas another source (Chunk {right_chunk_id}) "
                        f"states '{right_quote}'."
                    )

                c_chunks = [cid for cid in [left_chunk_id, right_chunk_id] if cid]
                statements.append(
                    AnswerStatement(
                        statement_text=stmt_text,
                        citation_chunk_ids=c_chunks,
                        citation_path_ids=[],
                        is_inference=False,
                        confidence=1.0,
                        contradiction_ref_ids=[conf.id],
                    )
                )

        # Synthesize from paths and relations
        if package.paths:
            for path in package.paths:
                chunk_ids = [e.source_chunk_id for e in path.edges if e.source_chunk_id]
                edge_desc = []
                for edge in path.edges:
                    s_ent = next((e.name for e in package.entities if e.id == edge.source_id), edge.source_id)
                    t_ent = next((e.name for e in package.entities if e.id == edge.target_id), edge.target_id)
                    edge_desc.append(f"{s_ent} {edge.predicate} {t_ent}")

                path_summary = " -> ".join(edge_desc)
                if language == "hi":
                    stmt_text = f"दस्तावेजी साक्ष्य के अनुसार: {path_summary}।"
                else:
                    stmt_text = f"According to verified documentation: {path_summary}."

                statements.append(
                    AnswerStatement(
                        statement_text=stmt_text,
                        citation_chunk_ids=list(set(chunk_ids)),
                        citation_path_ids=[path.path_id],
                        is_inference=False,
                        confidence=1.0,
                    )
                )

        # Direct relations if not covered in paths
        if not statements and package.relations:
            for rel in package.relations[:3]:
                s_ent = next((e.name for e in package.entities if e.id == rel.subject_id), rel.subject_id)
                o_val = rel.predicate_original or rel.predicate
                target = ""
                if rel.object_entity_id:
                    target = next((e.name for e in package.entities if e.id == rel.object_entity_id), rel.object_entity_id)
                elif rel.object_value_id:
                    val_node = next((v for v in package.values if v.id == rel.object_value_id), None)
                    target = val_node.lexical_value if val_node else rel.object_value_id

                if language == "hi":
                    stmt_text = f"साक्ष्य के अनुसार: {s_ent} का {o_val} {target} है (ध्रुवता: {rel.polarity})।"
                else:
                    stmt_text = f"Evidence states that {s_ent} {o_val} {target} (polarity: {rel.polarity})."

                statements.append(
                    AnswerStatement(
                        statement_text=stmt_text,
                        citation_chunk_ids=[rel.evidence.chunk_id],
                        citation_path_ids=[],
                        is_inference=False,
                        confidence=1.0,
                    )
                )

        # Thematic synthesis if topics are present
        if not statements and package.topics:
            topic_names = [t.label for t in package.topics]
            if language == "hi":
                stmt_text = f"कार्यक्षेत्र में मुख्य थीम शामिल हैं: {', '.join(topic_names)}।"
            else:
                stmt_text = f"Identified primary themes across active workspace: {', '.join(topic_names)}."

            all_rep_chunks = [cid for t in package.topics for cid in t.representative_chunk_ids if any(c.id == cid for c in package.chunks)]
            statements.append(
                AnswerStatement(
                    statement_text=stmt_text,
                    citation_chunk_ids=all_rep_chunks[:5],
                    citation_path_ids=[],
                    is_inference=False,
                    confidence=1.0,
                )
            )

        # If still no statements, synthesize directly from active chunks
        if not statements and package.chunks:
            for c in package.chunks[:2]:
                first_sentence = c.text.strip().split(".")[0].strip()
                if language == "hi":
                    stmt_text = f"स्रोत सामग्री में उल्लेख है: \"{first_sentence}\"।"
                else:
                    stmt_text = f"Source material notes: \"{first_sentence}\"."

                statements.append(
                    AnswerStatement(
                        statement_text=stmt_text,
                        citation_chunk_ids=[c.id],
                        citation_path_ids=[],
                        is_inference=False,
                        confidence=0.95,
                    )
                )

        return statements

    def repair_citations(
        self,
        statements: List[AnswerStatement],
        valid_chunk_ids: set[str],
        valid_path_ids: set[str],
    ) -> List[AnswerStatement]:
        """
        Server validates every citation/path before responding;
        invalid output gets one repair, then an extractive insufficient-evidence response.
        """
        repaired: List[AnswerStatement] = []
        for stmt in statements:
            had_chunks = bool(stmt.citation_chunk_ids)
            had_paths = bool(stmt.citation_path_ids)
            filtered_chunks = [cid for cid in stmt.citation_chunk_ids if cid in valid_chunk_ids]
            filtered_paths = [pid for pid in stmt.citation_path_ids if pid in valid_path_ids]

            # If invalid IDs were cited and no valid citations remain, discard this unsupported statement
            if (had_chunks and not filtered_chunks) or (had_paths and not filtered_paths):
                if not filtered_chunks and not filtered_paths:
                    continue

            repaired.append(
                AnswerStatement(
                    statement_text=stmt.statement_text,
                    citation_chunk_ids=filtered_chunks,
                    citation_path_ids=filtered_paths,
                    is_inference=stmt.is_inference,
                    confidence=stmt.confidence,
                    contradiction_ref_ids=stmt.contradiction_ref_ids,
                )
            )
        return repaired
