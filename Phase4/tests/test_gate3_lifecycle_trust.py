"""Gate 3: Lifecycle and trust testing add/edit/delete SLA, shared evidence, conflicts, and Hindi queries."""

import time
from backend.storage.graph_store import get_graph_store


def test_gate3_lifecycle_and_trust(client):
    ws = "ws-gate3"
    store = get_graph_store()

    # 1. Ingest shared entity documents
    doc_a_text = (
        "Core Switch Network.\n"
        "CoreRouter connects to CentralSwitch.\n"
        "CentralSwitch routes packets for AlphaZone.\n"
    )
    doc_b_text = (
        "Branch Office Network.\n"
        "BranchRouter connects to CentralSwitch.\n"
        "CentralSwitch routes packets for BetaZone.\n"
    )

    resp_a = client.post(f"/v1/workspaces/{ws}/documents", data={"raw_text": doc_a_text, "filename": "doc_a.txt"})
    resp_b = client.post(f"/v1/workspaces/{ws}/documents", data={"raw_text": doc_b_text, "filename": "doc_b.txt"})
    op_a_id = resp_a.json()["operation_id"]
    op_b_id = resp_b.json()["operation_id"]
    doc_a_id = resp_a.json()["document_id"]
    doc_b_id = resp_b.json()["document_id"]

    for _ in range(50):
        time.sleep(0.05)
        st_a = client.get(f"/v1/operations/{op_a_id}").json()["status"]
        st_b = client.get(f"/v1/operations/{op_b_id}").json()["status"]
        if st_a == "COMPLETED" and st_b == "COMPLETED":
            break

    # Verify CentralSwitch entity exists and has 2 document references
    assert "CentralSwitch" in store.entities[ws]
    assert len(store.entity_doc_refs[ws]["CentralSwitch"]) == 2

    # 2. Delete Document A and verify shared entity CentralSwitch remains supported by Document B
    del_resp = client.delete(f"/v1/workspaces/{ws}/documents/{doc_a_id}")
    assert del_resp.status_code == 202
    del_op_id = del_resp.json()["operation_id"]
    for _ in range(50):
        time.sleep(0.05)
        if client.get(f"/v1/operations/{del_op_id}").json()["status"] == "COMPLETED":
            break

    # Verify visibility: Document A removed, but CentralSwitch preserved
    assert doc_a_id not in store.documents[ws]
    assert "CentralSwitch" in store.entities[ws]
    assert "BranchRouter" in store.entities[ws]
    assert "CoreRouter" not in store.entities[ws]

    # 3. Test planted contradiction: both sides presented
    conf_doc_1 = (
        "Audit Policy A.\n"
        "Database port 5432 is publicly accessible for external analytics.\n"
    )
    conf_doc_2 = (
        "Audit Policy B.\n"
        "Database port 5432 is strictly private and blocked by the firewall.\n"
    )

    r_c1 = client.post(f"/v1/workspaces/{ws}/documents", data={"raw_text": conf_doc_1, "filename": "conf_1.txt"})
    r_c2 = client.post(f"/v1/workspaces/{ws}/documents", data={"raw_text": conf_doc_2, "filename": "conf_2.txt"})
    for _ in range(50):
        time.sleep(0.05)
        st1 = client.get(f"/v1/operations/{r_c1.json()['operation_id']}").json()["status"]
        st2 = client.get(f"/v1/operations/{r_c2.json()['operation_id']}").json()["status"]
        if st1 == "COMPLETED" and st2 == "COMPLETED":
            break


    q_conf = client.post(
        "/v1/query",
        json={"workspace_id": ws, "query": "Is database port 5432 public or private?"},
    )
    assert q_conf.status_code == 200
    conf_data = q_conf.json()
    assert conf_data["conflict_detected"] is True
    assert len(conf_data["conflicts"]) > 0

    # 4. Hindi query over English documents
    q_hindi = client.post(
        "/v1/query",
        json={"workspace_id": ws, "query": "डेटाबेस पोर्ट 5432 की स्थिति क्या है?"},
    )
    assert q_hindi.status_code == 200
    hindi_data = q_hindi.json()
    # Response must be Hindi text
    assert any(ord(c) >= 0x0900 and ord(c) <= 0x097F for c in hindi_data["answer"])
    # Sources must still point to original English documents/chunks
    assert len(hindi_data["source_chunks"]) > 0
    assert "conf_" in hindi_data["source_chunks"][0]["source_name"]

    # 5. Stale revision rejection on PUT
    stale_edit = client.put(
        f"/v1/workspaces/{ws}/documents/{doc_b_id}",
        data={"expected_revision_id": 99, "raw_text": "Illegal stale update"},
    )
    assert stale_edit.status_code == 409
    assert "Stale revision" in stale_edit.json()["message"]
