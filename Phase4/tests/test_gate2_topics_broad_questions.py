"""Gate 2: Topics and broad questions testing discovery, thematic queries, and multi-hop retrieval."""

import time
from backend.services.topic_service import get_topic_service


def test_gate2_topics_and_broad_questions(client):
    ws = "ws-gate2"

    # Ingest a small mixed corpus across two themes: Security and Payments
    sec_doc = (
        "Security Firewall Specification.\n"
        "FirewallCluster enforces perimeter defense on port 443.\n"
        "SecurityGuard monitors intrusion detection events.\n"
    )
    pay_doc = (
        "Payment Processing Architecture.\n"
        "BillingEngine handles credit card settlement on port 8443.\n"
        "PaymentGateway routes transactions to BankClearingHouse.\n"
    )

    r1 = client.post(f"/v1/workspaces/{ws}/documents", data={"raw_text": sec_doc, "filename": "security.txt"})
    r2 = client.post(f"/v1/workspaces/{ws}/documents", data={"raw_text": pay_doc, "filename": "payments.txt"})

    for _ in range(50):
        time.sleep(0.05)
        st1 = client.get(f"/v1/operations/{r1.json()['operation_id']}").json()["status"]
        st2 = client.get(f"/v1/operations/{r2.json()['operation_id']}").json()["status"]
        if st1 == "COMPLETED" and st2 == "COMPLETED":
            break


    # Discover and freeze topics
    topic_service = get_topic_service()
    topics = topic_service.discover_and_freeze_topics(ws, k_clusters=2)
    assert len(topics) >= 1

    # Check topic list route
    top_list_resp = client.get(f"/v1/topics?workspace_id={ws}")
    assert top_list_resp.status_code == 200
    top_data = top_list_resp.json()
    assert top_data["total"] >= 1

    # Ask a thematic question
    theme_q = client.post(
        "/v1/query",
        json={"workspace_id": ws, "query": "What are the core capabilities of BillingEngine in payments?"},
    )
    assert theme_q.status_code == 200
    theme_data = theme_q.json()
    assert "BillingEngine" in theme_data["answer"] or "PaymentGateway" in theme_data["answer"]
    assert len(theme_data["source_chunks"]) > 0

    # Ask a scoped question restricting topic
    target_topic_id = topics[0].id
    scoped_q = client.post(
        "/v1/query",
        json={
            "workspace_id": ws,
            "query": "What is the network port configuration?",
            "topic_ids": [target_topic_id],
        },
    )
    assert scoped_q.status_code == 200
    scoped_data = scoped_q.json()
    assert target_topic_id in scoped_data["topic_scope_used"]
