import pytest
from fastapi.testclient import TestClient
from backend.app import app

client = TestClient(app)

def test_batch_document_upload_and_listing():
    ws = "ws-batch-test"
    
    # Create 20 mock files for batch ingestion
    files = [
        ("files", (f"spec_doc_{i}.txt", f"Component {i} implements protocol {i % 5} in region {i % 3}. System status is active.".encode("utf-8"), "text/plain"))
        for i in range(20)
    ]
    
    # 1. Post batch
    res = client.post(f"/v1/workspaces/{ws}/documents/batch", files=files)
    assert res.status_code == 202
    data = res.json()
    assert data["status"] == "accepted"
    assert data["total_documents"] == 20
    assert len(data["operation_ids"]) == 20
    
    # 2. Check batch status
    status_res = client.get(f"/v1/workspaces/{ws}/operations/batch-status?operation_ids={','.join(data['operation_ids'])}")
    assert status_res.status_code == 200
    st_data = status_res.json()
    assert st_data["total"] == 20
    
    # 3. Wait for operations to process
    import time
    for _ in range(50):
        check = client.get(f"/v1/workspaces/{ws}/operations/batch-status?operation_ids={','.join(data['operation_ids'])}").json()
        if check["is_finished"]:
            break
        time.sleep(0.1)
        
    # 4. List workspace documents
    doc_res = client.get(f"/v1/workspaces/{ws}/documents")
    assert doc_res.status_code == 200
    docs_data = doc_res.json()
    assert docs_data["total"] >= 20
    assert any(d["source_name"] == "spec_doc_0.txt" for d in docs_data["documents"])
    
    # 5. Check workspace graph returns document nodes
    graph_res = client.get(f"/v1/workspaces/{ws}/graph")
    assert graph_res.status_code == 200
    g_data = graph_res.json()
    doc_nodes = [n for n in g_data["nodes"] if n["type"] == "document"]
    assert len(doc_nodes) >= 20


def test_500_plus_documents_bulk_ingestion():
    ws = "ws-500-test"
    count = 500

    files = [
        ("files", (f"policy_doc_{i}.txt", f"Policy {i} applies security protocol {i % 10} for cluster {i % 4}.".encode("utf-8"), "text/plain"))
        for i in range(count)
    ]

    import time
    start_t = time.time()
    res = client.post(f"/v1/workspaces/{ws}/documents/batch", files=files)
    assert res.status_code == 202
    data = res.json()
    assert data["total_documents"] == count

    # Wait for completion
    for _ in range(150):
        status = client.get(f"/v1/workspaces/{ws}/operations/batch-status?operation_ids={','.join(data['operation_ids'])}").json()
        if status["is_finished"]:
            break
        time.sleep(0.1)

    elapsed = time.time() - start_t
    assert elapsed < 15.0, f"500 documents took {elapsed:.2f}s, expected < 15s"

    # Verify all 500 documents are saved and listed
    docs_res = client.get(f"/v1/workspaces/{ws}/documents")
    assert docs_res.status_code == 200
    assert docs_res.json()["total"] == count

    # Verify graph slice has document nodes that stay
    graph_res = client.get(f"/v1/workspaces/{ws}/graph")
    assert graph_res.status_code == 200
    doc_nodes = [n for n in graph_res.json()["nodes"] if n["type"] == "document"]
    assert len(doc_nodes) == count
