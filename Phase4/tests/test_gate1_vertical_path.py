"""Gate 1: Vertical Phase 1 path testing upload, operation inspection, graph highlighting, and deduplication."""

import time
import io
import pypdf
from backend.storage.graph_store import get_graph_store


def create_dummy_pdf_bytes(text: str) -> bytes:
    """Helper creating valid PDF bytes in memory."""
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    stream = io.BytesIO()
    writer.write(stream)
    # Return minimal valid PDF bytes
    return stream.getvalue()


def test_gate1_vertical_path(client):
    ws = "ws-gate1"

    # 1. Upload TXT file via API
    txt_content = (
        "Core Network Router Architecture.\n"
        "CoreRouter connects to CoreSwitch.\n"
        "CoreSwitch routes packets to GatewayServer.\n"
    )
    resp_txt = client.post(
        f"/v1/workspaces/{ws}/documents",
        data={"raw_text": txt_content, "filename": "core_network.txt"},
    )
    assert resp_txt.status_code == 202
    txt_receipt = resp_txt.json()
    assert txt_receipt["status"] == "accepted"
    txt_op_id = txt_receipt["operation_id"]
    txt_doc_id = txt_receipt["document_id"]

    # Poll operation view until completed
    for _ in range(50):
        time.sleep(0.05)
        op_resp = client.get(f"/v1/operations/{txt_op_id}")
        assert op_resp.status_code == 200
        op_data = op_resp.json()
        if op_data["status"] == "COMPLETED":
            break
    assert op_data["status"] == "COMPLETED"
    assert op_data["ready_at"] is not None

    # Inspect graph store for chunks, entities, relations
    store = get_graph_store()
    assert len(store.chunks[ws]) > 0
    assert len(store.entities[ws]) > 0
    assert len(store.relations[ws]) > 0

    # 2. Ask a direct question
    query_resp = client.post(
        "/v1/query",
        json={"workspace_id": ws, "query": "What does CoreRouter connect to?"},
    )
    assert query_resp.status_code == 200
    q_data = query_resp.json()

    assert "CoreSwitch" in q_data["answer"] or "connects" in q_data["answer"]
    assert len(q_data["source_chunks"]) > 0
    assert q_data["source_chunks"][0]["document_id"] == txt_doc_id

    # Verify graph slice highlights the path
    graph_slice = q_data["graph_path"]
    assert len(graph_slice["nodes"]) > 0
    assert len(graph_slice["edges"]) > 0
    assert len(graph_slice["highlighted_path_ids"]) > 0

    # 3. Repeat same upload and verify idempotency (no duplicate documents or chunks)
    resp_repeat = client.post(
        f"/v1/workspaces/{ws}/documents",
        data={"raw_text": txt_content, "filename": "core_network_dup.txt"},
    )
    assert resp_repeat.status_code == 202
    repeat_receipt = resp_repeat.json()

    for _ in range(50):
        time.sleep(0.05)
        op_resp = client.get(f"/v1/operations/{repeat_receipt['operation_id']}")
        if op_resp.json()["status"] == "COMPLETED":
            break

    # Verify document count is 1 (idempotent deduplication)
    assert len(store.documents[ws]) == 1
