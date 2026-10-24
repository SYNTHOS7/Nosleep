"""Generate canonical JSON Schema and TypeScript declarations."""

from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    subprocess.run([sys.executable, "-m", "backend.contracts.generate"], cwd=ROOT, check=True)
    npm = "npm.cmd" if os.name == "nt" else "npm"
    subprocess.run([npm, "run", "generate:types"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
