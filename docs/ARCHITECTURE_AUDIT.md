# October 27 migration update

Neon PostgreSQL/pgvector and Neon Auth replace the Firebase implementation described in the historical audit below. Current setup and boundaries are in HOSTED_SETUP.md and AUTHENTICATION.md. SQL publication is transactional; live Neon verification remains pending. Neo4j write-through remains unfinished.

# AegisGraph architecture audit and local verification

Reviewed against the master context, pivot blueprint, flowcharts and the current
Firebase hosting plan. This is a code/runtime review, not a live cloud deployment
verification. The historical architecture documents include unimplemented claims.

## Local verification

The app is running at http://127.0.0.1:8000 with the production React build and
in-memory storage. No Firebase or Neo4j credentials were used.

| Check | Result |
| --- | --- |
| UI, demo ingestion and graph | Passed in the browser; six synthetic documents loaded |
| Blast-radius query | Returned CVE -> gateway -> auth service -> banking database |
| Negated backup-vault access | Excluded from reachable assets |
| Evidence | Every returned attack-route quote matched its source chunk |
| Citation inspection | Opened the actual source paragraph in the UI |
| Document lifecycle | Upload, edit, stale-edit HTTP 409, delete and path cleanup passed over HTTP |
| Topic filtering | A missing topic yielded no attack-path evidence |
| MCP | Actual stdio client initialized, listed all four tools and called the trace tool successfully |
| Browser console | No captured warnings/errors during the checked flow |
| Firebase | Test-double checks passed; live account integration remains unverified |
| Final unified suite | 138 passed, one optional Neo4j test skipped |

The first suite run missed the 500-document timing threshold: 16.79 seconds versus
15 seconds. The final suite passed, so this target is timing-sensitive and should
not be presented as a reliable production SLA. No test threshold was relaxed.

A live evidence check found that GET /v1/chunks/{id}/source truncated chunks to
200 characters while returning full offsets. Fixed locally to return the complete
chunk; added a regression test for evidence beyond character 200. The final suite
and HTTP evidence validation passed after the fix.

Network view rendered after using Fit to Screen. Automatic framing on mode/query
changes needs improvement. Repeated hops supported by multiple documents are also
printed repeatedly in the answer instead of one hop with grouped citations.

## Remaining work in priority order

Update: the next implementation pass added Firebase login, live workspace roles,
operation/source isolation, platform-admin checks, upload/archive bounds and an
operator membership CLI. It also removed synthetic-heading false claims and
restricted contradictions to matching assertions or exclusive predicates. The
demo now has one intended patch dispute. See AUTHENTICATION.md. The findings below
record the original audit; audit trails, rate limits and real-cloud verification
remain open.

### 1. Access control and ingestion hardening

Implement login, backend token verification, workspace membership and roles.
Restrict runtime database configuration to administrators. Firebase rules deny
direct database access but do not secure the FastAPI endpoints. Add audited
administrative actions, upload-size/archive limits, filename/path validation and
rate limits before private multi-user hosting.

### 2. Real extraction, embeddings and grounded synthesis

The active extractor is regex/rule-based. The embedder hashes words into random
768-dimensional vectors; it does not run MPNet. General answers select sentences,
and Hindi routing uses a fixed concept map. Connect actual providers/models,
validate exact evidence spans for each extracted relation, re-embed the corpus,
and enforce claim-by-claim source/path coverage for all generated answers.

Evidence: Phase4/backend/ingestion/extractor.py, ingestion/embedder.py and
services/query_service.py. Provider names in comments are not proof of integration.

### 3. Neo4j integration with the active application

DatabaseManager can initialize a Neo4j repository, but LifecycleService publishes
to the embedded GraphStore. Query traversal also uses that store. Bridge the
repository contracts and test create/edit/delete, graph traversal, restart
recovery, connectivity failure and reconnect reconciliation. A connected badge
must reflect the actual storage path.

Evidence: Phase4/backend/storage/db_manager.py and services/lifecycle_service.py.

### 4. Conflict precision and provenance

The demo's mitigation query returned nine conflict pairs: one intended patch
dispute and eight false alarms involving SYNTHETIC ASSOCIATED_WITH DEMO. Generic
extraction attaches sentence negation to unrelated capitalized words, while query
conflict filtering accepts broad shared terms. Clean metadata/headings, use
claim-specific negation, distinguish exclusive predicates from multi-valued
relationships, filter by the requested CVE/entity, and handle time, version and
conditions. Add precision tests; detecting at least one conflict is insufficient.

The active GraphStore compares pairs inside buckets, so worst-case O(N) claims
are not supported by its implementation. Also verify source/topic isolation for
every conflicting claim and exact offsets in both sides.

### 5. Complete hosted durability and recovery

Firestore saves extracted batches and embeddings, but original files, operation
checkpoints and discovered topic assignments remain local. Persist the required
state, wire startup recovery into the actual application lifecycle, and verify
with a real Firebase project. Add optimistic concurrency and interrupted-write
cleanup. Old edit pages currently remain until document deletion.

The backend rebuilds an in-memory search/graph index on startup. Multiple API
instances do not synchronize their caches. Define the expected corpus size and
move to coordinated shared indexes/queues if horizontal scaling is required.

### 6. Real CTI sources and richer cyber normalization

The six demo files are synthetic. Add grounded CISA/CVE/NVD and MITRE ATT&CK/STIX
imports with URLs, timestamps, deduplication, canonical identifiers and refresh
handling. Support realistic advisory prose, actor aliases, software versions,
patches, CVSS/severity and conditions rather than only simple tokenized sentences.

### 7. Attack reasoning and remediation workflow

Directed evidence-backed connectivity traversal works. Asset inventory, exposure,
privilege requirements, exploit preconditions, time-aware findings, risk ranking
and remediation recommendations are not implemented. The MCP server exposes
investigation/ingestion tools; it does not generate validated environment-specific
firewall rules or provide an approval/audit workflow for remediation execution.

### 8. Topic quality, product polish and operational evidence

HDBSCAN helpers exist, but the active topic service uses k-means and generic
labels, fixed assignment confidence and approximate entity counts. Connect the
intended discovery/labeling pipeline and persist stable topics. Improve automatic
graph framing, grouped hop citations, conflict navigation and error reporting.
Measure real upload/query/update latency and resource usage with connected cloud
stores; add structured telemetry, meaningful readiness checks and a backup demo.

## What only needs configuration

Firebase project/service-account credentials and rules deployment, Vercel project
settings, Render environment variables, and the selected API URL/CORS origins are
deployment tasks. They are separate from the missing code above. Supabase is no
longer part of the current plan. See HOSTED_SETUP.md for the configuration handoff.

Recommended build order: access controls -> conflict precision -> real extraction
and embeddings -> active Neo4j integration -> durable recovery -> CTI connectors
-> richer attack/remediation logic -> scale and interface polish.
