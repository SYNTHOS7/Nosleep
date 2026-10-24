"""Versioned evaluation gold set containing 30 Phase 1 questions and 10 Hindi Phase 2 questions."""

from typing import Any, Dict, List
from pydantic import BaseModel, Field


class GoldQuestion(BaseModel):
    id: str
    category: str  # "thematic", "local_factual", "multi_hop", "insufficient_evidence", "hindi"
    query: str
    expected_answer_keywords: List[str]
    expected_paths: List[str] = Field(default_factory=list)
    is_insufficient: bool = False
    is_hindi: bool = False


# Versioned Phase 1 gold set (30 questions)
PHASE1_GOLD_SET: List[GoldQuestion] = [
    # 10 Thematic Questions
    GoldQuestion(
        id="q-theme-01",
        category="thematic",
        query="What are the overarching architectural patterns for the ingestion pipeline?",
        expected_answer_keywords=["ingestion", "pipeline", "parsing", "chunking", "extraction"],
        expected_paths=["ent:IngestionPipeline", "rel:PART_OF"],
    ),
    GoldQuestion(
        id="q-theme-02",
        category="thematic",
        query="Explain the primary topic discovery and clustering strategy.",
        expected_answer_keywords=["topic", "clustering", "vector", "medoid", "themes"],
        expected_paths=["ent:TopicService", "rel:USES"],
    ),
    GoldQuestion(
        id="q-theme-03",
        category="thematic",
        query="What is the role of the lexical graph compared to the domain graph?",
        expected_answer_keywords=["lexical", "domain", "chunk", "document", "provenance"],
        expected_paths=["ent:LexicalGraph", "ent:DomainGraph"],
    ),
    GoldQuestion(
        id="q-theme-04",
        category="thematic",
        query="Summarize the system's conflict and contradiction preservation approach.",
        expected_answer_keywords=["contradiction", "conflict", "preservation", "sources"],
        expected_paths=["ent:ConflictService"],
    ),
    GoldQuestion(
        id="q-theme-05",
        category="thematic",
        query="How does the system ensure prompt injection resistance across text ingestion?",
        expected_answer_keywords=["injection", "untrusted", "data", "shield", "delimiter"],
        expected_paths=["ent:PromptShield"],
    ),
    GoldQuestion(
        id="q-theme-06",
        category="thematic",
        query="What are the core components governing document mutation operations?",
        expected_answer_keywords=["operation", "mutation", "checkpoint", "durable"],
        expected_paths=["ent:OperationManager"],
    ),
    GoldQuestion(
        id="q-theme-07",
        category="thematic",
        query="Describe the vector retrieval and cosine similarity indexing design.",
        expected_answer_keywords=["vector", "cosine", "similarity", "embedding", "dimension"],
        expected_paths=["ent:VectorStore"],
    ),
    GoldQuestion(
        id="q-theme-08",
        category="thematic",
        query="How does workspace isolation protect multi-tenant boundaries?",
        expected_answer_keywords=["workspace", "isolation", "boundary", "partition"],
        expected_paths=["ent:WorkspaceIsolation"],
    ),
    GoldQuestion(
        id="q-theme-09",
        category="thematic",
        query="What is the incremental update strategy for maintaining graph freshness under 60 seconds?",
        expected_answer_keywords=["incremental", "lifecycle", "freshness", "seconds", "rebuild"],
        expected_paths=["ent:LifecycleService"],
    ),
    GoldQuestion(
        id="q-theme-10",
        category="thematic",
        query="What guarantees exist regarding shared entity preservation upon document deletion?",
        expected_answer_keywords=["shared", "entity", "deletion", "reference", "preservation"],
        expected_paths=["ent:EntityPreservation"],
    ),

    # 10 Local Factual Questions
    GoldQuestion(
        id="q-fact-01",
        category="local_factual",
        query="What is the pinned embedding vector dimension?",
        expected_answer_keywords=["768", "dimension"],
        expected_paths=["ent:EmbeddingModel", "rel:HAS_VALUE"],
    ),
    GoldQuestion(
        id="q-fact-02",
        category="local_factual",
        query="Which tokenizer is frozen in pipeline-lock.json?",
        expected_answer_keywords=["cl100k_base", "tokenizer"],
        expected_paths=["ent:Tokenizer"],
    ),
    GoldQuestion(
        id="q-fact-03",
        category="local_factual",
        query="What HTTP status code is returned upon accepting a document upload?",
        expected_answer_keywords=["202", "accepted"],
        expected_paths=["ent:UploadRoute", "rel:RETURNS"],
    ),
    GoldQuestion(
        id="q-fact-04",
        category="local_factual",
        query="What is the maximum token budget per chunk?",
        expected_answer_keywords=["800", "tokens"],
        expected_paths=["ent:Chunker"],
    ),
    GoldQuestion(
        id="q-fact-05",
        category="local_factual",
        query="What error code is raised when a PDF contains no extractable text?",
        expected_answer_keywords=["NO_EXTRACTABLE_TEXT"],
        expected_paths=["ent:PDFParser"],
    ),
    GoldQuestion(
        id="q-fact-06",
        category="local_factual",
        query="What is the fallback label for extracted entities when no specific label matches?",
        expected_answer_keywords=["Entity"],
        expected_paths=["ent:SchemaConfig"],
    ),
    GoldQuestion(
        id="q-fact-07",
        category="local_factual",
        query="What is the fallback relation predicate in the extraction schema?",
        expected_answer_keywords=["RELATED_TO"],
        expected_paths=["ent:SchemaConfig"],
    ),
    GoldQuestion(
        id="q-fact-08",
        category="local_factual",
        query="What graph database is targeted by the architecture?",
        expected_answer_keywords=["Neo4j", "AuraDB"],
        expected_paths=["ent:GraphDB"],
    ),
    GoldQuestion(
        id="q-fact-09",
        category="local_factual",
        query="What operation status indicates that an operation is persisted to disk?",
        expected_answer_keywords=["ACCEPTED", "STAGED", "checkpoint"],
        expected_paths=["ent:OperationStatus"],
    ),
    GoldQuestion(
        id="q-fact-10",
        category="local_factual",
        query="What parameter is required to prevent stale edits during document updates?",
        expected_answer_keywords=["expected_revision_id"],
        expected_paths=["ent:EditRoute"],
    ),

    # 5 Multi-Hop Questions
    GoldQuestion(
        id="q-hop-01",
        category="multi_hop",
        query="Which service initiates parsing, and what Element structure does the chunker depend on from it?",
        expected_answer_keywords=["parser", "chunker", "element_id", "page_number"],
        expected_paths=["ent:Parser", "rel:PRODUCES", "ent:Element", "ent:Chunker"],
    ),
    GoldQuestion(
        id="q-hop-02",
        category="multi_hop",
        query="Trace how an uploaded document becomes a set of vectors linked to a topic.",
        expected_answer_keywords=["document", "chunk", "vector", "embedder", "topic"],
        expected_paths=["ent:Document", "ent:Chunk", "ent:Topic", "rel:HAS_MEMBER"],
    ),
    GoldQuestion(
        id="q-hop-03",
        category="multi_hop",
        query="How does an edit request propagate from API validation through revision increment to vector update?",
        expected_answer_keywords=["revision", "validation", "batch", "vectors"],
        expected_paths=["ent:EditRoute", "ent:LifecycleService", "ent:VectorStore"],
    ),
    GoldQuestion(
        id="q-hop-04",
        category="multi_hop",
        query="How do candidate graphs extracted from chunks get resolved into canonical entities and relations?",
        expected_answer_keywords=["candidate", "graphs", "canonical", "aggregated", "relations"],
        expected_paths=["ent:Extractor", "ent:CandidateGraph", "ent:GraphStore"],
    ),
    GoldQuestion(
        id="q-hop-05",
        category="multi_hop",
        query="Explain how a query connects an entity match to a source chunk quote and document revision.",
        expected_answer_keywords=["provenance", "exact_quote", "chunk", "revision"],
        expected_paths=["ent:QueryService", "ent:Provenance", "ent:SourceView"],
    ),

    # 5 Insufficient Evidence Questions
    GoldQuestion(
        id="q-insuff-01",
        category="insufficient_evidence",
        query="What is the internal quantum encryption algorithm used by the 2035 quantum satellite?",
        expected_answer_keywords=["insufficient evidence"],
        is_insufficient=True,
    ),
    GoldQuestion(
        id="q-insuff-02",
        category="insufficient_evidence",
        query="Who won the 1927 Olympic badminton singles gold medal?",
        expected_answer_keywords=["insufficient evidence"],
        is_insufficient=True,
    ),
    GoldQuestion(
        id="q-insuff-03",
        category="insufficient_evidence",
        query="What is the recipe for grandmother's sourdough apple pie?",
        expected_answer_keywords=["insufficient evidence"],
        is_insufficient=True,
    ),
    GoldQuestion(
        id="q-insuff-04",
        category="insufficient_evidence",
        query="How many submarines were constructed in Atlantis in 1840?",
        expected_answer_keywords=["insufficient evidence"],
        is_insufficient=True,
    ),
    GoldQuestion(
        id="q-insuff-05",
        category="insufficient_evidence",
        query="What is the atmospheric composition of Kepler-452b at ground level?",
        expected_answer_keywords=["insufficient evidence"],
        is_insufficient=True,
    ),
]

# Phase 2 Hindi subset (10 questions over English documents)
HINDI_SUBSET: List[GoldQuestion] = [
    GoldQuestion(
        id="q-hindi-01",
        category="hindi",
        query="दस्तावेज़ अंतर्ग्रहण पाइपलाइन के मुख्य चरण क्या हैं?",
        expected_answer_keywords=["साक्ष्य", "पाइपलाइन"],
        is_hindi=True,
    ),
    GoldQuestion(
        id="q-hindi-02",
        category="hindi",
        query="एम्बेडिंग वेक्टर का निश्चित आयाम क्या है?",
        expected_answer_keywords=["768", "आयाम"],
        is_hindi=True,
    ),
    GoldQuestion(
        id="q-hindi-03",
        category="hindi",
        query="दस्तावेज़ अपलोड स्वीकार होने पर कौन सा HTTP कोड प्राप्त होता है?",
        expected_answer_keywords=["202", "स्वीकृत"],
        is_hindi=True,
    ),
    GoldQuestion(
        id="q-hindi-04",
        category="hindi",
        query="विषय खोज और क्लस्टरिंग के लिए कौन सी विधि उपयोग की जाती है?",
        expected_answer_keywords=["क्लस्टरिंग", "विषय"],
        is_hindi=True,
    ),
    GoldQuestion(
        id="q-hindi-05",
        category="hindi",
        query="क्या सिस्टम में परस्पर विरोधी दावों को दोनों पक्षों के साथ प्रदर्शित किया जाता है?",
        expected_answer_keywords=["विरोधी", "दावे", "स्रोत"],
        is_hindi=True,
    ),
    GoldQuestion(
        id="q-hindi-06",
        category="hindi",
        query="दस्तावेज़ संपादन में बासी संशोधन से बचने के लिए किस पैरामीटर का उपयोग होता है?",
        expected_answer_keywords=["संशोधन", "expected_revision_id"],
        is_hindi=True,
    ),
    GoldQuestion(
        id="q-hindi-07",
        category="hindi",
        query="ग्राफ़ में कौन सा डेटाबेस इस्तेमाल किया गया है?",
        expected_answer_keywords=["Neo4j", "AuraDB"],
        is_hindi=True,
    ),
    GoldQuestion(
        id="q-hindi-08",
        category="hindi",
        query="दस्तावेज़ हटाने पर साझा इकाइयाँ कैसे सुरक्षित रहती हैं?",
        expected_answer_keywords=["साझा", "इकाइयाँ"],
        is_hindi=True,
    ),
    GoldQuestion(
        id="q-hindi-09",
        category="hindi",
        query="प्रॉम्प्ट इंजेक्शन से डेटा की सुरक्षा कैसे की जाती है?",
        expected_answer_keywords=["डेटा", "सुरक्षा", "इंजेक्शन"],
        is_hindi=True,
    ),
    GoldQuestion(
        id="q-hindi-10",
        category="hindi",
        query="अपर्याप्त साक्ष्य होने पर सिस्टम क्या उत्तर देता है?",
        expected_answer_keywords=["पर्याप्त साक्ष्य नहीं", "साक्ष्य"],
        is_hindi=True,
    ),
]
