"""Deterministic LangGraph evidence workflow; no LLM, scanner execution or remediation tools."""
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from backend.contracts.api_models import QueryRequest
from backend.services.query_service import get_query_service
from backend.services.attack_path_service import trace_attack_paths
from backend.storage.graph_store import get_graph_store


class InvestigationState(TypedDict, total=False):
    workspace_id: str
    entry_point: str
    evidence: dict
    paths: dict
    review: dict


def gather(state):
    response = get_query_service().query(QueryRequest(workspace_id=state["workspace_id"],
                                                   query=f"Evidence and conflicting claims about {state['entry_point']}", top_k=8))
    evidence = response.model_dump()
    # Broad similarity candidates must not become attributed evidence for an
    # exact CVE/entity investigation unless the passage actually names it.
    needle = state["entry_point"].strip().casefold()
    focused = []
    for source in evidence["source_chunks"]:
        chunk = get_graph_store().get_chunk(state["workspace_id"], source["chunk_id"])
        if chunk and needle in chunk.text.casefold():
            focused.append({**source, "exact_quote": chunk.text, "start_char": chunk.start_char,
                            "end_char": chunk.end_char})
    evidence["source_chunks"] = focused
    chunk_ids = {source["chunk_id"] for source in evidence["source_chunks"]}
    evidence["conflicts"] = [pair for pair in evidence["conflicts"]
                             if pair["source_a"].get("chunk_id") in chunk_ids and pair["source_b"].get("chunk_id") in chunk_ids]
    evidence["conflict_detected"] = bool(evidence["conflicts"])
    evidence["answer"] = "\n".join(f"{source['exact_quote']} [chunk {source['chunk_id']}]"
                                       for source in evidence["source_chunks"]) or "No matching source passages."
    evidence["graph_path"] = {"nodes": [], "edges": [], "highlighted_path_ids": []}
    return {"evidence": evidence}


def trace(state):
    return {"paths": trace_attack_paths(state["workspace_id"], state["entry_point"], 3)}


def review(state):
    evidence = state["evidence"]
    citations = evidence.get("source_chunks", [])
    return {"review": {"status": "review_required" if citations else "insufficient_evidence",
        "finding": "Review the cited evidence and opposing claims before deciding remediation." if citations else "Import matching evidence before drawing conclusions.",
        "execution_enabled": False,
        "limitations": "Deterministic evidence workflow. Scanner findings and connectivity do not prove exploitability. No commands or network scans are executed."}}


def create_workflow():
    workflow = StateGraph(InvestigationState)
    workflow.add_node("gather_evidence", gather)
    workflow.add_node("trace_paths", trace)
    workflow.add_node("prepare_review", review)
    workflow.add_edge(START, "gather_evidence")
    workflow.add_edge("gather_evidence", "trace_paths")
    workflow.add_edge("trace_paths", "prepare_review")
    workflow.add_edge("prepare_review", END)
    return workflow.compile()


_workflow = create_workflow()


def investigate(workspace_id, entry_point):
    state = _workflow.invoke({"workspace_id": workspace_id, "entry_point": entry_point})
    return {**state, "engine": "langgraph", "steps": ["gather_evidence", "trace_paths", "prepare_review"]}
