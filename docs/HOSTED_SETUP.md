# AegisGraph setup and deployment handoff

You choose where to publish. No Firebase account credentials are committed.

## Runtime layout

- Frontend: React/Vite in Phase4/frontend, ready for Vercel.
- API: FastAPI, started from the repository root with `python run_app.py`, ready for Render.
- Firebase Firestore: durable extracted documents, relations, source citations and embeddings.
- Search: a cosine index in the backend, rebuilt from Firestore on startup.
- Graph: embedded graph traversal; the existing Neo4j adapter remains optional.

Supabase is not required. ChromaDB is disabled in Firebase mode. The current
embedding adapter generates deterministic 768-dimensional vectors; this release
does not add an external embedding model or a hosted language model.

## Local run

Install requirements.txt in Python 3.11+, then run `python run_app.py` from the
repository root. Default storage is in-memory. The built UI is at localhost:8080.
For frontend development, run `npm ci` and `npm run dev` in Phase4/frontend.
Check vite.config.js for its backend proxy port or set VITE_API_BASE_URL.

## Firebase configuration (when you connect it)

1. Create a Firebase project and a Cloud Firestore database.
2. Give a backend service account Firestore access through IAM.
3. Set backend environment values:

```env
VECTOR_BACKEND=firebase
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_SERVICE_ACCOUNT_JSON={...the complete service-account JSON...}
```

Instead of JSON in an environment variable, use Application Default Credentials,
for example a Render secret file referenced by GOOGLE_APPLICATION_CREDENTIALS.
Never expose these credentials through a VITE_ variable.

Apply firebase/firestore.rules and firebase/firestore.indexes.json with the
Firebase CLI (`firebase deploy --only firestore --project YOUR_PROJECT_ID`) or
the console. Rules deny direct browser access; the backend Admin SDK uses IAM.
No browser Firebase SDK, Storage bucket, or native vector index is required.

On startup, Firebase mode loads committed document batches, verifies integrity,
and reconstructs the graph and search index. Invalid credentials/read failures
stop startup rather than silently claiming cloud persistence works.

Batches are compressed and divided into 700 KB pages. The manifest changes only
after every page is written, so interrupted publication preserves the previous
revision. A delete tombstones the manifest before removing all pages. Old edit
pages are retained until document deletion. The maximum raw batch is 64 MiB.

Use one API instance/process: caches are not synchronized across replicas. Startup
reads the persisted corpus. This design targets a demo-sized corpus; it does not
claim unlimited scale or guaranteed free operation. Firestore usage is metered.

Original uploaded files, operation polling checkpoints, and discovered topics
remain local. Extracted content and evidence survive restarts. Interrupted uploads
may need resubmission; topic discovery may need rerunning.

## Vercel frontend

Root Directory: Phase4/frontend. Framework: Vite. Build: `npm run build`.
Output: dist. Two supported API connection choices:

- Leave VITE_API_BASE_URL empty and update the backend hostname in vercel.json.
  API rewrites run before the SPA fallback.
- Set VITE_API_BASE_URL to your API URL, and configure backend CORS_ALLOWED_ORIGINS
  with the exact frontend origins, comma-separated.

## Render backend

Build: `pip install -r requirements.txt`. Start: `python run_app.py`.
Health endpoint: /health. Set SERVE_FRONTEND=false for separate frontend hosting.
render.yaml is a template; fill in your Firebase secrets before applying it.
Neo4j credentials are optional and backend-only, as shown in .env.example.

## Cyber demo

Click **Load synthetic cyber demo** in Reasoner. Six labeled fixtures pass
through the normal ingestion lifecycle. Suggested prompts cover the blast radius,
PHP gateway attack path, opposing mitigation claims, and malicious log text.
The actor, topology and patch dispute are fictional. No real threat actor is
attributed to the CVE. Connectivity means a potential route, not proven exploitation.
Negated, uncertain, conditional and disputed links are excluded from attack paths.
Each hop has an exact quote, source document, chunk ID and path ID. Topic filters
also constrain cyber paths.

## MCP

From Phase4 run `python -m backend.mcp_server`. Set AEGISGRAPH_API_URL to your
API (default http://localhost:8000). Standard MCP clients launch it over stdio.
Tools: sec_trace_attack_path, sec_query_threat_intel, sec_find_conflicts,
sec_ingest_advisory. They call the same API as React, not a second data store.
Ingestion returns a receipt; check its operation ID through the API for completion.

## Validation and boundaries

Run `python test_all_phases.py`, then `npm run build` in Phase4/frontend.
Firebase persistence tests use a Firestore test double. Once connected, verify
upload -> query -> edit -> restart -> delete -> restart with exact source quotes.

The API has no user login/workspace-membership authorization. Workspace IDs
partition data but are not access control. Put private deployments behind access
control before storing sensitive information. Firestore rules protect direct
client access, not the API. Runtime database configuration is an admin endpoint.

Neo4j's existing adapter uses a different contract from current ingestion. Until
write-through is connected, queries use the embedded graph restored from Firebase.
Database status reports connectivity, not proof every storage path is active.

References: [Firebase Admin](https://firebase.google.com/docs/admin/setup),
[Firestore limits](https://firebase.google.com/docs/firestore/quotas),
[Vercel rewrites](https://vercel.com/docs/rewrites).
