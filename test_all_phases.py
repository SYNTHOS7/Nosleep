"""
Master Test Runner across all 4 phases of the Interactive Knowledge Base.
Runs unit and integration test suites for:
- Phase 1: Storage Contracts & Lifecycle
- Phase 2: Ingestion & Extraction Pipeline
- Phase 3: Topics, Grounded Retrieval & Conflicts
- Phase 4: API, UI & End-to-End Acceptance Gates
"""

import os
import sys
import subprocess
import time

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(ROOT_DIR, "Phase4", ".venv", "Scripts", "python.exe")

if not os.path.exists(VENV_PYTHON):
    VENV_PYTHON = sys.executable

def run_suite(title: str, cmd: list, cwd: str) -> bool:
    print(f"\n{'='*70}")
    print(f" RUNNING: {title}")
    print(f" Command: {' '.join(cmd)}")
    print(f" Working Directory: {cwd}")
    print(f"{'='*70}\n")
    start = time.time()
    res = subprocess.run(cmd, cwd=cwd)
    duration = time.time() - start
    status = "PASSED" if res.returncode == 0 else "FAILED"
    print(f"\n>>> [{status}] {title} in {duration:.2f}s\n")
    return res.returncode == 0

def main():
    print(f"==================================================================")
    print(f" Interactive Knowledge Base — Unified 4-Phase Test Runner")
    print(f" Python Interpreter: {VENV_PYTHON}")
    print(f"==================================================================")

    results = {}

    # Phase 1: Contracts & Storage Lifecycle
    results["Phase 1 (Contracts & Storage Lifecycle)"] = run_suite(
        "Phase 1: Contracts and Storage Lifecycle Tests",
        [VENV_PYTHON, "-m", "pytest", "tests", "-v"],
        cwd=os.path.join(ROOT_DIR, "Phase1")
    )

    # Phase 2: Ingestion, Extraction & Embeddings
    results["Phase 2 (Ingestion, Extraction & Embeddings)"] = run_suite(
        "Phase 2: Ingestion and Pipeline Tests",
        [VENV_PYTHON, "-m", "pytest", "tests", "-v"],
        cwd=os.path.join(ROOT_DIR, "Phase2")
    )

    # Phase 3: Topics, Retrieval, Conflicts & Hindi
    results["Phase 3 (Topics, Retrieval, Conflicts & Hindi)"] = run_suite(
        "Phase 3: Topic Clustering and Retrieval Tests",
        [VENV_PYTHON, "run_all_tests.py"],
        cwd=os.path.join(ROOT_DIR, "Phase3")
    )

    # Phase 4: API, UI, Gates & E2E Requirements
    results["Phase 4 (API, UI & End-to-End Acceptance)"] = run_suite(
        "Phase 4: API, Gates and E2E Acceptance Tests",
        [VENV_PYTHON, "-m", "pytest", "tests", "-v"],
        cwd=os.path.join(ROOT_DIR, "Phase4")
    )

    print(f"\n{'='*70}")
    print(f" UNIFIED 4-PHASE TEST SCORECARD")
    print(f"{'='*70}")
    all_passed = True
    for phase, passed in results.items():
        status = "PASSED" if passed else "FAILED"
        if not passed:
            all_passed = False
        print(f" - {phase:<50} [{status}]")
    print(f"{'='*70}")

    if all_passed:
        print(" SUCCESS: All 4 phases are fully connected and verified passing!")
        sys.exit(0)
    else:
        print(" FAILURE: One or more test suites failed.")
        sys.exit(1)

if __name__ == "__main__":
    main()
