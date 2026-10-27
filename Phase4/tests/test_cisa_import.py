import copy
import json
import time
import pytest
from backend.ingestion.cisa_kev import normalize_catalog


def fixture_catalog():
    return {"catalogVersion": "fixture-v1", "dateReleased": "2026-10-27T00:00:00Z", "count": 1,
            "vulnerabilities": [{"cveID": "CVE-2024-4577", "vendorProject": "Fixture vendor",
            "product": "Fixture gateway", "vulnerabilityName": "Synthetic import test",
            "dateAdded": "2026-10-27", "shortDescription": "UNVERIFIED TEST: Gateway accesses Database.",
            "requiredAction": "TEST ONLY: review the fixture.", "dueDate": "2026-11-01"}]}


def test_normalization_is_deterministic_and_does_not_claim_publisher_authenticity():
    catalog = fixture_catalog()
    first = normalize_catalog(json.dumps(catalog).encode())
    second = normalize_catalog(json.dumps(catalog, indent=4, sort_keys=True).encode())
    assert first == second
    assert "authenticity have not been verified" in first["text"]
    assert catalog["vulnerabilities"][0]["shortDescription"] in first["text"]
    catalog["vulnerabilities"][0]["shortDescription"] += " Changed."
    assert normalize_catalog(json.dumps(catalog).encode())["document_id"] != first["document_id"]


@pytest.mark.parametrize("change", ["count", "duplicate", "date", "cve", "missing"])
def test_invalid_catalog_is_rejected_before_ingestion(change):
    catalog = fixture_catalog()
    if change == "count": catalog["count"] = 2
    if change == "duplicate":
        catalog["count"] = 2
        catalog["vulnerabilities"] *= 2
    if change == "date": catalog["vulnerabilities"][0]["dateAdded"] = "2026-02-31"
    if change == "cve": catalog["vulnerabilities"][0]["cveID"] = "../../unsafe"
    if change == "missing": del catalog["vulnerabilities"][0]["requiredAction"]
    with pytest.raises(ValueError): normalize_catalog(json.dumps(catalog).encode())


def test_catalog_endpoint_reuses_normal_operation_and_deduplicates(client):
    raw = json.dumps(fixture_catalog()).encode()
    for _ in range(2):
        receipt = client.post("/v1/workspaces/import-test/imports/cisa-kev",
                              files={"file": ("fixture.kev.json", raw, "application/json")})
        assert receipt.status_code == 202
        for attempt in range(100):
            operation = client.get(f"/v1/operations/{receipt.json()['operation_id']}").json()
            if operation["status"] in {"COMPLETED", "FAILED"}: break
            time.sleep(.01)
        assert operation["status"] == "COMPLETED"
    assert client.get("/v1/workspaces/import-test/documents").json()["total"] == 1
    from backend.storage.graph_store import get_graph_store
    graph = get_graph_store()
    assert not graph.relations.get("import-test", {})
    assert "CVE-2024-4577" in graph.entities.get("import-test", {})
    invalid = client.post("/v1/workspaces/import-test/imports/cisa-kev", files={"file": ("bad.json", b'{}')})
    assert invalid.status_code == 400


def test_upload_paths_are_unique_and_partitioned(client):
    from backend.app import upload_path
    first = upload_path("first", "same.txt")
    second = upload_path("second", "same.txt")
    third = upload_path("first", "same.txt")
    assert len({first, second, third}) == 3
    assert "first" in first and "second" in second


def test_discovery_replaces_previous_snapshot_instead_of_duplicating(client):
    client.post("/v1/workspaces/themes/demo/cyber")
    for _ in range(2):
        response = client.post("/v1/topics/discover?workspace_id=themes&k=2")
        assert response.status_code == 200
        assert response.json()["total"] == 2
        assert all("synthetic" not in t["label"].lower() for t in response.json()["topics"])
    assert client.post("/v1/topics/discover?workspace_id=themes&k=0").status_code == 422
