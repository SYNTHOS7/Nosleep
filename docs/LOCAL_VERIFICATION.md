# Local feature build and verification — October 27

The local application now supports saved themes, stable discovery snapshots, persistent original upload files, atomic operation checkpoints, automatic interrupted-job recovery, offline CISA KEV-shaped catalog import, metadata-only audit history, and bounded request throttling.

Verified with a running localhost API and real SQLite: created an accepted operation before starting the server; startup resumed it and published its document. Discovered two themes and imported a synthetic KEV fixture through HTTP. Restarted the process again: eight documents, the same two theme IDs, and both request audit events recovered. Imported publisher authenticity is explicitly unverified; the fixture is not real threat intelligence. Catalog imports index CVE identifiers and source text without inferring attack edges from JSON fields or metadata.

The Neo4j projection adapter writes all scoped nodes and evidence-bearing links in one managed transaction, replacing only AegisManaged nodes for that workspace. It receives all content and predicates as parameters. Local recording-driver checks verify transaction calls, parameterization, provenance and failure behavior; they do not execute Cypher against Neo4j. Live Neo4j integration is still pending. Writes retry on subsequent mutations or restart; operators can reconnect through authenticated configuration. Neon/SQLite remains authoritative and application queries still use the embedded graph.

Themes and request audit events have SQLite and Neon persistence adapters. Rerun the explicit Neon schema setup when connecting an existing database. Original upload files and operation checkpoints remain disk-backed: hosted services need persistent storage. Audit persistence failure is logged, not transactionally coupled to document writes. This is request history, not a tamper-proof compliance audit. Limits are per process and actor (local demo uses the peer address); they are not distributed or a replacement for platform-level abuse controls.

The required unified four-phase suite, frontend build and three auth SDK checks passed. New regression coverage includes restart and rollback behavior, theme scoping, validation failure audit status, audit privacy/admin access, rate-limit expiry/bounds, feed validation/deduplication, and safe graph projection contracts. The optional live Neo4j test remains skipped without credentials.

To run: ./start_local.ps1. For the checked preview, open http://127.0.0.1:8003 and choose workspace local-proof. Local sources, databases and proof artifacts are excluded from Git.

Still unfinished: real AI providers/learned embeddings, direct Neo4j-backed application traversal, live cloud verification, hosted upload/checkpoint object storage, cross-instance synchronization, additional NVD/MITRE/STIX import formats, and environment-aware exploit/remediation reasoning.

Implementation references: https://neo4j.com/docs/python-manual/current/transactions/ and https://github.com/cisagov/kev-data/blob/develop/known_exploited_vulnerabilities_schema.json.

Browser proof: .test-temp/complete-local-build.png shows eight restored documents and two saved themes; no captured console warnings/errors.
