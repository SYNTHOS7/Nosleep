# Security-tool integrations

## Product features

Upload one report through the Corpus panel:

| Format | Filename | Imported data |
| --- | --- | --- |
| Trivy vulnerability JSON | trivy.json or *.trivy.json | Artifact, package/version, vulnerability ID, reported severity and fix version |
| OSV-Scanner JSON | osv.json or *.osv.json | Source lockfile, package/version and vulnerability ID |
| SARIF 2.1.0 | *.sarif or *.sarif.json | Located rule findings from tools such as Semgrep and CodeQL |

The API is POST /v1/workspaces/{ws}/imports/scanner?format=trivy, osv or sarif, with a multipart file. Reports are limited to 5 MiB and 2000 findings. Empty reports are rejected as unsupported imports, not certified as clean scans. Equivalent selected fields deduplicate. Changed reports are separate snapshots.

Only selected fields are retained. Raw source snippets, Trivy Secrets, network requests/responses and arbitrary report properties are omitted. Secret-scanner SARIF is rejected. This is not a general-purpose secret sanitizer: review reports before uploading; descriptions and artifact names remain source data. Quotes and offsets reference the normalized imported snapshot, not the original JSON byte positions. The importer never fetches report links or launches scanners.

Graph links are REPORTS_FINDING and REPORTS_PACKAGE. They are observations and are excluded from affirmative exploit-path traversal. An artifact path is not automatically mapped to an enterprise host. Severity remains the scanner's reported value, not an independently verified risk assessment.

## Investigation workflow

LangGraph 1.2.18 is an installed backend dependency. The Reasoner panel's Investigate control and GET /v1/workspaces/{ws}/investigation?entry_point=... run gather_evidence, trace_paths and prepare_review. Matching source passages must explicitly name the entered CVE/entity. Existing workspace permissions apply; viewers may investigate, while report ingestion requires editor/admin access.

The fifth MCP tool, sec_investigate, calls the same read-only API. There is no model key requirement. The workflow is deterministic, per request, and does not have durable conversational memory, autonomous scanning, executable remediation or an approval-to-execution handler.

## Repository checks

.github/workflows/security.yml configures pinned GitHub Actions for:

- Semgrep 1.182.1 with local Python/React security rules; metrics are disabled.
- Gitleaks 8.30.1 CLI scanning full Git history with redaction.
- CodeQL Python and JavaScript/TypeScript analysis. GitHub code-scanning eligibility and repository settings still apply.

The checks run on main pushes, pull requests and manual dispatch. Only the CodeQL job requests security-events write permission. Reports have seven-day artifact retention. Dependabot is configured for GitHub Actions, frontend npm dependencies and root Python requirements. None of these settings establishes that a CI run has passed.

Local evidence: a checksummed official Gitleaks executable scanned all committed history and found no leaks. Semgrep installed, but its Windows core failed with an Invalid argument socketpair error before analysis, including on a single-worker retry. Semgrep's scan is therefore unverified locally; check the Linux CI result after push. CodeQL was configured, not executed locally.

## Upstream projects and remaining integrations

- [LangGraph](https://github.com/langchain-ai/langgraph): actual workflow dependency.
- [Trivy](https://github.com/aquasecurity/trivy), [OSV-Scanner](https://github.com/google/osv-scanner): report interoperability; scanner binaries are not bundled into the product.
- [Semgrep](https://github.com/semgrep/semgrep), [CodeQL](https://github.com/github/codeql): SARIF interoperability and repository checks.
- [Gitleaks](https://github.com/gitleaks/gitleaks): local/CI secret detection; secret findings are not ingested into the product.
- [ZAP](https://github.com/zaproxy/zaproxy): future localhost web/API security testing. Not installed or run here.
- [Nuclei](https://github.com/projectdiscovery/nuclei): future checks against explicitly authorized assets. Not installed or run here.

Use each upstream tool under its published license. This repository contains adapters and references, not copied scanner engines. Optional real local AI extraction and embeddings are now implemented; see LOCAL_AI.md. Live database verification, hosted model serving, authorized active scanning and direct Neo4j traversal remain separate work.

## Updating diagrams

Edit docs/architecture.json, then run python scripts/generate_architecture.py. It generates CYBERSECURITY_SYSTEM_FLOWCHARTS.md, the root architecture document and flowcharts.html. The HTML contains six offline SVG diagrams and no external scripts/fonts. Open /architecture on the running backend, or open flowcharts.html directly. Phase-specific architecture copies are labeled historical.
