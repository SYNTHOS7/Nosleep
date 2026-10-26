# Interactive Knowledge Base — Grounded Intelligence & Knowledge Graph

[![Unified Test Suite](https://img.shields.io/badge/tests-120%2F120%20passing-brightgreen.svg)](#testing--verification)
[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Persistent-orange.svg)](https://www.trychroma.com/)
[![Neo4j](https://img.shields.io/badge/Neo4j-AuraDB%20%26%20Embedded-008CC1.svg)](https://neo4j.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

An enterprise-grade, grounded intelligence system that bridges unstructured documents, persistent vector embeddings, and an interactive knowledge graph. Designed to handle broad thematic queries, multi-hop fact chains, document contradiction tracking, prompt injection immunity, and cross-lingual Hindi queries over English corpora.

---

## 🌐 Live Deployment

- **Production Web Application**: [https://nosleep-n1ae.onrender.com/](https://nosleep-n1ae.onrender.com/)
- **Interactive Swagger Docs**: [https://nosleep-n1ae.onrender.com/docs](https://nosleep-n1ae.onrender.com/docs)
- **Health & Readiness Check**: [https://nosleep-n1ae.onrender.com/health](https://nosleep-n1ae.onrender.com/health)
- **Database Status**: [https://nosleep-n1ae.onrender.com/v1/database/status](https://nosleep-n1ae.onrender.com/v1/database/status)

---

## 🚀 Key Capabilities & Phase 2 Compliance

| Requirement | Implementation & Performance |
| :--- | :--- |
| **500+ Documents Bulk Ingestion** | Ingests 500+ documents concurrently via batch endpoint or 1-click UI benchmark. Reports exact ingestion time (s) and graph size (nodes, edges). |
| **60-Second Dynamic Mutation** | Add, edit, or delete documents without rebuilding the app. Sub-second mutation latency (**~75ms - 95ms**) with durable disk checkpoints. |
| **Document Contradiction Detection** | Detects conflicting claims across documents; presents both sides with exact quotes and source links instead of picking one. |
| **Prompt Injection Immunity** | Robust extraction layer treats all 20+ planted prompt injections as raw data, completely neutralizing malicious execution. |
| **Cross-Lingual Hindi Answering** | Accepts Hindi queries over English knowledge corpora, returning Hindi syntheses with English graph citation paths. |
| **Answer Quality Preservation** | Maintains Phase 1 benchmark answer quality within 3 points while enabling broad thematic exploration. |
| **Dual-Database Topology** | **ChromaDB** for persistent vector embeddings + **Neo4j** (AuraDB & self-hosted) alongside embedded transactional fallback. |

---

## 🏛️ System Architecture

![System Architecture Diagram](docs/architecture.svg)

<details>
<summary><b>View Mermaid Source Code</b></summary>

```mermaid
graph TD
    Client[Split-Screen React UI / REST Client] -->|FastAPI Gateway| API[Phase 4: REST API & Lifecycle Service]
    
    subgraph Ingestion Pipeline
        API -->|Upload / Batch| Parser[Phase 2: PDF / TXT Parser]
        Parser --> Chunker[Deterministic 600-Token Chunker]
        Chunker --> Extractor[Entity, Relation & Value Extractor]
        Chunker --> Embedder[Multilingual MPNet 768-Dim Embedder]
    end
    
    subgraph Dual Persistence & Storage
        Extractor -->|Batch Publish| GS[Phase 1 / 4: Transactional Graph Store]
        Embedder -->|Vector Upsert| VS[Phase 1 / 4: Vector Repository]
        GS -.->|Synchronize| Neo4j[(Neo4j AuraDB / Bolt)]
        VS -.->|Persistent Index| Chroma[(ChromaDB: ./data/chroma)]
        API -.->|Atomic Checkpoints| Disk[(Operations Checkpoint: ./data/operations)]
    end
    
    subgraph Thematic Clustering & Grounded Synthesis
        GS --> Clustering[Phase 3: HDBSCAN + Incremental Centroid Topics]
        VS --> Hybrid[Phase 3: Reciprocal Rank Fusion & Graph Traversal]
        Hybrid --> ConflictEngine[Phase 3: O(N) Conflict Detection]
        Hybrid --> HindiEngine[Phase 3: Cross-Lingual Hindi Routing]
        ConflictEngine --> Synthesis[Grounded Synthesis with Provenance]
        HindiEngine --> Synthesis
    end
    
    Synthesis --> Client
```
</details>

---

## 📸 Interactive System Showcase

### 1. Force-Directed Knowledge Graph Visual
Nodes stay permanently visible on the canvas with color-coded entity labels, document clusters, and bidirectional relation edges:

![Interactive Knowledge Graph Visual](docs/knowledge_graph.png)

### 2. Dual-Database Connectivity & Configuration
Active Chroma vector persistence alongside Neo4j AuraDB and embedded transactional graph repository:

![Database & Persistence Connections](docs/database_connections.png)

### 3. Grounded Synthesis & Highlighted Graph Path
100% citation-grounded answering with supporting subgraph traversal path highlighting:

![Grounded Query Answering & Graph Highlight](docs/query_synthesis.png)

---

## 🗄️ Database & Storage Engine

The architecture supports a dual-engine database strategy configured via environment variables or runtime UI controls:

### 1. Vector Database: ChromaDB
- **Storage Mode**: Persistent on-disk vector store located at `./data/chroma`.
- **Embedding Space**: 768-dimensional normalized unit sphere (`hnsw:space: cosine`).
- **Collections**: Per-workspace collections (`ws_<workspace_id>`) for strict multi-tenant isolation.

### 2. Graph Database: Neo4j & Embedded Transactional
- **Cloud / Self-Hosted Neo4j**: Connects to Neo4j AuraDB (`neo4j+s://...`) or local instances (`bolt://localhost:7687`).
- **Resilient Fallback**: If external Neo4j credentials are not supplied, the system seamlessly uses its embedded in-memory transactional graph repository.

### 3. Durable Checkpoint Storage
- **Directory**: `./data/operations`
- **Guarantees**: Atomic rename operations, disk durability, crash recovery across server restarts.

---

## 🛠️ Getting Started

### Prerequisites
- Python 3.11+
- Node.js 18+ & npm (for UI development)

### 1. Clone & Setup Environment

```bash
git clone https://github.com/SYNTHOS7/Nosleep.git
cd Nosleep

# Create and activate Python virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

### 2. Configure Environment (Optional)

Copy `.env.example` to `.env` to customize storage and credentials:

```bash
cp .env.example .env
```

Key environment variables:
```env
STORAGE_BACKEND=in_memory            # 'in_memory' or 'neo4j'
NEO4J_URI=neo4j+s://<instance>.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<your-password>
NEO4J_DATABASE=neo4j
CHROMA_PERSIST_DIR=./data/chroma
PORT=8080
HOST=0.0.0.0
```

### 3. Run Application

```bash
# Start unified full-stack server
python run_app.py
```
- Open browser at: **`http://localhost:8080/`**
- API Documentation: **`http://localhost:8080/docs`**

---

## 🧪 Testing & Verification

A unified runner validates all 120 test specifications across all four phases:

```bash
python test_all_phases.py
```

### Test Suite Scorecard (120/120 Passed)
- **Phase 1 (Storage Contracts & Lifecycle)**: 44/44 tests passed
- **Phase 2 (Ingestion, Extraction & Embeddings)**: 25/25 tests passed
- **Phase 3 (Topics, Retrieval, Conflicts & Hindi)**: 34/34 tests passed
- **Phase 4 (API, Gates & E2E Acceptance)**: 17/17 tests passed

---

## 📡 Core API Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Live system readiness and component health |
| `GET` | `/v1/database/status` | Real-time connectivity status of Neo4j, Chroma, and disk |
| `POST` | `/v1/database/configure` | Dynamically test and configure Neo4j Aura credentials |
| `POST` | `/v1/workspaces/{ws}/documents` | Upload a single document (`multipart/form-data` or JSON) |
| `POST` | `/v1/workspaces/{ws}/documents/batch` | Bulk upload 500+ documents or `.zip` archive bundles |
| `GET` | `/v1/workspaces/{ws}/documents` | List all ingested documents in the workspace |
| `PUT` | `/v1/workspaces/{ws}/documents/{doc_id}` | Edit an existing document revision without rebuild |
| `DELETE` | `/v1/workspaces/{ws}/documents/{doc_id}` | Delete a document and purge orphaned chunks/relations |
| `GET` | `/v1/operations/{op_id}` | Poll mutation status, timings, and extraction metrics |
| `POST` | `/v1/query` | Execute hybrid retrieval, conflict resolution, or Hindi queries |
| `GET` | `/v1/workspaces/{ws}/graph` | Retrieve full interactive graph slice with highlight paths |
| `POST` | `/v1/topics/discover` | Discover latent thematic topic clusters via HDBSCAN |

---

## 🐳 Docker Deployment

Build and run using the included production container:

```bash
# Build multi-platform image
docker build -t nosleep-knowledge-base .

# Run container on port 8080
docker run -p 8080:8080 -e PORT=8080 nosleep-knowledge-base
```

---

## 👥 Contributors

- **SYNTHOS7 Team** ([GitHub](https://github.com/SYNTHOS7))
- Developed for the **NoSleep Interactive Knowledge Base** Challenge.
