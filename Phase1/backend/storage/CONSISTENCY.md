# Task 1 storage consistency model

Neo4j graph publication is authoritative. Vectors are staged and verified before
the graph's active revision pointer and corpus epoch are changed. The stores do
not share a transaction: a vector-stage failure leaves the old graph snapshot
visible, while a graph-publication failure leaves staged vectors invisible
because every vector read is filtered by the caller's graph `CorpusSnapshot`.

After graph publication, cleanup deletes retired graph/vector data idempotently.
A cleanup failure records `cleanup_pending` in the durable operation checkpoint
and leaves the operation running; it never reverts a successful publication.
`cleanup`/`recover_cleanup` retries removal and a current-snapshot read probe,
then marks the operation ready. Repository reads validate workspace and current
snapshot epoch, so they cannot mix old/new active revisions.

The included in-memory implementations (`InMemoryGraphRepository`, `InMemoryVectorRepository`)
serve as offline CI test doubles. Production `Neo4jGraphRepository` (for Neo4j AuraDB)
and `ChromaVectorRepository` (for persistent Chroma) conform to `GraphRepository` and
`VectorRepository`. Connection parameters are configured via environment variables:
- `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`
- `CHROMA_PERSIST_DIR`

No consumer is allowed direct database access; all graph and vector interactions must
go through these repository interfaces coordinated by `StorageLifecycle`.

