"""
QueryResponse fixtures for Person 4 (API, UI, and Acceptance testing).
Contains validated production-grade fixtures for:
1. Local factual query
2. Thematic / broad query
3. Hybrid multi-hop query
4. Hindi query over English source evidence
5. Conflict / contradiction query showing both sources
6. Truncation query with explicit limitations
7. Insufficient evidence query
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Dict

from backend.contracts.models import (
    AnswerStatement,
    Chunk,
    Conflict,
    Document,
    Entity,
    Evidence,
    EvidencePackage,
    EvidencePath,
    GraphEdgeView,
    GraphNodeView,
    GraphSlice,
    Location,
    ProvenanceLink,
    QueryPlan,
    QueryResponse,
    Relation,
    Revision,
    Topic,
    Value,
    utc_now,
)

WS_ID = "ws_pilot_01"
NOW = datetime(2026, 10, 24, 15, 0, 0, tzinfo=timezone.utc)

# Helper function to create sample evidence
def _make_chunk(cid: str, did: str, rid: str, text: str) -> Chunk:
    return Chunk(
        id=cid,
        workspace_id=WS_ID,
        document_id=did,
        revision_id=rid,
        index=0,
        text=text,
        text_hash=f"hash_{cid}",
        location=Location(page=1, element_ids=[f"el_{cid}"], start_offset=0, end_offset=len(text)),
    )


# 1. Local Query Response Fixture
def get_local_query_fixture() -> QueryResponse:
    chunk1 = _make_chunk("chunk_01", "doc_01", "rev_01", "PaymentGateway depends on AuthService for authentication tokens.")
    entity_pg = Entity(id="ent_pg", workspace_id=WS_ID, name="PaymentGateway", normalized_name="paymentgateway", type="Service")
    entity_as = Entity(id="ent_as", workspace_id=WS_ID, name="AuthService", normalized_name="authservice", type="Service")

    rel1 = Relation(
        id="rel_01",
        workspace_id=WS_ID,
        revision_id="rev_01",
        subject_id=entity_pg.id,
        object_entity_id=entity_as.id,
        predicate="DEPENDS_ON",
        predicate_original="depends on",
        polarity="positive",
        modality="asserted",
        evidence=Evidence(chunk_id=chunk1.id, start=0, end=len(chunk1.text), quote=chunk1.text),
        extraction_model="test-extractor",
        extraction_version="v1",
    )

    path1 = EvidencePath(
        path_id="path_pg_as",
        node_ids=[entity_pg.id, entity_as.id],
        edges=[
            GraphEdgeView(
                id="edge_rel_01",
                source_id=entity_pg.id,
                target_id=entity_as.id,
                predicate="DEPENDS_ON",
                relation_id=rel1.id,
                source_chunk_id=chunk1.id,
                is_topic_membership=False,
            )
        ],
        provenance_links=[
            ProvenanceLink(chunk_id=chunk1.id, revision_id="rev_01", document_id="doc_01")
        ],
    )

    package = EvidencePackage(
        workspace_id=WS_ID,
        corpus_epoch=1,
        chunks=[chunk1],
        relations=[rel1],
        entities=[entity_pg, entity_as],
        values=[],
        paths=[path1],
        topics=[],
        conflicts=[],
        searched_count=1,
        available_count=20,
    )

    graph = GraphSlice(
        nodes=[
            GraphNodeView(id=entity_pg.id, label="PaymentGateway", node_type="Entity"),
            GraphNodeView(id=entity_as.id, label="AuthService", node_type="Entity"),
            GraphNodeView(id=chunk1.id, label="Chunk 01", node_type="Chunk"),
        ],
        edges=[path1.edges[0]],
        truncated=False,
    )

    return QueryResponse(
        request_id="req_local_01",
        corpus_epoch=1,
        status="answered",
        language="en",
        plan=QueryPlan(
            query_type="local",
            rationale_code="LOCAL_NAMED_ENTITY",
            query_language="en",
            target_topic_ids=[],
            max_hops=2,
            top_k=10,
        ),
        statements=[
            AnswerStatement(
                statement_text="According to verified documentation: PaymentGateway DEPENDS_ON AuthService.",
                citation_chunk_ids=[chunk1.id],
                citation_path_ids=[path1.path_id],
                is_inference=False,
                confidence=1.0,
            )
        ],
        evidence=package,
        graph=graph,
        latency_ms=18.5,
        warnings=[],
    )


# 2. Thematic Query Response Fixture
def get_thematic_query_fixture() -> QueryResponse:
    chunk_t1 = _make_chunk("chunk_t1", "doc_02", "rev_01", "Authentication architecture focuses on OAuth2 and JWT token verification.")
    chunk_t2 = _make_chunk("chunk_t2", "doc_03", "rev_01", "Payment processing infrastructure manages Stripe integrations and webhooks.")

    topic_auth = Topic(
        id="topic_auth_01",
        workspace_id=WS_ID,
        label="Auth & Security Architecture",
        description="Covers identity providers, token validation, and OAuth flows.",
        cluster_version="cluster-v1",
        embedding_version="multilingual-embed-v1",
        centroid=[0.1] * 64,
        representative_chunk_ids=[chunk_t1.id],
        summary_evidence_ids=[chunk_t1.id],
        summary_status="fresh",
        active=True,
    )

    topic_pay = Topic(
        id="topic_pay_01",
        workspace_id=WS_ID,
        label="Payment Processing & Billing",
        description="Covers payment gateways, checkout flows, and Stripe integration.",
        cluster_version="cluster-v1",
        embedding_version="multilingual-embed-v1",
        centroid=[0.2] * 64,
        representative_chunk_ids=[chunk_t2.id],
        summary_evidence_ids=[chunk_t2.id],
        summary_status="fresh",
        active=True,
    )

    package = EvidencePackage(
        workspace_id=WS_ID,
        corpus_epoch=1,
        chunks=[chunk_t1, chunk_t2],
        relations=[],
        entities=[],
        values=[],
        paths=[],
        topics=[topic_auth, topic_pay],
        conflicts=[],
        searched_count=2,
        available_count=2,
    )

    graph = GraphSlice(
        nodes=[
            GraphNodeView(id=topic_auth.id, label=topic_auth.label, node_type="Topic"),
            GraphNodeView(id=topic_pay.id, label=topic_pay.label, node_type="Topic"),
            GraphNodeView(id=chunk_t1.id, label="Chunk t1", node_type="Chunk"),
            GraphNodeView(id=chunk_t2.id, label="Chunk t2", node_type="Chunk"),
        ],
        edges=[
            GraphEdgeView(id="edge_mem_1", source_id=topic_auth.id, target_id=chunk_t1.id, predicate="HAS_MEMBER", is_topic_membership=True),
            GraphEdgeView(id="edge_mem_2", source_id=topic_pay.id, target_id=chunk_t2.id, predicate="HAS_MEMBER", is_topic_membership=True),
        ],
        truncated=False,
    )

    return QueryResponse(
        request_id="req_thematic_01",
        corpus_epoch=1,
        status="answered",
        language="en",
        plan=QueryPlan(
            query_type="thematic",
            rationale_code="THEMATIC_PATTERN_KEYWORD",
            query_language="en",
            target_topic_ids=[topic_auth.id, topic_pay.id],
            max_hops=1,
            top_k=10,
        ),
        statements=[
            AnswerStatement(
                statement_text="Identified primary themes across active workspace: Auth & Security Architecture, Payment Processing & Billing.",
                citation_chunk_ids=[chunk_t1.id, chunk_t2.id],
                citation_path_ids=[],
                is_inference=False,
                confidence=1.0,
            )
        ],
        evidence=package,
        graph=graph,
        latency_ms=24.0,
        warnings=[],
    )


# 3. Hybrid Multi-Hop Query Response Fixture
def get_hybrid_query_fixture() -> QueryResponse:
    chunk1 = _make_chunk("chunk_h1", "doc_01", "rev_01", "PaymentGateway connects to AuthService for authorization.")
    chunk2 = _make_chunk("chunk_h2", "doc_04", "rev_01", "AuthService reads user credentials from DatabaseCluster.")

    ent_pg = Entity(id="ent_pg", workspace_id=WS_ID, name="PaymentGateway", normalized_name="paymentgateway", type="Service")
    ent_as = Entity(id="ent_as", workspace_id=WS_ID, name="AuthService", normalized_name="authservice", type="Service")
    ent_db = Entity(id="ent_db", workspace_id=WS_ID, name="DatabaseCluster", normalized_name="databasecluster", type="Database")

    rel1 = Relation(
        id="rel_h1",
        workspace_id=WS_ID,
        revision_id="rev_01",
        subject_id=ent_pg.id,
        object_entity_id=ent_as.id,
        predicate="CONNECTS_TO",
        predicate_original="connects to",
        polarity="positive",
        evidence=Evidence(chunk_id=chunk1.id, start=0, end=len(chunk1.text), quote=chunk1.text),
        extraction_model="test-extractor",
        extraction_version="v1",
    )
    rel2 = Relation(
        id="rel_h2",
        workspace_id=WS_ID,
        revision_id="rev_01",
        subject_id=ent_as.id,
        object_entity_id=ent_db.id,
        predicate="READS_FROM",
        predicate_original="reads from",
        polarity="positive",
        evidence=Evidence(chunk_id=chunk2.id, start=0, end=len(chunk2.text), quote=chunk2.text),
        extraction_model="test-extractor",
        extraction_version="v1",
    )

    path = EvidencePath(
        path_id="path_multi_hop_01",
        node_ids=[ent_pg.id, ent_as.id, ent_db.id],
        edges=[
            GraphEdgeView(id="edge_rel_h1", source_id=ent_pg.id, target_id=ent_as.id, predicate="CONNECTS_TO", relation_id=rel1.id, source_chunk_id=chunk1.id),
            GraphEdgeView(id="edge_rel_h2", source_id=ent_as.id, target_id=ent_db.id, predicate="READS_FROM", relation_id=rel2.id, source_chunk_id=chunk2.id),
        ],
        provenance_links=[
            ProvenanceLink(chunk_id=chunk1.id, revision_id="rev_01", document_id="doc_01"),
            ProvenanceLink(chunk_id=chunk2.id, revision_id="rev_01", document_id="doc_04"),
        ],
    )

    package = EvidencePackage(
        workspace_id=WS_ID,
        corpus_epoch=1,
        chunks=[chunk1, chunk2],
        relations=[rel1, rel2],
        entities=[ent_pg, ent_as, ent_db],
        values=[],
        paths=[path],
        topics=[],
        conflicts=[],
        searched_count=2,
        available_count=20,
    )

    graph = GraphSlice(
        nodes=[
            GraphNodeView(id=ent_pg.id, label="PaymentGateway", node_type="Service"),
            GraphNodeView(id=ent_as.id, label="AuthService", node_type="Service"),
            GraphNodeView(id=ent_db.id, label="DatabaseCluster", node_type="Database"),
        ],
        edges=path.edges,
        truncated=False,
    )

    return QueryResponse(
        request_id="req_hybrid_01",
        corpus_epoch=1,
        status="answered",
        language="en",
        plan=QueryPlan(
            query_type="hybrid",
            rationale_code="HYBRID_CONNECTION_MULTI_HOP",
            query_language="en",
            target_topic_ids=[],
            max_hops=3,
            top_k=10,
        ),
        statements=[
            AnswerStatement(
                statement_text="According to verified documentation: PaymentGateway CONNECTS_TO AuthService -> AuthService READS_FROM DatabaseCluster.",
                citation_chunk_ids=[chunk1.id, chunk2.id],
                citation_path_ids=[path.path_id],
                is_inference=False,
                confidence=1.0,
            )
        ],
        evidence=package,
        graph=graph,
        latency_ms=28.2,
        warnings=[],
    )


# 4. Hindi Query Response Fixture
def get_hindi_query_fixture() -> QueryResponse:
    chunk1 = _make_chunk("chunk_hi_01", "doc_01", "rev_01", "PaymentGateway depends on AuthService for transaction authentication.")
    ent_pg = Entity(id="ent_pg", workspace_id=WS_ID, name="PaymentGateway", normalized_name="paymentgateway", type="Service")
    ent_as = Entity(id="ent_as", workspace_id=WS_ID, name="AuthService", normalized_name="authservice", type="Service")

    rel1 = Relation(
        id="rel_hi_01",
        workspace_id=WS_ID,
        revision_id="rev_01",
        subject_id=ent_pg.id,
        object_entity_id=ent_as.id,
        predicate="DEPENDS_ON",
        predicate_original="depends on",
        polarity="positive",
        evidence=Evidence(chunk_id=chunk1.id, start=0, end=len(chunk1.text), quote=chunk1.text),
        extraction_model="test-extractor",
        extraction_version="v1",
    )

    path1 = EvidencePath(
        path_id="path_hi_01",
        node_ids=[ent_pg.id, ent_as.id],
        edges=[
            GraphEdgeView(id="edge_rel_hi_01", source_id=ent_pg.id, target_id=ent_as.id, predicate="DEPENDS_ON", relation_id=rel1.id, source_chunk_id=chunk1.id)
        ],
        provenance_links=[
            ProvenanceLink(chunk_id=chunk1.id, revision_id="rev_01", document_id="doc_01")
        ],
    )

    package = EvidencePackage(
        workspace_id=WS_ID,
        corpus_epoch=1,
        chunks=[chunk1],
        relations=[rel1],
        entities=[ent_pg, ent_as],
        values=[],
        paths=[path1],
        topics=[],
        conflicts=[],
        searched_count=1,
        available_count=20,
    )

    return QueryResponse(
        request_id="req_hindi_01",
        corpus_epoch=1,
        status="answered",
        language="hi",
        plan=QueryPlan(
            query_type="local",
            rationale_code="LOCAL_NAMED_ENTITY",
            query_language="hi",
            target_topic_ids=[],
            max_hops=2,
            top_k=10,
        ),
        statements=[
            AnswerStatement(
                statement_text="दस्तावेजी साक्ष्य के अनुसार: PaymentGateway DEPENDS_ON AuthService।",
                citation_chunk_ids=[chunk1.id],
                citation_path_ids=[path1.path_id],
                is_inference=False,
                confidence=1.0,
            )
        ],
        evidence=package,
        graph=GraphSlice(
            nodes=[
                GraphNodeView(id=ent_pg.id, label="PaymentGateway", node_type="Entity"),
                GraphNodeView(id=ent_as.id, label="AuthService", node_type="Entity"),
            ],
            edges=path1.edges,
            truncated=False,
        ),
        latency_ms=22.4,
        warnings=[],
    )


# 5. Conflict Query Response Fixture
def get_conflict_query_fixture() -> QueryResponse:
    chunk_a = _make_chunk("chunk_c_left", "doc_v1", "rev_01", "PaymentAPI license is open_source and freely distributable.")
    chunk_b = _make_chunk("chunk_c_right", "doc_v2", "rev_02", "PaymentAPI license is proprietary and strictly confidential.")

    ent_api = Entity(id="ent_papi", workspace_id=WS_ID, name="PaymentAPI", normalized_name="paymentapi", type="System")
    val_os = Value(id="val_os", workspace_id=WS_ID, kind="text", lexical_value="open_source", normalized_value="open_source")
    val_prop = Value(id="val_prop", workspace_id=WS_ID, kind="text", lexical_value="proprietary", normalized_value="proprietary")

    rel_a = Relation(
        id="rel_conf_left",
        workspace_id=WS_ID,
        revision_id="rev_01",
        subject_id=ent_api.id,
        object_value_id=val_os.id,
        predicate="HAS_STATUS",
        predicate_original="license is",
        polarity="positive",
        evidence=Evidence(chunk_id=chunk_a.id, start=0, end=len(chunk_a.text), quote=chunk_a.text),
        extraction_model="test-extractor",
        extraction_version="v1",
    )
    rel_b = Relation(
        id="rel_conf_right",
        workspace_id=WS_ID,
        revision_id="rev_02",
        subject_id=ent_api.id,
        object_value_id=val_prop.id,
        predicate="HAS_STATUS",
        predicate_original="license is",
        polarity="positive",
        evidence=Evidence(chunk_id=chunk_b.id, start=0, end=len(chunk_b.text), quote=chunk_b.text),
        extraction_model="test-extractor",
        extraction_version="v1",
    )

    conflict = Conflict(
        id="conflict_papi_license",
        workspace_id=WS_ID,
        left_relation_id=rel_a.id,
        right_relation_id=rel_b.id,
        kind="exclusive_value",
        state="supported",
        explanation="Exclusive value conflict on predicate 'has_status': Source A asserts 'open_source' vs Source B asserts 'proprietary'.",
        evidence_chunk_ids=[chunk_a.id, chunk_b.id],
        detector_version="conflict-detector-v1",
    )

    package = EvidencePackage(
        workspace_id=WS_ID,
        corpus_epoch=2,
        chunks=[chunk_a, chunk_b],
        relations=[rel_a, rel_b],
        entities=[ent_api],
        values=[val_os, val_prop],
        paths=[],
        topics=[],
        conflicts=[conflict],
        searched_count=2,
        available_count=25,
    )

    return QueryResponse(
        request_id="req_conflict_01",
        corpus_epoch=2,
        status="answered",
        language="en",
        plan=QueryPlan(
            query_type="local",
            rationale_code="LOCAL_NAMED_ENTITY",
            query_language="en",
            target_topic_ids=[],
            max_hops=2,
            top_k=10,
        ),
        statements=[
            AnswerStatement(
                statement_text=(
                    f"Conflicting claims detected between sources: One source (Chunk {chunk_a.id}) "
                    f"states '{chunk_a.text}', whereas another source (Chunk {chunk_b.id}) "
                    f"states '{chunk_b.text}'."
                ),
                citation_chunk_ids=[chunk_a.id, chunk_b.id],
                citation_path_ids=[],
                is_inference=False,
                confidence=1.0,
                contradiction_ref_ids=[conflict.id],
            )
        ],
        evidence=package,
        graph=GraphSlice(
            nodes=[
                GraphNodeView(id=ent_api.id, label="PaymentAPI", node_type="System"),
                GraphNodeView(id=val_os.id, label="open_source", node_type="Value"),
                GraphNodeView(id=val_prop.id, label="proprietary", node_type="Value"),
            ],
            edges=[
                GraphEdgeView(id="edge_ca", source_id=ent_api.id, target_id=val_os.id, predicate="HAS_STATUS", relation_id=rel_a.id, source_chunk_id=chunk_a.id),
                GraphEdgeView(id="edge_cb", source_id=ent_api.id, target_id=val_prop.id, predicate="HAS_STATUS", relation_id=rel_b.id, source_chunk_id=chunk_b.id),
            ],
            truncated=False,
        ),
        latency_ms=26.3,
        warnings=[],
    )


# 6. Truncation Query Response Fixture
def get_truncation_query_fixture() -> QueryResponse:
    chunk_rep = _make_chunk("chunk_rep_01", "doc_01", "rev_01", "Core cloud architecture documentation and cluster policies.")
    topic = Topic(
        id="topic_large_01",
        workspace_id=WS_ID,
        label="Cloud Infrastructure",
        description="Covers cloud deployment configurations and policies.",
        cluster_version="cluster-v1",
        embedding_version="multilingual-embed-v1",
        centroid=[0.5] * 64,
        representative_chunk_ids=[chunk_rep.id],
        summary_evidence_ids=[chunk_rep.id],
        summary_status="fresh",
        active=True,
    )

    package = EvidencePackage(
        workspace_id=WS_ID,
        corpus_epoch=1,
        chunks=[chunk_rep],
        relations=[],
        entities=[],
        values=[],
        paths=[],
        topics=[topic],
        conflicts=[],
        truncated=True,
        searched_count=1,
        available_count=520,
        limitations=[
            "Thematic overview represents top 1 clusters across 1 representative chunks. Corpus contains 520 total active chunks. Broad answer cannot claim exhaustive themes from top-k alone."
        ],
    )

    return QueryResponse(
        request_id="req_trunc_01",
        corpus_epoch=1,
        status="answered",
        language="en",
        plan=QueryPlan(
            query_type="thematic",
            rationale_code="THEMATIC_PATTERN_KEYWORD",
            query_language="en",
            target_topic_ids=[topic.id],
            max_hops=1,
            top_k=10,
        ),
        statements=[
            AnswerStatement(
                statement_text="Identified primary themes across active workspace: Cloud Infrastructure.",
                citation_chunk_ids=[chunk_rep.id],
                citation_path_ids=[],
                is_inference=False,
                confidence=0.9,
            )
        ],
        evidence=package,
        graph=GraphSlice(
            nodes=[GraphNodeView(id=topic.id, label=topic.label, node_type="Topic")],
            edges=[],
            truncated=True,
        ),
        latency_ms=31.0,
        warnings=package.limitations,
    )


# 7. Insufficient Evidence Query Response Fixture
def get_insufficient_evidence_query_fixture() -> QueryResponse:
    package = EvidencePackage(
        workspace_id=WS_ID,
        corpus_epoch=1,
        chunks=[],
        relations=[],
        entities=[],
        values=[],
        paths=[],
        topics=[],
        conflicts=[],
        truncated=False,
        searched_count=0,
        available_count=150,
        limitations=["Underfilled active-filtered retrieval: No matching active chunks found under the current topic scope."],
    )

    return QueryResponse(
        request_id="req_insufficient_01",
        corpus_epoch=1,
        status="insufficient_evidence",
        language="en",
        plan=QueryPlan(
            query_type="local",
            rationale_code="LOCAL_FACTUAL_DEFAULT",
            query_language="en",
            target_topic_ids=[],
            max_hops=2,
            top_k=10,
        ),
        statements=[
            AnswerStatement(
                statement_text="No supporting evidence found in the active workspace for the requested query.",
                citation_chunk_ids=[],
                citation_path_ids=[],
                is_inference=False,
                confidence=1.0,
            )
        ],
        evidence=package,
        graph=GraphSlice(nodes=[], edges=[], truncated=False),
        latency_ms=12.1,
        warnings=package.limitations,
    )


ALL_FIXTURES: Dict[str, QueryResponse] = {
    "local": get_local_query_fixture(),
    "thematic": get_thematic_query_fixture(),
    "hybrid": get_hybrid_query_fixture(),
    "hindi": get_hindi_query_fixture(),
    "conflict": get_conflict_query_fixture(),
    "truncation": get_truncation_query_fixture(),
    "insufficient_evidence": get_insufficient_evidence_query_fixture(),
}
