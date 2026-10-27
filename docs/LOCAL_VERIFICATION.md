# Local build verification — October 27

Added a local-only SQLite persistence mode using VECTOR_BACKEND=local. Completed extraction batches include source chunks, extracted graph assertions and vectors. They commit atomically and rebuild the embedded graph and cosine index on restart. start_local.ps1 starts this mode with cloud connections disabled and a loopback-only listener.

Verified with a real SQLite database and HTTP server: loaded all six synthetic cyber documents; stopped and restarted the API process; recovered six documents and five potential attack paths; checked every returned route quote against its restored source chunk. Browser workspace loading and the cited blast-radius query worked after restart, with no captured browser warnings/errors. Screenshot: .test-temp/local-durability-proof.png (local, excluded from Git).

Five new regression tests cover restart recovery and workspace/topic filtering, edit/delete recovery, failed-write rollback, lifecycle startup restoration, and truthful health reporting. The required python test_all_phases.py run passed all four phases. Frontend production build and all three auth SDK checks passed.

Corrected health labels to identify rule extraction and word-hash embeddings. A verified Neo4j connection no longer claims it is the active ingestion graph. The UI distinguishes saved local storage from temporary memory.

Remaining: live Neon/Neo4j integration checks, active Neo4j ingestion/traversal, real model providers, durable original uploads and topics, multi-instance cache synchronization, audit trails and rate limits. SQLite mode is for a single local process and uses unauthenticated demo access; it is not a hosted authorization replacement.
