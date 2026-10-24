"""
Unified Application Entrypoint for the Interactive Knowledge Base Product.
Combines all 4 phases:
- Phase 1: Storage Contracts & Transactional Lifecycle (Graph & Vector Repositories)
- Phase 2: Ingestion Pipeline (PDF/TXT Parsing, 600-Token Chunking, Extraction, Embeddings)
- Phase 3: Thematic Topic Clustering, Grounded Retrieval Fusion, Conflicts & Hindi Queries
- Phase 4: FastAPI REST API, Evaluation Runner & Split-Screen Interactive UI
"""

import os
import sys
import argparse

# Add Phase4 and root to Python path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
PHASE4_DIR = os.path.join(ROOT_DIR, "Phase4")
if PHASE4_DIR not in sys.path:
    sys.path.insert(0, PHASE4_DIR)

import uvicorn

def main():
    default_port = int(os.environ.get("PORT", 8080))
    default_host = os.environ.get("HOST", "0.0.0.0")

    parser = argparse.ArgumentParser(description="Interactive Knowledge Base — Full Product Runner")
    parser.add_argument("--host", default=default_host, help=f"Host IP to bind (default: {default_host})")
    parser.add_argument("--port", type=int, default=default_port, help=f"Port to bind (default: {default_port})")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    # Final port/host priority
    port = int(os.environ.get("PORT", args.port))
    host = os.environ.get("HOST", args.host)

    print(f"==================================================================")
    print(f" Starting Interactive Knowledge Base — Unified Product")
    print(f" Serving on: http://{host}:{port}")
    print(f" API Docs:   http://{host}:{port}/docs")
    print(f" Web UI:     http://{host}:{port}/")
    print(f"==================================================================")

    uvicorn.run("backend.app:app", host=host, port=port, reload=args.reload)

if __name__ == "__main__":
    main()
