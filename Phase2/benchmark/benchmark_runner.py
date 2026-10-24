"""Scale benchmark runner for measuring 500-document ingestion throughput, stage timings, and cold/warm metrics."""

import argparse
import json
import os
import platform
import shutil
import sys
import time

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List
import numpy as np

from backend.contracts.models import OperationType
from backend.ingestion.operations import OperationManager
from backend.ingestion.pipeline import build_batch

BENCHMARK_DATA_DIR = os.path.join(os.path.dirname(__file__), "generated_corpus")


def generate_benchmark_corpus(count: int = 500, out_dir: str = BENCHMARK_DATA_DIR) -> List[Dict[str, str]]:
    """Generates a corpus of distinct PDF and TXT documents for benchmarking."""
    os.makedirs(out_dir, exist_ok=True)
    corpus = []

    domains = ["Finance", "Healthcare", "Aerospace", "Telecommunications", "Energy", "Retail", "Cybersecurity", "Automotive"]
    actions = ["uses", "depends on", "is located in", "is a part of"]

    for i in range(count):
        doc_type = "pdf" if (i % 3 == 0) else "txt"
        domain = domains[i % len(domains)]
        doc_id = f"bench-doc-{i:04d}"

        content_lines = [
            f"# Benchmark Document {i:04d} - {domain} Architecture Overview",
            f"Enterprise System_{domain}_{i} is a part of Global Core_{domain}.",
            f"Service_{domain}_{i}_Alpha uses Microservice_{domain}_{i}_Beta.",
            f"Service_{domain}_{i}_Alpha depends on Infrastructure_{domain}_{i}.",
            f"Module_{domain}_{i} has status ACTIVE.",
            f"Facility_{domain}_{i} is located in Region_{i % 5}.",
        ]

        if i % 5 == 0:
            content_lines.append(f"Subsystem_{domain}_{i} does not depend on Legacy_{domain}_{i}.")
        if i % 7 == 0:
            content_lines.append(f"Service_{domain}_{i}_Alpha uses Cache_{i} only if high availability is enabled.")

        text_content = "\n\n".join(content_lines)

        if doc_type == "txt":
            file_path = os.path.join(out_dir, f"{doc_id}.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(text_content)
        else:
            # Generate valid PDF
            file_path = os.path.join(out_dir, f"{doc_id}.pdf")
            _write_simple_pdf(file_path, content_lines)

        corpus.append({
            "doc_id": doc_id,
            "file_path": file_path,
            "source_type": doc_type,
            "domain": domain,
        })

    return corpus


def _write_simple_pdf(out_path: str, lines: List[str]):
    """Writes a valid PDF with selectable text stream."""
    safe_lines = [l.replace("(", "").replace(")", "").replace("\\", "") for l in lines]
    text_commands = []
    y = 700
    for l in safe_lines:
        text_commands.append(f"72 {y} Td ({l[:80]}) Tj -72 -20 Td")
        y -= 20

    stream_content = "BT\n/F1 10 Tf\n" + "\n".join(text_commands) + "\nET\n"
    stream_bytes = stream_content.encode("latin-1")
    length = len(stream_bytes)

    pdf_bytes = f"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj
4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
5 0 obj << /Length {length} >> stream
{stream_content}endstream
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000246 00000 n 
0000000317 00000 n 
trailer << /Size 6 /Root 1 0 R >>
startxref
{380 + length}
%%EOF
""".encode("latin-1")

    with open(out_path, "wb") as f:
        f.write(pdf_bytes)


def run_benchmark(corpus_size: int = 500, concurrency: int = 8) -> Dict[str, Any]:
    """
    Executes benchmark over corpus.
    Evaluates cold run, warm run, percentiles, stage breakdowns, and 60-second SLA adherence.
    """
    print(f"=== Starting Ingestion Scale Benchmark ({corpus_size} documents, {concurrency} threads) ===")
    corpus = generate_benchmark_corpus(count=corpus_size)

    bench_storage = os.path.join(os.path.dirname(__file__), "bench_storage")
    shutil.rmtree(bench_storage, ignore_errors=True)
    os.makedirs(bench_storage, exist_ok=True)

    op_manager = OperationManager(storage_dir=bench_storage, max_workers=concurrency)

    # 1. Cold Run
    print("Executing COLD run...")
    start_cold = time.perf_counter()
    cold_results = _execute_batch_run(corpus, op_manager, concurrency)
    cold_duration = time.perf_counter() - start_cold

    # 2. Warm Run (Cache hit verification)
    print("Executing WARM run (re-ingesting with cache)...")
    start_warm = time.perf_counter()
    warm_results = _execute_batch_run(corpus, op_manager, concurrency)
    warm_duration = time.perf_counter() - start_warm

    report = _compile_report(
        corpus=corpus,
        concurrency=concurrency,
        cold_results=cold_results,
        cold_duration=cold_duration,
        warm_results=warm_results,
        warm_duration=warm_duration,
    )

    # Save benchmark report to disk
    report_path = os.path.join(os.path.dirname(__file__), "benchmark_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    _print_summary(report)
    return report


def _execute_batch_run(
    corpus: List[Dict[str, str]], op_manager: OperationManager, concurrency: int
) -> List[Dict[str, Any]]:
    results = []

    def _process_one(item: Dict[str, str]) -> Dict[str, Any]:
        op = op_manager.create_operation(
            workspace_id="benchmark-ws",
            document_id=item["doc_id"],
            operation_type=OperationType.ADD,
            source_ref=item["file_path"],
            source_type=item["source_type"],
        )
        t0 = time.perf_counter()
        try:
            batch = build_batch(op)
            t_total = time.perf_counter() - t0
            return {
                "doc_id": item["doc_id"],
                "success": True,
                "latency": t_total,
                "stage_timings": op.stage_timings,
                "chunks": len(batch.chunks),
                "entities": len(batch.aggregated_entities),
                "relations": len(batch.aggregated_relations),
                "values": len(batch.aggregated_values),
                "vectors": len(batch.vectors),
            }
        except Exception as e:
            t_total = time.perf_counter() - t0
            return {
                "doc_id": item["doc_id"],
                "success": False,
                "latency": t_total,
                "error": str(e),
            }
        finally:
            op_manager.release_lock(op.document_id)

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_process_one, item) for item in corpus]
        for f in as_completed(futures):
            results.append(f.result())

    return results


def _compile_report(
    corpus: List[Dict[str, str]],
    concurrency: int,
    cold_results: List[Dict[str, Any]],
    cold_duration: float,
    warm_results: List[Dict[str, Any]],
    warm_duration: float,
) -> Dict[str, Any]:
    cold_successes = [r for r in cold_results if r["success"]]
    cold_latencies = [r["latency"] for r in cold_successes]
    warm_successes = [r for r in warm_results if r["success"]]
    warm_latencies = [r["latency"] for r in warm_successes]

    # Calculate percentiles
    p50 = float(np.percentile(cold_latencies, 50)) if cold_latencies else 0.0
    p90 = float(np.percentile(cold_latencies, 90)) if cold_latencies else 0.0
    p95 = float(np.percentile(cold_latencies, 95)) if cold_latencies else 0.0
    p99 = float(np.percentile(cold_latencies, 99)) if cold_latencies else 0.0

    total_chunks = sum(r.get("chunks", 0) for r in cold_successes)
    total_entities = sum(r.get("entities", 0) for r in cold_successes)
    total_relations = sum(r.get("relations", 0) for r in cold_successes)
    total_vectors = sum(r.get("vectors", 0) for r in cold_successes)

    # Average stage breakdown
    stage_breakdown = {}
    if cold_successes:
        all_stages = ["parsing", "chunk_cache", "extraction", "embeddings", "stage_batch"]
        for st in all_stages:
            stage_vals = [r.get("stage_timings", {}).get(st, 0.0) for r in cold_successes]
            stage_breakdown[st] = round(float(np.mean(stage_vals)), 4)

    return {
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "host_os": platform.system() + " " + platform.release(),
            "cpu_count": os.cpu_count(),
            "concurrency": concurrency,
            "corpus_size": len(corpus),
            "pdf_count": sum(1 for c in corpus if c["source_type"] == "pdf"),
            "txt_count": sum(1 for c in corpus if c["source_type"] == "txt"),
            "sla_target_seconds": 60.0,
        },
        "throughput": {
            "cold_total_seconds": round(cold_duration, 2),
            "cold_docs_per_second": round(len(cold_results) / max(0.001, cold_duration), 2),
            "warm_total_seconds": round(warm_duration, 2),
            "warm_docs_per_second": round(len(warm_results) / max(0.001, warm_duration), 2),
            "cache_speedup_factor": round(cold_duration / max(0.001, warm_duration), 2),
        },
        "latency_percentiles_seconds": {
            "p50": round(p50, 4),
            "p90": round(p90, 4),
            "p95": round(p95, 4),
            "p99": round(p99, 4),
            "within_60s_sla": p95 <= 60.0,
        },
        "stage_durations_mean_seconds": stage_breakdown,
        "resource_totals": {
            "successful_documents": len(cold_successes),
            "failed_documents": len(cold_results) - len(cold_successes),
            "total_chunks": total_chunks,
            "total_entities": total_entities,
            "total_relations": total_relations,
            "total_vectors": total_vectors,
        },
    }


def _print_summary(rep: Dict[str, Any]):
    meta = rep["metadata"]
    tp = rep["throughput"]
    pct = rep["latency_percentiles_seconds"]
    res = rep["resource_totals"]

    print("\n================== BENCHMARK REPORT SUMMARY ==================")
    print(f"Corpus Size: {meta['corpus_size']} docs ({meta['pdf_count']} PDF, {meta['txt_count']} TXT)")
    print(f"Concurrency: {meta['concurrency']} threads on {meta['cpu_count']} CPUs")
    print(f"Cold Throughput: {tp['cold_docs_per_second']} docs/sec (Total: {tp['cold_total_seconds']}s)")
    print(f"Warm Throughput: {tp['warm_docs_per_second']} docs/sec (Speedup: {tp['cache_speedup_factor']}x)")
    print(f"Latency Percentiles: p50={pct['p50']}s, p90={pct['p90']}s, p95={pct['p95']}s, p99={pct['p99']}s")
    print(f"60-Second SLA Met: {pct['within_60s_sla']} (p95 {pct['p95']}s <= 60.0s)")
    print(f"Knowledge Graph Created: {res['total_entities']} entities, {res['total_relations']} relations, {res['total_vectors']} vectors")
    print("==============================================================\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run scale benchmark")
    parser.add_argument("--count", type=int, default=500, help="Number of documents to test")
    parser.add_argument("--concurrency", type=int, default=8, help="Concurrency level")
    args = parser.parse_args()

    run_benchmark(corpus_size=args.count, concurrency=args.concurrency)
