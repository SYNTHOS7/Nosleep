# Hosted setup: Neon, Render and Vercel

The API uses Neon PostgreSQL for completed extraction batches, workspace permissions and pgvector search. Login uses Neon managed Auth (Better Auth). Firebase and Supabase are no longer required. No hosted account has been configured or tested by this migration.

## 1. Neon

Create a project, enable Neon Auth, and copy its full Auth endpoint URL and pooled PostgreSQL connection string. Keep the database connection string private. Enable the pgvector extension by running the explicit schema setup with a database owner connection:

```powershell
# From Phase4, with DATABASE_URL supplied in your environment
python -m backend.storage.neon_setup
```

This creates the private `aegis` schema and the public vector extension. API startup does not run schema migrations. Add your frontend origin to the Neon Auth trusted origins. The browser uses session cookies; browsers blocking cross-site cookies may require a same-site Auth proxy or shared-domain arrangement supported by Neon.

## 2. Render API

Use the repository Dockerfile or render.yaml. Set:

```text
DATABASE_URL=<private Neon pooled connection string>
NEON_AUTH_URL=<full Neon Auth endpoint>
VECTOR_BACKEND=neon
AUTH_MODE=neon
HOST=0.0.0.0
SERVE_FRONTEND=false
CHROMA_MIRROR_ENABLED=false
CORS_ALLOWED_ORIGINS=https://your-frontend.vercel.app
```

Keep one API instance: the active graph and topic cache are local to that process. Completed batches and their vectors are published atomically in PostgreSQL; edits replace old vectors and deletes cascade. Startup restores the active graph from saved batches. Vector queries run in PostgreSQL with workspace and optional topic filters. Themes and request audit events are also saved in PostgreSQL. Original upload files and operation checkpoints need a persistent disk or object storage on hosted services; local mode keeps them in data folders.

## 3. Vercel frontend

Set the root directory to `Phase4/frontend`, build command `npm run build`, output directory `dist`, and use Node 24 (or supported Node 20.19+/22.12+). Set these public build variables, then rebuild:

```text
VITE_API_BASE_URL=https://your-api.onrender.com
VITE_NEON_AUTH_URL=<same full Neon Auth endpoint>
```

Never expose DATABASE_URL in a VITE_ variable. The frontend talks to the API, which owns database access.

## 4. First account and permissions

Sign up through the app. New accounts receive no workspace access automatically. Copy the user ID displayed by the access screen, then run from Phase4 with DATABASE_URL in the operator environment:

```powershell
python -m backend.security.manage_access --uid USER_ID --workspace security-team --role admin --platform-admin
```

Reload the app. Give other users viewer, editor or admin access using the same command without `--platform-admin`. See AUTHENTICATION.md for revocation and verification details.

## Local development and MCP

Local defaults remain `VECTOR_BACKEND=in_memory` and `AUTH_MODE=demo`; run `python run_app.py --port 8000`. Demo mode is rejected for hosted environments or Neon storage. Environment examples are references; load variables through your shell or hosting provider.

MCP: from Phase4 run `python -m backend.mcp_server`, with AEGISGRAPH_API_URL and an authenticated AEGISGRAPH_ID_TOKEN for hosted access. Tokens expire and must be refreshed by the caller.

## Verification boundaries

Run `python test_all_phases.py`, and `npm run test:auth` in the frontend. Storage tests use a transaction-aware database double; JWT tests verify real Ed25519 signatures with a mocked key endpoint. A live Neon project still needs schema, sign-up/login, upload/search/edit/delete, restart recovery and role revocation checks.

Set NEO4J_PROJECTION_ENABLED=true with durable storage to copy the evidence graph into Neo4j after document/theme changes and startup. Only AegisManaged nodes are replaced, scoped per workspace; use a dedicated database. Neo4j/SQLite is not a distributed transaction: authoritative data survives projection failure and is reconciled on a subsequent mutation or restart. Application queries still traverse the embedded graph. Live projection verification is pending. Default extraction and embeddings remain rules/hash vectors. Optional local Ollama models are implemented; see LOCAL_AI.md. Hosted deployment must explicitly provision any model server. Metadata-only request audit history and single-process request limits are implemented. Multi-instance synchronization, tamper-proof audit retention and original-upload object storage are unfinished. Configure READ_REQUESTS_PER_MINUTE and WRITE_REQUESTS_PER_MINUTE as needed; defaults are 180 and 30. Existing Firebase data is not automatically migrated or deleted.
