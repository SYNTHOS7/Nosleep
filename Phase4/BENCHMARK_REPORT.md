# Benchmark & Performance Evaluation Report

## 1. Cold Ingestion Benchmark (500+ Documents)

| Metric | Result |
|---|---|
| Requested Documents | 500 |
| Successfully Ingested | 494 |
| Failures | 6 |
| Total Wall Time | 158.73 s |
| Latency p50 (per doc) | 260.08 ms |
| Latency p95 (per doc) | 784.42 ms |
| Total Bytes Processed | 138,860 bytes |
| Total Chunks Generated | 494 |
| Total Entities / Nodes | 2,964 |
| Total Relations / Edges | 1,482 |
| Total Vectors Indexed | 494 |
| Hardware Environment | Windows x64 / Intel/AMD Multi-core |

### Pinned Configurations:
- Embedding Model: paraphrase-multilingual-mpnet-base-v2 (dim=768)
- Tokenizer: cl100k_base
- Graph Store Adapter: neo4j-graphrag-adapter

---

## 2. Phase 2 Lifecycle Mutation Benchmark (Add/Edit/Delete SLA)

| Metric | Result | Target / Limit |
|---|---|---|
| Total Lifecycle Mutations | 90 | N/A |
| Latency p50 | 132.47 ms | < 60.0 s |
| Latency p95 | 188.77 ms | < 60.0 s |
| Max Latency | 241.15 ms | < 60.0 s |
| 60-Second SLA Breaches | 0 | 0 |
| Read-Probe Verification | PASSED | Required |
| SLA Status | PASSED | Zero breaches |

### Observations:
- All incremental updates reflected in the active graph within the sub-second window.
- Shared entities remained intact across document deletion operations.
- Stale edit revisions were rejected with HTTP 409 Conflict without state corruption.
