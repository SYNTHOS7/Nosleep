"""Offline scanner contracts and the actual installed LangGraph engine."""
import json
import time
import pytest

from backend.ingestion.scanner_reports import normalize_report
from backend.storage.graph_store import get_graph_store
from backend.services.attack_path_service import trace_attack_paths


def reports():
    return {
        "trivy": {"Results": [{"Target": "fixture/package-lock.json", "Vulnerabilities": [
            {"VulnerabilityID": "CVE-2024-4577", "PkgName": "fixture-lib", "InstalledVersion": "1.0",
             "FixedVersion": "2.0", "Severity": "HIGH", "Title": "Synthetic fixture finding"}],
             "Secrets": [{"Match": "DO-NOT-RETAIN-THIS-SECRET"}]}]},
        "osv": {"results": [{"source": {"path": "fixture/requirements.txt"}, "packages": [{
            "package": {"name": "fixture-lib", "version": "1.0", "ecosystem": "PyPI"},
            "vulnerabilities": [{"id": "GHSA-fixture-test", "aliases": ["CVE-2024-4577", "CVE-2025-99999"], "summary": "Synthetic fixture finding"}]}]}]},
        "sarif": {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "Semgrep"}}, "results": [{
            "ruleId": "fixture-rule", "message": {"text": "Synthetic fixture finding"}, "level": "warning",
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": "fixture/app.py"},
                            "region": {"startLine": 12}, "snippet": {"text": "DO-NOT-RETAIN-THIS-SOURCE"}}}]}]}]}
    }


@pytest.mark.parametrize("format_name", ["trivy", "osv", "sarif"])
def test_report_normalization_is_stable_and_omits_unselected_fields(format_name):
    source = reports()[format_name]
    first = normalize_report(json.dumps(source).encode(), format_name)
    second = normalize_report(json.dumps(source, indent=4).encode(), format_name)
    assert first == second and first["count"] == 1
    assert "DO-NOT-RETAIN" not in first["text"]
    assert "unverified" in first["text"]


@pytest.mark.parametrize("format_name", ["trivy", "osv", "sarif"])
def test_scanner_endpoint_has_exact_quotes_and_no_inferred_exploit_paths(client, format_name):
    workspace = f"scan-{format_name}"
    raw = json.dumps(reports()[format_name]).encode()
    for repeat in range(2):
        response = client.post(f"/v1/workspaces/{workspace}/imports/scanner?format={format_name}",
                               files={"file": ("report.json", raw, "application/json")})
        assert response.status_code == 202
        for _ in range(200):
            operation = client.get(f"/v1/operations/{response.json()['operation_id']}").json()
            if operation["status"] in {"COMPLETED", "FAILED"}: break
            time.sleep(.01)
        assert operation["status"] == "COMPLETED"
    store = get_graph_store()
    assert len(store.documents[workspace]) == 1
    assert store.relations[workspace]
    if format_name == "osv":
        assert "CVE-2024-4577" in store.entities[workspace]
        assert "package:PyPI:fixture-lib@1.0" in store.entities[workspace]
        assert len([r for r in store.relations[workspace].values() if r.predicate == "REPORTED_ALIAS"]) == 2
    for relation in store.relations[workspace].values():
        provenance = relation.provenance
        chunk = store.chunks[workspace][provenance.source_chunk_id]
        assert chunk.text[provenance.char_start:provenance.char_end] == provenance.exact_quote
        assert not trace_attack_paths(workspace, relation.source_entity_name, 3)["paths"]
    assert not store.documents.get("unrelated", {})


def test_secret_reports_and_empty_or_malformed_reports_fail_closed(client):
    source = reports()["sarif"]
    source["runs"][0]["tool"]["driver"]["name"] = "Gitleaks"
    response = client.post("/v1/workspaces/test/imports/scanner?format=sarif",
                           files={"file": ("report.sarif", json.dumps(source).encode())})
    assert response.status_code == 400
    for format_name in ("trivy", "osv", "sarif"):
        assert client.post(f"/v1/workspaces/test/imports/scanner?format={format_name}",
                           files={"file": ("bad.json", b'{}')}).status_code == 400


def test_report_urls_do_not_keep_credentials_or_query_tokens():
    source = reports()["trivy"]
    source["Results"][0]["Target"] = "https://name:PRIVATE_PASSWORD_VALUE@example.invalid/path?token=HIDDEN_TOKEN_VALUE#fragment"
    normalized = normalize_report(json.dumps(source).encode(), "trivy")
    assert "PRIVATE_PASSWORD_VALUE" not in normalized["text"] and "HIDDEN_TOKEN_VALUE" not in normalized["text"]


def test_real_langgraph_workflow_returns_evidence_and_review_only(client):
    client.post("/v1/workspaces/investigate/demo/cyber")
    receipt = client.post("/v1/workspaces/investigate/imports/scanner?format=trivy",
                          files={"file": ("trivy.json", json.dumps(reports()['trivy']).encode())}).json()
    for _ in range(200):
        operation = client.get(f"/v1/operations/{receipt['operation_id']}").json()
        if operation['status'] in {'COMPLETED', 'FAILED'}: break
        time.sleep(.01)
    assert operation['status'] == 'COMPLETED'
    response = client.get("/v1/workspaces/investigate/investigation?entry_point=CVE-2024-4577")
    assert response.status_code == 200
    result = response.json()
    assert result["engine"] == "langgraph"
    assert result["steps"] == ["gather_evidence", "trace_paths", "prepare_review"]
    assert result["evidence"]["source_chunks"] and result["paths"]["paths"]
    assert result["review"]["execution_enabled"] is False
    assert all('cve-2024-4577' in source['exact_quote'].lower() for source in result['evidence']['source_chunks'])
    assert any(source['source_name'] == 'scanner-trivy.txt' for source in result['evidence']['source_chunks'])
    missing = client.get("/v1/workspaces/unrelated/investigation?entry_point=CVE-2024-4577").json()
    assert missing["review"]["status"] == "insufficient_evidence"
    assert client.get("/v1/workspaces/investigate/investigation?entry_point=%20").status_code == 400


def test_investigation_and_import_enforce_workspace_roles(client, monkeypatch):
    import backend.security.access as access
    monkeypatch.setenv("AUTH_MODE", "neon")
    monkeypatch.setattr(access, "verify_identity", lambda token: {"uid": "viewer"})
    monkeypatch.setattr(access, "load_memberships", lambda uid: {"workspaces": {"allowed": "viewer"}})
    headers = {"Authorization": "Bearer test"}
    assert client.get("/v1/workspaces/allowed/investigation?entry_point=CVE-2024-4577", headers=headers).status_code == 200
    assert client.get("/v1/workspaces/forbidden/investigation?entry_point=CVE-2024-4577", headers=headers).status_code == 403
    assert client.post("/v1/workspaces/allowed/imports/scanner?format=trivy", headers=headers,
                       files={"file": ("report.json", json.dumps(reports()["trivy"]).encode())}).status_code == 403


def test_architecture_view_is_offline_and_specification_links_are_valid(client):
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    spec = json.loads((root / 'docs/architecture.json').read_text(encoding='utf-8'))
    for diagram in spec['diagrams']:
        node_ids = {node['id'] for node in diagram['nodes']}
        assert len(node_ids) == len(diagram['nodes'])
        assert all(source in node_ids and target in node_ids for source, target in diagram['edges'])
    response = client.get('/architecture')
    assert response.status_code == 200
    assert response.text.count('<svg ') == len(spec['diagrams'])
    assert '<script' not in response.text and 'fonts.googleapis.com' not in response.text
