"""
Deterministic query planning and routing module.
Conforms to 03-topics-retrieval-answers-and-conflicts.md:
- Deterministic rules first (thematic, local, hybrid)
- Rationale codes
- Hindi auto-detection and labeling
- Strict topic scope enforcement
"""

from __future__ import annotations
import re
from typing import List, Set

from backend.contracts.models import QueryPlan, QueryRequest
from backend.storage.interface import CorpusSnapshot


# Thematic indicators
THEMATIC_PATTERNS = [
    r"\bmain themes?\b",
    r"\bpatterns?\b",
    r"\bacross documents?\b",
    r"\btopic lists?\b",
    r"\blist topics?\b",
    r"\boverview\b",
    r"\bsummarize\b",
    r"\bsummary\b",
    r"\bhigh[- ]level\b",
    r"\bgeneral trends?\b",
    r"\bcollection[- ]wide\b",
    r"\bwhat are the themes\b",
    r"\bमुख्य थीम\b",
    r"\bथीम\b",
    r"\bपैटर्न\b",
    r"\bसार\b",
]

# Hybrid connection / multi-hop indicators
HYBRID_PATTERNS = [
    r"\bconnect(ion)?s?\b",
    r"\brelationship between\b",
    r"\bhow does .* (affect|relate to|connect to|depend on)\b",
    r"\bpath between\b",
    r"\blink between\b",
    r"\binteraction between\b",
    r"\bbridge between\b",
    r"\bसंबंध\b",
    r"\bजोड़\b",
    r"\bमार्ग\b",
]

# Local question words
LOCAL_PATTERNS = [
    r"\bwho (is|was|are)\b",
    r"\bwhat is the (status|version|price|cost|location|date|type)\b",
    r"\bwhere is\b",
    r"\bwhen (was|is|did)\b",
    r"\bdoes .* (use|have|run|support)\b",
    r"\bक्या\b",
    r"\bकहाँ\b",
    r"\bकब\b",
    r"\bकौन\b",
    r"\bकिस\b",
    r"\bकैसे\b",
    r"\bकितना\b",
    r"\bनिर्भर\b",
]


def detect_hindi(text: str) -> bool:
    """Returns True if text contains Devanagari characters (Unicode \u0900-\u097F)."""
    return bool(re.search(r"[\u0900-\u097F]", text))


def plan_query(request: QueryRequest, snapshot: CorpusSnapshot) -> QueryPlan:
    """
    Plans query routing using deterministic rules and provides an explicit rationale code.
    """
    q_lower = request.question.lower().strip()

    # 1. Language detection
    is_hindi = detect_hindi(request.question) or request.answer_language == "hi"
    query_language = "hi" if is_hindi else "en"

    # 2. Scope resolution
    if request.scope == "selected":
        # Selected scope strictly filtered; never silently widens!
        target_topic_ids = [tid for tid in request.topic_ids if tid in snapshot.topics]
    else:
        target_topic_ids = [tid for tid, t in snapshot.topics.items() if t.active]

    # 3. Detect signals
    has_thematic = any(re.search(pat, q_lower) for pat in THEMATIC_PATTERNS)
    has_hybrid = any(re.search(pat, q_lower) for pat in HYBRID_PATTERNS)
    has_local = any(re.search(pat, q_lower) for pat in LOCAL_PATTERNS)

    # Check for known entity mentions in query
    entity_names = [e.name.lower() for e in snapshot.entities.values()]
    entities_mentioned = [name for name in entity_names if name in q_lower]

    # Deterministic routing logic
    if has_thematic and not entities_mentioned and not has_hybrid:
        query_type = "thematic"
        rationale_code = "THEMATIC_PATTERN_KEYWORD"
        use_vector = True
        use_lexical = True
        use_graph = False
        max_hops = 1

    elif has_hybrid or (has_thematic and entities_mentioned) or len(entities_mentioned) >= 2:
        query_type = "hybrid"
        rationale_code = "HYBRID_CONNECTION_MULTI_HOP"
        use_vector = True
        use_lexical = True
        use_graph = True
        max_hops = min(request.max_hops, 4)

    elif has_local or entities_mentioned:
        query_type = "local"
        rationale_code = "LOCAL_NAMED_ENTITY"
        use_vector = True
        use_lexical = True
        use_graph = True
        max_hops = min(request.max_hops, 2)

    else:
        # Default fallback: local if short query, thematic if broad query
        if len(q_lower.split()) > 7:
            query_type = "thematic"
            rationale_code = "THEMATIC_BROAD_QUERY_DEFAULT"
            use_vector = True
            use_lexical = True
            use_graph = False
            max_hops = 1
        else:
            query_type = "local"
            rationale_code = "LOCAL_FACTUAL_DEFAULT"
            use_vector = True
            use_lexical = True
            use_graph = True
            max_hops = 2

    return QueryPlan(
        query_type=query_type,
        rationale_code=rationale_code,
        query_language=query_language,
        target_topic_ids=target_topic_ids,
        use_vector=use_vector,
        use_lexical=use_lexical,
        use_graph=use_graph,
        max_hops=max_hops,
        top_k=request.top_k,
    )
