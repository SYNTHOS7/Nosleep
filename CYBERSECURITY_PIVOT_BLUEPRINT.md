# AegisGraph product blueprint — current implementation

AegisGraph helps analysts inspect source evidence, opposing security claims, scanner observations and potential attack routes in one workspace. Findings and connectivity alone do not establish exploitability.

## Implemented

- React workspace with document library, themes, cited answers and graph views.
- FastAPI workspace authorization, upload bounds, request limits and metadata-only audit history.
- Local SQLite or Neon extraction/vector persistence; topic restoration and disk-backed job recovery.
- Offline CISA KEV-shaped catalog import with unverified publisher identity.
- Trivy vulnerability JSON, OSV JSON and located SARIF 2.1.0 report imports. CodeQL and Semgrep reports use SARIF. Imported observations retain exact normalized-source quotes and do not become affirmative exploit routes.
- LangGraph deterministic investigation: gather evidence and conflicts, trace potential routes, prepare analyst review. No AI model, active scanner or remediation execution is attached.
- Optional Neo4j graph projection; queries still traverse the embedded graph.
- Repository security workflows for CodeQL, Semgrep and redacted Gitleaks checks. CI results require verification after push. Gitleaks ran locally; Semgrep's Windows socket error blocked its local scan.

## Demonstration

Start ./start_local.ps1 and load the synthetic cyber demo. Ask for the CVE blast radius and inspect the quoted route evidence. Import one trivy.json, osv.json or *.sarif report, then inspect its artifact/package/finding links. Enter a CVE or entity and choose Investigate to review evidence, contradictions and potential routes. Imported data stays passive.

## Remaining

Connect and verify Vercel, Render, Neon Auth/database and optional Neo4j. Add actual model providers and learned embeddings, direct Neo4j-backed traversal, hosted upload/checkpoint object storage and multi-instance synchronization. ZAP localhost security testing and Nuclei checks against authorized assets are future integrations. No automatic remediation is available.

## Canonical diagrams

CYBERSECURITY_SYSTEM_FLOWCHARTS.md and flowcharts.html are generated from docs/architecture.json by scripts/generate_architecture.py. Update the specification first, then regenerate both outputs. The HTML viewer works offline at /architecture.
