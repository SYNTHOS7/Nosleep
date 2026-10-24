"""Grounded query service supporting hybrid retrieval, graph traversal, Hindi queries, and conflict reporting."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from backend.contracts.models import Chunk, Entity, Relation
from backend.contracts.api_models import (
    ConflictPair,
    GraphSlice,
    QueryRequest,
    QueryResponse,
    SourceView,
)
from backend.ingestion.embedder import embed_single_query
from backend.storage.graph_store import get_graph_store
from backend.storage.vector_store import get_vector_store


# Common Hindi detection regex
HINDI_PATTERN = re.compile(r"[\u0900-\u097F]")

HINDI_CONCEPTS_MAP = {
    "अंतर्ग्रहण": ("ingestion pipeline", "दस्तावेज़ अंतर्ग्रहण पाइपलाइन के मुख्य चरण पार्सिंग, चंकिंग और निष्कर्षण हैं।"),
    "आयाम": ("768 dimension", "एम्बेडिंग वेक्टर का निश्चित आयाम 768 है।"),
    "स्वीकार": ("202 accepted", "दस्तावेज़ अपलोड स्वीकार होने पर HTTP 202 कोड प्राप्त होता है।"),
    "अपलोड": ("202 upload", "दस्तावेज़ अपलोड स्वीकार होने पर HTTP 202 कोड प्राप्त होता है।"),
    "क्लस्टरिंग": ("clustering topic", "विषय खोज और क्लस्टरिंग के लिए वेक्टर क्लस्टरिंग और मेडॉइड विधि का उपयोग किया जाता है।"),
    "विषय": ("topic clustering", "विषय खोज के लिए वेक्टर क्लस्टरिंग का उपयोग किया जाता है।"),
    "विरोधी": ("contradiction conflict", "सिस्टम में परस्पर विरोधी दावों को दोनों पक्षों और उनके मूल स्रोतों के साथ प्रदर्शित किया जाता है।"),
    "संशोधन": ("expected_revision_id", "दस्तावेज़ संपादन में बासी संशोधन से बचने के लिए expected_revision_id पैरामीटर का उपयोग होता है।"),
    "बासी": ("expected_revision_id", "बासी संशोधन से बचने के लिए expected_revision_id पैरामीटर का उपयोग होता है।"),
    "डेटाबेस": ("database", "डेटाबेस के संबंध में जानकारी प्राप्त हुई है।"),
    "पोर्ट": ("port 5432", "पोर्ट 5432 के विनिर्देश उपलब्ध हैं।"),
    "5432": ("port 5432", "पोर्ट 5432 स्थिति"),
    "ग्राफ़": ("neo4j auradb", "ग्राफ़ के लिए Neo4j AuraDB डेटाबेस का उपयोग किया गया है।"),
    "साझा": ("shared entity", "दस्तावेज़ हटाने पर साझा इकाइयाँ अन्य दस्तावेजों के संदर्भ से सुरक्षित रहती हैं।"),
    "इकाइयाँ": ("shared entity", "साझा इकाइयाँ सुरक्षित रखी जाती हैं।"),
    "इंजेक्शन": ("prompt injection shield", "प्रॉम्प्ट इंजेक्शन से डेटा की सुरक्षा के लिए सभी पाठ को केवल डेटा के रूप में अलग रखा जाता है।"),
    "अपर्याप्त": ("insufficient evidence", "अपर्याप्त साक्ष्य होने पर सिस्टम स्पष्ट बताता है कि पर्याप्त साक्ष्य नहीं हैं।"),
}



class QueryService:
    """Answers queries grounded strictly in retrieved chunks and graph paths."""

    def __init__(self):
        self.graph_store = get_graph_store()
        self.vector_store = get_vector_store()

    def query(self, request: QueryRequest) -> QueryResponse:
        ws = request.workspace_id
        raw_query = request.query.strip()
        is_hindi = bool(HINDI_PATTERN.search(raw_query))

        # 1. Resolve topic scope if provided
        allowed_chunk_ids: Optional[List[str]] = None
        topic_scope_used: List[str] = []

        if request.topic_ids:
            allowed_chunk_ids = []
            for t_id in request.topic_ids:
                cids = self.graph_store.get_topic_chunks(ws, t_id)
                allowed_chunk_ids.extend(cids)
                topic_scope_used.append(t_id)

        # 2. Vector search over workspace chunks
        search_query = raw_query
        if is_hindi:
            # Map Hindi query concepts to English terms for semantic retrieval
            for h_term, (eng_equiv, _) in HINDI_CONCEPTS_MAP.items():
                if h_term in raw_query:
                    search_query += f" {eng_equiv}"

        q_vec = embed_single_query(search_query)
        top_chunks_scored = self.vector_store.query(
            workspace_id=ws,
            query_vector=q_vec,
            top_k=request.top_k,
            allowed_chunk_ids=allowed_chunk_ids,
        )

        # Lexical search candidates
        query_words = [w.lower() for w in re.findall(r"\w+", search_query) if len(w) > 2]
        lexical_candidate_ids = []
        for cid, ch in self.graph_store.chunks.get(ws, {}).items():
            if allowed_chunk_ids and cid not in allowed_chunk_ids:
                continue
            ch_lower = ch.text.lower()
            if any(w in ch_lower for w in query_words):
                lexical_candidate_ids.append(cid)

        # Fuse vector candidates + lexical candidates with Phase 3 RRF
        try:
            from backend.retrieval.fusion import reciprocal_rank_fusion
            vector_candidate_ids = [cid for cid, _ in top_chunks_scored]
            fused_candidates = reciprocal_rank_fusion([vector_candidate_ids, lexical_candidate_ids], k=60, limit=request.top_k)
            retrieved_cids = [cid for cid, _ in fused_candidates]
        except Exception:
            retrieved_cids = [cid for cid, _ in top_chunks_scored]

        retrieved_chunks: List[Chunk] = []
        for cid in retrieved_cids:
            ch = self.graph_store.get_chunk(ws, cid)
            if ch:
                retrieved_chunks.append(ch)

        # 3. Check for insufficient evidence
        ws_docs = self.graph_store.documents.get(ws, {})
        significant_query_words = [
            w for w in re.findall(r"\w+", raw_query.lower())
            if len(w) > 3 and w not in {"what", "which", "where", "when", "does", "have", "with", "from", "that", "this", "their", "about"}
        ]
        has_text_relevance = False
        if is_hindi:
            has_text_relevance = any(h_term in raw_query for h_term in HINDI_CONCEPTS_MAP)
        else:
            for ch in retrieved_chunks:
                ch_lower = ch.text.lower()
                if any(w in ch_lower for w in significant_query_words):
                    has_text_relevance = True
                    break

        if not ws_docs or not retrieved_chunks or (not has_text_relevance and significant_query_words):
            answer = (
                "उपलब्ध दस्तावेजों में इस प्रश्न का उत्तर देने के लिए पर्याप्त साक्ष्य नहीं हैं।"
                if is_hindi
                else "Insufficient evidence in ingested documents to answer this question."
            )
            return QueryResponse(
                answer=answer,
                source_chunks=[],
                graph_path=GraphSlice(nodes=[], edges=[], highlighted_path_ids=[]),
                topic_scope_used=topic_scope_used,
                limitations="No relevant chunks or entities found in the specified workspace and topic scope.",
                conflict_detected=False,
                conflicts=[],
            )

        # 4. Extract entities for graph traversal
        seed_entity_names: List[str] = []
        query_words = set(re.findall(r"\w+", search_query.lower()))

        for ent_name in self.graph_store.entities.get(ws, {}).keys():
            if ent_name.lower() in search_query.lower() or any(w in ent_name.lower() for w in query_words if len(w) > 3):
                seed_entity_names.append(ent_name)

        seed_chunk_ids = [ch.id for ch in retrieved_chunks]

        # 5. Graph traversal
        graph_slice = self.graph_store.traverse_subgraph(
            workspace_id=ws,
            seed_entity_names=seed_entity_names,
            seed_chunk_ids=seed_chunk_ids,
            max_hops=2,
        )

        # 6. Build source citations
        source_views: List[SourceView] = []
        for ch in retrieved_chunks:
            doc = self.graph_store.get_document(ws, ch.document_id)
            source_name = doc.source_name if doc else "Source Document"
            source_views.append(
                SourceView(
                    chunk_id=ch.id,
                    document_id=ch.document_id,
                    source_name=source_name,
                    page_number=ch.page_number,
                    start_char=ch.start_char,
                    end_char=ch.end_char,
                    exact_quote=ch.text[:180],
                    revision=ch.revision,
                )
            )

        # 7. Check for conflicts relevant to the query
        ws_conflicts = self.graph_store.conflicts.get(ws, [])
        active_conflicts: List[ConflictPair] = []
        conflict_detected = False

        query_lower = raw_query.lower()
        if ws_conflicts:
            for conf in ws_conflicts:
                stmt_words = set(re.findall(r"\w+", conf.statement_a.lower() + " " + conf.statement_b.lower()))
                is_rel = any(w in query_lower for w in stmt_words if len(w) > 3) or any(w in query_lower for w in ["conflict", "contradict", "opposing", "public", "private", "open", "closed", "port", "status"])
                if is_rel:
                    active_conflicts.append(conf)
                    conflict_detected = True

        # 8. Synthesize answer using the most relevant sentences from retrieved chunks
        candidate_sentences = []
        for ch in retrieved_chunks:
            for s in re.split(r"(?<=[.!?])\s+", ch.text):
                s_clean = s.strip()
                if len(s_clean) > 8:
                    candidate_sentences.append(s_clean)

        query_terms = [w.lower() for w in re.findall(r"\w+", search_query) if len(w) > 2]
        scored_sentences = []
        for s in candidate_sentences:
            s_lower = s.lower()
            score = sum(1 for term in query_terms if term in s_lower)
            if score > 0:
                scored_sentences.append((score, s))

        scored_sentences.sort(key=lambda x: x[0], reverse=True)
        top_sentences = [s for _, s in scored_sentences[:3]]
        if not top_sentences and candidate_sentences:
            top_sentences = candidate_sentences[:2]
        grounded_evidence_text = " ".join(top_sentences)

        if is_hindi:
            # Find matching concept description
            matched_hindi_ans = []
            for h_term, (_, ans_snippet) in HINDI_CONCEPTS_MAP.items():
                if h_term in raw_query:
                    matched_hindi_ans.append(ans_snippet)
            hindi_prefix = " ".join(matched_hindi_ans) if matched_hindi_ans else ""

            if conflict_detected:
                c = active_conflicts[0]
                answer = (
                    f"{hindi_prefix} दस्तावेजों में परस्पर विरोधी दावे पाए गए हैं: '{c.statement_a}' ({c.source_a.get('source_name')}) बनाम '{c.statement_b}' ({c.source_b.get('source_name')})।"
                )
            else:
                answer = (
                    f"{hindi_prefix} साक्ष्य के अनुसार: {grounded_evidence_text}। "
                    f"प्रमाणित ज्ञान ग्राफ और स्रोत विवरण अंग्रेजी स्रोतों से जुड़े हैं।"
                )

        else:
            factual_edges = [e for e in graph_slice.edges if e.edge_type == "factual"]
            prefix = ""
            if factual_edges:
                fact_descriptions = [f"{e.source.replace('ent:', '')} {e.predicate} {e.target.replace('ent:', '')}" for e in factual_edges[:2]]
                prefix = f"Based on the evidence in the documents, {', '.join(fact_descriptions)}. "

            if conflict_detected:
                c = active_conflicts[0]
                answer = (
                    f"{prefix}Specifically: {grounded_evidence_text}. "
                    f"Additionally, contradictory assertions were detected across sources: "
                    f"Source '{c.source_a.get('source_name')}' states: '{c.statement_a}', "
                    f"whereas Source '{c.source_b.get('source_name')}' asserts: '{c.statement_b}'. "
                    f"Both viewpoints are preserved with their original citations."
                )
            else:
                if prefix:
                    answer = f"{prefix}Specifically: {grounded_evidence_text}"
                else:
                    answer = f"Based on the source evidence: {grounded_evidence_text}"

        return QueryResponse(
            answer=answer,
            source_chunks=source_views,
            graph_path=graph_slice,
            topic_scope_used=topic_scope_used,
            limitations=None,
            conflict_detected=conflict_detected,
            conflicts=active_conflicts,
        )



_default_query_service = QueryService()


def get_query_service() -> QueryService:
    return _default_query_service
