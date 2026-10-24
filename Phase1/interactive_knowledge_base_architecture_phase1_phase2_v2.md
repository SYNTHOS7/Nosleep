# Interactive Knowledge Base — Architecture (Generic KG MVP)

**Revision:** 2 — generic knowledge graph first; Claim-node model deferred  
**Status:** MVP architecture decision  
**Managed services:** Unstructured API for general document parsing; Neo4j AuraDB for graph storage

## 1. Product goal

Build the Phase 1 system described in the problem statement: ingest unstructured PDF/text documents, extract entities and triples, discover themes, store an embedded knowledge graph alongside vector retrieval, route questions between thematic and local factual retrieval, and return grounded answers with supporting graph paths in a split-screen UI.

Phase 2 extends this with trustworthy lifecycle management: ingest 500+ documents with measured performance; add/edit/delete individual documents without a full rebuild and update the graph within 60 seconds; expose contradictory claims together with their sources; resist instructions embedded in documents; and answer Hindi questions over English documents while preserving supporting graph paths. Phase 1 answer quality must not regress by more than 3 points under the agreed evaluation metric.

Use a conventional entity-and-relationship graph for Phase 1. **Do not introduce Claim nodes merely for architectural elegance.** However, Phase 2 explicitly requires showing conflicting claims with source attribution. Implement the smallest assertion/evidence representation that passes this requirement. If direct relationship properties cannot represent a conflict faithfully—especially conflicting values or statements that are not simple entity-to-entity triples—add an assertion/claim record in Phase 2. This is requirement-driven, not a speculative abstraction.

## 2. Architecture at a glance

```text
Upload / source
   ↓
Ingestion API (FastAPI)
   ↓
Unstructured API for general document parsing and chunking
   ├─ deterministic parsers for code, manifests, JSON, YAML, etc.
   ↓
Normalized Document + Chunk records
   ↓
Neo4j GraphRAG KG builder
   ├─ entity extraction
   ├─ typed relationship extraction
   ├─ optional schema extraction / schema-guided extraction
   ├─ lexical Document/Chunk graph
   ├─ chunk embeddings (through configured embedder)
   └─ entity resolution
   ↓
Neo4j AuraDB
   ├─ lexical graph: Document, Chunk, NEXT_CHUNK, FROM_DOCUMENT
   ├─ domain graph: typed entity nodes and typed relationships
   ├─ vector/full-text indexes as configured
   └─ topic assignments and topic metadata (our layer)
   ↓
Query intelligence (our layer)
   ├─ topic discovery and topic scope selection
   ├─ vector / keyword / graph retrieval selection
   ├─ bounded graph traversal
   ├─ evidence/chunk collection
   └─ grounded answer + paths + limitations
   ↓
FastAPI now; MCP interface for agents; UI later
```

## 3. What we reuse versus what we build

| Capability | MVP approach | Ownership |
|---|---|---|
| PDF and general document parsing | Unstructured API | Reuse; normalize outputs into our schema |
| Code/config/structured-data parsing | Format-aware parsers where useful | Build small deterministic adapters; do not rely on prose extraction for syntax |
| Text chunking | Unstructured or Neo4j GraphRAG splitter, chosen and pinned | Reuse; test chunk size/overlap on our corpus |
| Entity extraction | Neo4j GraphRAG KG builder | Reuse; configure schema and LLM |
| Typed relationship extraction | Neo4j GraphRAG KG builder | Reuse; validate direction, type and evidence links |
| Graph writing | Neo4j GraphRAG writer into AuraDB | Reuse behind an adapter |
| Basic entity resolution | KG builder's configured resolver | Reuse cautiously; review false merges |
| Chunk embeddings | One configured embedding model/provider | Reuse adapter; keep model/version consistent for queries |
| Graph database hosting | Neo4j AuraDB | Managed service |
| Persistent topic IDs and topic discovery | Our service | Build |
| Topic assignment and cross-topic policy | Our service | Build |
| Query planning across vector, keyword and graph retrieval | Our service using GraphRAG components where suitable | Build and evaluate |
| Collection-wide synthesis / topic summaries | Our service; evaluate GraphRAG-style global methods later | Build/evaluate |
| API and MCP tool surface | FastAPI + official MCP Python SDK | Build |
| Claim/assertion evidence model | Phase 1: source-linked direct relationships; Phase 2: add only the minimal assertion layer needed to show contradictions faithfully | Requirement-driven |

## 4. Graph model for the MVP

### 4.1 Lexical graph

Use document and chunk nodes so retrieved facts can be traced back to source text.

- `(:Document {id, workspace_id, source_name, source_type, content_hash, metadata})`
- `(:Chunk {id, workspace_id, document_id, text, chunk_index, location, embedding, metadata})`
- `(:Chunk)-[:FROM_DOCUMENT]->(:Document)`
- `(:Chunk)-[:NEXT_CHUNK]->(:Chunk)`

The exact labels/property names may be adapted to the KG builder's lexical graph configuration, but our ingestion adapter must normalize them and preserve stable IDs and workspace ownership.

### 4.2 Domain graph

Use entity nodes with labels and properties, joined by conventional typed relationships:

```text
(:SoftwareService {name: "Service A"})
  -[:DEPENDS_ON {source_chunk_id: "chunk-17", extraction_method: "llm"}]->
(:SoftwareService {name: "Service B"})
```

This is an illustrative target shape, not a claim that the builder will emit exactly these labels or properties without configuration. Store provenance on relationships where supported by the selected writer/pipeline, and retain the source chunk/entity-to-chunk link as a baseline audit trail. Before implementing the adapter, inspect the builder's actual output and test that each extracted relationship can be traced to the chunk(s) that produced it.

**Important distinction:** `DEPENDS_ON`, `USES`, `SUPPORTS`, `LOCATED_IN`, and `AFFECTS` are not universal built-in Neo4j types. Neo4j allows custom relationship types and traverses them using Cypher. The KG builder's LLM can propose relationship types from source text, or we can constrain it with a schema. We should use a controlled schema for repeatability once the generic first-pass extraction has been inspected.

### 4.3 Topic layer (our responsibility)

- `(:Topic {id, workspace_id, label, slug, description, discovery_method, model_version, cluster_version})`
- `(:Topic)-[:HAS_MEMBER {confidence, method, model_version}]->(:Chunk)` (or an equivalent `TopicAssignment` node/table if richer assignment history is needed)

**Initial topic-discovery pipeline:**

1. Generate an embedding for each normalized chunk using the same documented embedding model/version used by semantic retrieval, unless evaluation justifies a separate topic embedding model.
2. Cluster chunk embeddings to discover candidate themes. Evaluate **HDBSCAN** as a first candidate because the number of themes is not known in advance and some chunks may not belong to a clear cluster. Compare it with **K-means** as a baseline; K-means requires choosing the number of clusters and assigns every point to one.
3. For each candidate cluster, select representative chunks (for example, central/medoid-like examples plus diverse examples) and ask an LLM to propose a concise label and evidence-grounded description. The LLM must summarize the supplied examples, not invent a theme unsupported by them.
4. Persist the topic, its stable ID, representative chunk IDs, algorithm/parameters, embedding model version, cluster version, and assignments. Keep low-confidence or unclustered chunks available to ordinary retrieval rather than forcing them into a theme.
5. Evaluate topic coherence, duplicate/overlapping themes, coverage, stability across reruns, usefulness for broad questions, and the cost/latency of discovery. Choose the algorithm and thresholds from these results rather than assuming HDBSCAN is always best.

Use stable IDs (UUIDs or workspace-scoped slugs), **not embedding vectors**, as topic identifiers. A topic label may change without changing its identity when the underlying topic remains recognizably the same; if a clustering revision materially changes the topic, record a new cluster version and update assignments deliberately. A chunk may belong to multiple topics when appropriate. Topic membership is a retrieval scope hint, not proof that two entities have a factual relationship.

**Phase 2 update constraint:** adding/editing/deleting a document must update affected topic assignments and, when necessary, topic descriptions within the 60-second target without requiring a full corpus rebuild. Start with local assignment to existing topic representations and a targeted refresh; periodically evaluate whether broader reclustering is needed. Treat this as a benchmark requirement—the best incremental strategy depends on the selected clustering algorithm and corpus.

### 4.4 Evidence and contradiction handling: staged by requirement

**Phase 1:** keep direct typed relationships and source-chunk links. Store relationship provenance properties when supported, and preserve the source text/chunk needed to inspect every extracted triple.

**Phase 2:** the requirement to show both sides of a contradiction makes evidence identity a product requirement. Start by checking whether source-linked relationship records can represent the target contradiction cases. Direct edges may suffice for simple conflicting triples if each assertion remains separately attributable. They are not sufficient for every case: for example, two documents may state different values for a property, or make conflicting statements that do not fit a simple entity-to-entity edge.

If direct edges cannot represent these cases without overwriting or conflating statements, introduce a minimal `Assertion` (or `Claim`) record containing the normalized statement/triple, source chunk/document ID, assertion status/type where useful, extraction metadata, and any time/version information needed by the test cases. Link it to subject/object entities and source evidence. Do not build a large verification workflow unless the PS requires it.

The acceptance test is concrete: for planted contradiction pairs, the answer and UI must display both statements and their sources, rather than silently merging them or selecting one as true.

## 5. What Neo4j GraphRAG KG builder can do

The official Python library's KG builder can provide a pipeline with components for loading text/files, splitting text into chunks, optional chunk embeddings, schema creation (manual or LLM-derived), entity/relation extraction, graph pruning, writing to Neo4j, and entity resolution. The `SimpleKGPipeline` is the easiest starting point.

It can also create a lexical graph of documents and chunks, including sequential chunk links and links from chunks to their source document. Its schema can specify node labels, relationship labels, properties, and allowed source–relationship–target patterns. Schema guidance helps steer extraction, but do not assume it is a perfect hard guarantee: configure pruning/allowed additional types and validate results.

Entity resolution is especially important: the documented default resolver can merge entities sharing the same label and identical `name`; optional fuzzy or semantic resolvers can merge similar names. These can create false merges, so test them on representative data and keep the resolver replaceable.

The KG builder is documented as **experimental**, so pin the package version and isolate it behind an adapter. Test the exact Neo4j Aura version, LLM provider, embedder and schema settings used by the project.

## 6. What it does not solve for us

Do not assume the KG builder automatically provides:

1. **Correctness guarantees.** Extracted entities, relation directions, types and properties can be wrong or unsupported by the text.
2. **A universal domain ontology.** The builder can derive or use a schema, but we must choose how generic or constrained the graph should be.
3. **Reliable global topic discovery.** Entity/relation extraction is not the same as clustering the whole corpus into useful, stable, scoped topics.
4. **Collection-wide answers.** Global synthesis and broad “what are the main themes/patterns?” queries need a separate strategy and evaluation.
5. **Conflict resolution or truth verification.** A graph edge is a recorded extracted relation, not a guarantee that the relation is true or current.
6. **Our security and scope rules.** Workspace isolation, topic filters and cross-topic permission must be enforced in our query layer.
7. **Query intelligence.** We still need to decide when to use vector search, keyword search, graph traversal, or combinations.
8. **An MCP interface or product UI.** These remain application-layer responsibilities.

## 7. Extraction policy

Use the KG builder as the initial generic extraction engine, but do not force every source through an LLM:

1. **Deterministic parsing** for formats where structure gives direct evidence: imports, package manifests, JSON/YAML fields, symbol references and configuration links.
2. **KG-builder extraction** for general prose and mixed unstructured content.
3. **Validation and normalization** before accepting graph writes: required properties, workspace ID, valid source/target, allowed labels/types, source-chunk linkage and stable identifiers.
4. **Entity-resolution review** on a representative test set before turning on aggressive fuzzy/semantic merging.
5. **Idempotent ingestion** using content hashes and stable document/chunk IDs; avoid duplicating the graph when a document is reprocessed.

Treat extracted relationships as **candidate recorded knowledge**, not verified truth. Keep extraction method/model/version metadata wherever feasible. Do not promote mere co-occurrence or vector similarity into a typed factual relationship.

## 8. Query path

For each request:

1. Validate `workspace_id` and the requested topic scope.
2. Resolve topic scope: selected topic(s), all topics, or discover relevant topics.
3. Retrieve candidate chunks using vector search, keyword/full-text search, or both.
4. If the question requires connections, identify relevant entity nodes and traverse a bounded neighborhood using Cypher.
5. Gather source chunks for retrieved entities/relationships and verify that the answer is supported by those chunks.
6. Synthesize an answer with source references, relevant graph paths, scope used, and explicit limitations when evidence is weak or missing.
7. Enforce workspace and topic boundaries throughout retrieval and traversal, not only at the initial vector-search step.

A graph path shows recorded connections; it does not by itself prove causation. If sources disagree, the MVP should report the uncertainty where detectable rather than silently asserting certainty.

## 9. Topic isolation and cross-topic reasoning

- A workspace is a hard security boundary.
- Topic scope is the default retrieval boundary.
- Cross-topic retrieval is opt-in for a query or explicit user choice.
- Topics are not mutually exclusive: a chunk can have multiple assignments.
- Topic assignments carry confidence and method/model version.
- A topic match is not evidence of a domain relationship.

Cybersecurity and supply-chain material, for example, should remain separate by default. A user may explicitly ask for a cross-topic analysis, at which point the query planner can search both and explain the connections it actually finds in source evidence.

## 10. Initial stack

- **Parsing/chunking:** Unstructured API for common document formats; deterministic parsers for structured/code sources.
- **Graph store:** Neo4j AuraDB.
- **Graph construction:** `neo4j-graphrag` Python package, starting with `SimpleKGPipeline` and a configured schema after a short exploratory test.
- **LLM:** provider-neutral adapter; choose based on structured-output support, extraction quality, latency and cost.
- **Embeddings:** one model/version for chunk and query vectors; document the dimension and index configuration.
- **Application:** Python + FastAPI.
- **Agent access:** official MCP Python SDK over the same query/service layer; MCP is an interface, not the reasoning engine.
- **Topics:** embedding-based chunk clustering; evaluate HDBSCAN against K-means, then use an LLM to label and describe clusters from representative chunks. Persist topic IDs, assignments, model/cluster versions, and representative evidence.

## 11. Implementation sequence aligned to the problem statement

### Phase 1 — core deliverable

1. **Smoke test the KG builder:** one short PDF/Markdown file, AuraDB, chosen LLM and embedder; inspect exact node labels, relationship types, chunk links and entity-resolution behavior.
2. **Define the adapter contract:** normalize builder output into Document/Chunk/Entity/Relationship/Topic records and preserve source-chunk provenance.
3. **Build ingestion:** parsing, chunking, content hashing, stable IDs, workspace tagging, retries, idempotency and validation.
4. **Add graph + vector retrieval:** vector/keyword retrieval plus bounded Cypher traversal; always return source chunks and graph paths.
5. **Add topic discovery:** cluster corpus representations, assign persistent topic IDs, store assignments and produce topic descriptions from representative examples.
6. **Add query routing and synthesis:** route broad thematic questions to topic/community-level retrieval and specific factual/multi-hop questions to local graph retrieval or a hybrid path.
7. **Build the split-screen UI:** left side for document upload and chat; right side for an interactive graph that highlights the relevant topic cluster, source documents, entities and supporting path.
8. **Evaluate Phase 1:** create a fixed question set and record answer quality, groundedness, path correctness, topic quality, latency and cost.

### Phase 2 — trustworthy updates and adversarial robustness

9. **Incremental document lifecycle:** add, edit and delete one document without rebuilding the corpus. Use stable document/chunk IDs, version/content hashes, explicit ownership links, and idempotent jobs. On edits, remove or replace the old document's derived chunks, relationships and topic assignments without deleting shared entities still supported by other documents. Complete the graph update within 60 seconds for the defined test workload.
10. **Contradiction preservation:** create planted pairs of conflicting source statements. Ensure ingestion preserves both source-attributed assertions and the answer layer reports both, with document/chunk references and graph paths where applicable. Add a minimal Assertion/Claim representation only if direct source-linked edges cannot pass these tests.
11. **Prompt-injection resistance:** treat all ingested text as untrusted data, never as system/developer instructions. Extraction prompts must delimit source text as data; the pipeline must not execute instructions found inside documents or grant document text tool/DB-write authority. Test at least 20 planted injections and record whether any alter routing, access boundaries, extraction policy or answer behavior.
12. **Hindi question support over English documents:** use multilingual embeddings or a tested query-translation strategy. Preserve source-language evidence and return the same English-source graph paths/chunk references in the answer. Evaluate factual quality and path accuracy separately.
13. **Scale benchmark:** ingest at least 500 documents; report total and per-document ingestion time, graph node/relationship counts, chunk/vector counts, error/retry counts, and query latency. Document corpus composition and hardware/service configuration.
14. **Regression gate:** compare Phase 2 against the Phase 1 evaluation set. Phase 1 answer quality must stay within 3 points of baseline on the agreed metric; report confidence/variance if the test set is small.

## 12. Acceptance checks

### Phase 1

- Ingest PDF and text documents and extract entities/triples with source-chunk traceability.
- Discover meaningful themes across the collection using chunk embeddings, clustering, and evidence-grounded LLM labels/descriptions.
- Evaluate topic coherence, coverage, duplicate themes, stability, and usefulness for broad questions; do not treat generated labels as evidence by themselves.
- Answer specific and multi-hop questions using graph traversal and hybrid retrieval.
- Every answer exposes source evidence and the exact supporting graph path; unsupported conclusions are flagged.
- The UI shows upload/chat and an interactive graph view with relevant nodes, edges, topic clusters, and source documents.
- Re-ingesting identical content does not duplicate documents, chunks or relationships.

### Phase 2

- At least 500 documents ingested; report ingestion time and graph size.
- Adding, editing and deleting a document updates its derived graph state within 60 seconds without a corpus-wide rebuild.
- A contradiction test displays both claims/assertions and both sources; neither is silently overwritten or arbitrarily selected.
- At least 20 planted document prompt injections are tested; document content cannot override system policy or authorize tool/database actions.
- Hindi questions over English documents return grounded answers with supporting graph paths.
- Phase 1 answer quality remains within 3 points of the Phase 1 baseline on the agreed metric.
- Updates and deletions do not leave orphaned document chunks or remove shared facts still supported by other documents.
- Workspace/security boundaries remain enforced during vector retrieval, graph traversal, update and synthesis.

## 13. Official references

- Neo4j GraphRAG for Python: https://neo4j.com/docs/neo4j-graphrag-python/current/
- Knowledge Graph Builder guide: https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_kg_builder.html
- Neo4j GraphRAG API reference: https://neo4j.com/docs/neo4j-graphrag-python/current/api.html
- Unstructured API workflow overview: https://docs.unstructured.io/api-reference/workflow/overview
- Neo4j AuraDB: https://neo4j.com/product/aura-db/


## 14. Phase 2 design notes

- **Contradictions are not necessarily graph-edge opposites.** A conflict can be between values, dates, quantities, negated statements, or claims about a capability. Test the actual conflict cases before deciding that edge properties are sufficient.
- **Incremental updates need provenance at ingestion time.** Each derived chunk, entity mention, relationship, topic assignment, and assertion must be attributable to the source document/version that produced it. Otherwise, deleting or editing one document can damage knowledge still supported by other documents.
- **Prompt-injection defense is a pipeline property, not just a prompt sentence.** Keep document text in a clearly delimited data field, avoid giving extraction models unnecessary tools, validate all structured outputs, enforce authorization in application/database code, and test malicious examples end to end.
- **Hindi retrieval needs cross-lingual evaluation.** A multilingual embedding model is a reasonable baseline, but compare it against query translation on a fixed Hindi-question/English-document set. Do not translate away or hide the original source evidence.
- **Define “within 60 seconds” operationally.** Measure from successful add/edit/delete request acceptance to the point at which subsequent queries and graph visualization reflect the update. Report median and p95, and specify file sizes and concurrency in the benchmark.
- **Define the “3 points” metric before Phase 2.** Freeze a Phase 1 evaluation set and scoring rubric. Do not change the metric after seeing Phase 2 results.
