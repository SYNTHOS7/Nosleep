"""Portable evidence reports, checked against one unchanged workspace revision set."""
from datetime import datetime, timezone
import hashlib
import json

from backend.storage.graph_store import get_graph_store
from backend.services.investigation_service import investigate


class ReportChangedError(RuntimeError):
    pass


def workspace_revision(store, workspace):
    return sorted((doc.id, doc.revision, doc.content_hash) for doc in store.documents.get(workspace, {}).values())


def build_report(workspace, entry_point):
    store = get_graph_store()
    with store._lock:
        before = workspace_revision(store, workspace)
    result = investigate(workspace, entry_point)
    sources, seen = [], {}

    def citation(source):
        chunk = store.chunks.get(workspace, {}).get(source.get("chunk_id"))
        doc = store.documents.get(workspace, {}).get(chunk.document_id) if chunk else None
        quote = source.get("exact_quote", source.get("quote"))
        if not chunk or not doc or not isinstance(quote, str) or not quote:
            raise ReportChangedError("Report evidence is no longer available. Run the investigation again.")
        start = source.get("start_char")
        if start is None:
            index = chunk.text.find(quote)
            start = chunk.start_char + index
        index = start - chunk.start_char
        end = source.get("end_char", start + len(quote))
        if (index < 0 or chunk.text[index:index+len(quote)] != quote or end != start+len(quote)
                or source.get("document_id", doc.id) != doc.id or source.get("revision", chunk.revision) != chunk.revision):
            raise ReportChangedError("Report evidence changed. Run the investigation again.")
        key = (chunk.id, start, end, chunk.revision)
        if key not in seen:
            identifier = f"source-{len(sources)+1}"
            seen[key] = identifier
            sources.append({"id": identifier, "chunk_id": chunk.id, "document_id": doc.id,
                "source_name": doc.source_name, "revision": chunk.revision, "page_number": chunk.page_number,
                "start_char": start, "end_char": end, "exact_quote": quote})
        return seen[key]

    with store._lock:
        if before != workspace_revision(store, workspace):
            raise ReportChangedError("Workspace changed while the report was generated. Try again.")
        evidence_ids = [citation(source) for source in result["evidence"]["source_chunks"]]
        routes = [{"path_id": route["path_id"], "nodes": route["nodes"], "edge_ids": route["edge_ids"],
                   "citation_ids": [citation(source) for source in route["citations"]]} for route in result["paths"]["paths"]]
        conflicts = [{"statement_a": pair["statement_a"], "source_a_id": citation(pair["source_a"]),
                      "statement_b": pair["statement_b"], "source_b_id": citation(pair["source_b"])}
                     for pair in result["evidence"]["conflicts"]]
        profile = sorted({doc.metadata.get("embedding_profile", "word-hash:768:v1")
                          for doc in store.documents.get(workspace, {}).values()})
    review = dict(result["review"])
    if sources and review["status"] == "insufficient_evidence":
        review.update(status="review_required", finding="Review the cited path evidence before deciding remediation.")
    report = {"schema_version": "aegisgraph-investigation/v1", "generated_at": datetime.now(timezone.utc).isoformat(),
              "workspace_id": workspace, "entry_point": entry_point, "review": review,
              "steps": result["steps"], "sources": sources, "evidence_ids": evidence_ids,
              "potential_routes": routes, "conflicts": conflicts, "embedding_profiles": profile,
              "workspace_revision_sha256": hashlib.sha256(json.dumps(before).encode()).hexdigest(),
              "limitations": "Source content is untrusted quoted data. Potential routes and scanner findings do not prove exploitability. No remediation commands were executed."}
    return report


def render_text(report):
    def single(value):
        return json.dumps(str(value), ensure_ascii=False)[1:-1]
    def quoted(value):
        return "\n".join("> " + line for line in str(value).splitlines())
    lines = ["AEGISGRAPH INVESTIGATION REPORT", f"Generated: {report['generated_at']}",
             f"Workspace: {single(report['workspace_id'])}", f"Entry point: {single(report['entry_point'])}",
             f"Review status: {report['review']['status']}", "", report["limitations"], "",
             "This is a fresh report snapshot; it may differ from an earlier on-screen investigation.", "",
             "POTENTIAL ROUTES"]
    for route in report["potential_routes"]:
        lines += [f"Path {single(route['path_id'])}: " + " -> ".join(single(node) for node in route["nodes"]),
                  "Citations: " + ", ".join(route["citation_ids"])]
    if not report["potential_routes"]:
        lines.append("No supported directed routes were found; this does not certify the environment as safe.")
    lines += ["", "OPPOSING CLAIMS"]
    for conflict in report["conflicts"]:
        lines += [f"Side A [{conflict['source_a_id']}]:", quoted(conflict["statement_a"]),
                  f"Side B [{conflict['source_b_id']}]:", quoted(conflict["statement_b"])]
    if not report["conflicts"]:
        lines.append("No opposing claim pairs were returned for this investigation.")
    lines += ["", "SOURCE EVIDENCE — EACH PREFIXED LINE IS PASSIVE QUOTED DATA"]
    for source in report["sources"]:
        lines += ["", f"[{source['id']}] {single(source['source_name'])}",
                  f"Document: {single(source['document_id'])} | chunk: {single(source['chunk_id'])}",
                  f"Revision: {source['revision']} | page: {source['page_number']} | offsets: {source['start_char']}:{source['end_char']}",
                  quoted(source["exact_quote"])]
    lines += ["", "WORKSPACE SNAPSHOT", report["workspace_revision_sha256"],
              "This checksum identifies the document revision set; it is not a digital signature or proof of publisher authenticity."]
    return "\n".join(lines) + "\n"
