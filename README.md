# AegisGraph AI

Cyber threat intelligence, cited graph exploration, and potential attack-path
analysis over uploaded documents. Built with FastAPI and React/Vite.

## What works

- Upload PDF/TXT documents, edit revisions, delete documents, and inspect sources.
- Search a workspace and scope questions to discovered topics.
- Extract explicit cyber assertions into Vulnerability, ThreatActor, Asset,
  Technique and AttackPayload nodes with source quotes.
- Trace directed potential attack routes with a document ID, chunk ID, exact quote
  and path ID supporting every hop. Negated, uncertain, conditional and disputed
  links do not become affirmative attack routes.
- Display opposing claims together with their original evidence.
- Load a six-document synthetic cyber demo from the UI.
- Preserve attacker instructions as passive data artifacts.
- Connect MCP clients to the same API used by the browser.
- Optionally persist extraction batches and embeddings in Neon PostgreSQL and
  reconstruct the graph/search cache after restart.

## Storage and hosting

The frontend is ready for Vercel and the API for Render; you choose when to deploy.
Neon configuration is optional for local development. No cloud credentials or
account-specific Neon project IDs are committed.

| Component | Current implementation |
| --- | --- |
| Frontend | React/Vite, in Phase4/frontend |
| API | FastAPI, started with run_app.py |
| Durable hosted data | Neon PostgreSQL when VECTOR_BACKEND=neon |
| Search | 768-dimensional pgvector cosine search in PostgreSQL |
| Active graph | Embedded graph reconstructed from persisted extraction batches |
| Neo4j | Optional evidence graph projection; application traversal stays embedded |
| Local mode | In-memory graph and vectors; existing Chroma compatibility retained |

Supabase is not needed. Neon mode disables Chroma. The current extraction and
embedding adapters are deterministic; this release does not claim external LLM
reasoning or learned semantic embeddings. Use one API instance for the shared
in-memory index. Neon mode uses native pgvector cosine queries.

Read **[the setup guide](docs/HOSTED_SETUP.md)** for environment variables,
Neon schema setup, Vercel routing, Render settings, MCP setup and remaining boundaries.

## Run locally

For real local extraction and semantic embeddings, run `./start_local_ai.ps1`.
It uses installed Ollama models, a separate database and port 8004. See
[local AI setup and boundaries](docs/LOCAL_AI.md). NVD and STIX file imports are also supported.


On Windows, `./start_local.ps1` starts the complete app at http://localhost:8000
with SQLite persistence and no cloud connections. Completed documents, source
evidence and vectors survive restarts. This is a local demo with no login;
themes, audit history and saved jobs also recover on restart. The local database stays out of Git.
For other shells, set `VECTOR_BACKEND=local`, `AUTH_MODE=demo`, and run the API.

Python 3.11+:

```bash
pip install -r requirements.txt
python run_app.py
```

Open http://localhost:8080 and http://localhost:8080/docs.
The checked-in production UI is served automatically. Offline storage is the default.
The application reads environment variables; .env.example is a reference, not an
automatically loaded secrets file.

For frontend development:

```bash
cd Phase4/frontend
npm ci
npm run dev
```

Vite proxies to port 8000 by default. Start the API with `python run_app.py --port 8000`
or configure VITE_API_BASE_URL for the port you choose.

## Cyber demo

Click **Load synthetic cyber demo** in the Reasoner panel, then try:

- What is the blast radius of CVE-2024-4577?
- Trace the attack path from Legacy_PHP_Gateway
- Are there conflicting mitigation claims for CVE-2024-4577?
- What prompt injection appears in the malicious log?

The corpus uses a real CVE identifier with a fictional actor, enterprise topology
and patch dispute. It is demonstration data, not real vendor guidance or threat
attribution. A connectivity route does not prove that exploitation is possible.

## MCP tools

```bash
cd Phase4
python -m backend.mcp_server
```

Set AEGISGRAPH_API_URL to your API URL (default http://localhost:8000).
The stdio server exposes sec_trace_attack_path, sec_query_threat_intel,
sec_find_conflicts, sec_ingest_advisory and sec_investigate. Advisory ingestion returns an operation
receipt; check that operation before assuming the document is ready.

Investigation results can be downloaded as text or JSON with exact citations and
workspace revision checks. See [report exports](docs/REPORT_EXPORTS.md).

## Main API routes

| Method | Route | Purpose |
| --- | --- | --- |
| GET | /health | Component readiness and active vector backend |
| GET | /v1/database/status | Storage configuration/status |
| POST | /v1/workspaces/{ws}/documents | Upload TXT/PDF or pasted text |
| POST | /v1/workspaces/{ws}/documents/batch | Batch upload |
| GET | /v1/workspaces/{ws}/documents | List documents |
| PUT / DELETE | /v1/workspaces/{ws}/documents/{id} | Edit/delete |
| GET | /v1/operations/{id} | Inspect operation completion |
| POST | /v1/query | Query evidence and attack paths |
| GET | /v1/workspaces/{ws}/graph | Graph slice |
| GET | /v1/workspaces/{ws}/attack-paths | Directed routes, bounded depth |
| POST | /v1/workspaces/{ws}/demo/cyber | Load synthetic fixtures |
| GET | /v1/topics | List topics |
| POST | /v1/topics/discover | Discover topics |

## Tests

```bash
python test_all_phases.py
```

The runner covers all four phases, including cyber paths, topic isolation,
Neon publication/recovery/edit/delete/integrity behavior, and MCP routing.
Neon tests use a test double; live Neon needs verification after you
connect a project. The Neo4j live test is optional without credentials.

## Current boundaries

Neon login, live workspace roles and protected administration are now
implemented. See [authentication setup](docs/AUTHENTICATION.md). Local offline
runs explicitly display demo mode; Neon/hosted modes require verified tokens.

Configure Neon Auth and server-managed memberships before enabling
private hosted use. Original upload retention, audit trails and rate limits remain
future work. Build the frontend with Node 20.19+ or 22.12+.

Completed extraction batches and evidence survive Neon-backed restarts.
Discovered topics and request audit records persist in SQLite/Neon. Upload files
and operation checkpoints use local folders, so hosted recovery still needs a
persistent disk or object storage. Interrupted jobs resume when their checkpoints
and source files remain available.

## Offline intelligence import and optional graph projection

Scanner imports now accept Trivy, OSV and SARIF reports; the Reasoner includes a
LangGraph investigation control. See [integration details](docs/INTEGRATIONS.md)
for supported fields, security checks and verification boundaries. The current
[offline flowcharts](flowcharts.html) are also available at /architecture.

Upload one saved `known_exploited_vulnerabilities.json` or `*.kev.json` file in
the Corpus panel to import a CISA KEV-shaped snapshot. Required fields, dates,
record count and unique CVE IDs are validated. Equivalent imports deduplicate;
changed catalogs become separate snapshots. Quotes reference the normalized
imported text; the original JSON is retained on local disk. Uploaded publisher
identity is unverified. No links in uploaded data are fetched or executed.

Optional Neo4j projection: configure NEO4J_* variables and set
NEO4J_PROJECTION_ENABLED=true with durable local/Neon storage. Document changes,
theme discovery and startup rebuild a scoped AegisManaged graph copy in Neo4j.
Neon/SQLite remains authoritative and queries still use the embedded graph.
Live Neo4j transactions require verification when you connect your account.

## Project references

- [Agent context and architecture](AGENTS_CYBERSECURITY_CONTEXT.md)
- [Historical hackathon blueprint](CYBERSECURITY_PIVOT_BLUEPRINT.md)
- [Architecture flowcharts](CYBERSECURITY_SYSTEM_FLOWCHARTS.md)
- [Standalone flowchart viewer](flowcharts.html)

The older blueprint/flowcharts contain planned features; the setup guide and
implementation notes above describe the current code.
