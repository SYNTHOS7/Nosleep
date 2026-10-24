import subprocess
import sys
from pathlib import Path

from backend.contracts.generate import generate_schema

ROOT = Path(__file__).parents[2]


def test_generated_artifacts_are_current() -> None:
    generated = ROOT / "generated"
    expected_schema = generated / "contracts.schema.json"
    expected_types = generated / "contracts.d.ts"
    temporary_schema = ROOT / ".pytest_contracts.schema.json"
    temporary_types = ROOT / ".pytest_contracts.d.ts"
    try:
        generate_schema(temporary_schema)
        json2ts = ROOT / "node_modules" / ".bin" / ("json2ts.cmd" if sys.platform == "win32" else "json2ts")
        subprocess.run(
            [str(json2ts), "--input", str(temporary_schema), "--output", str(temporary_types)],
            cwd=ROOT,
            check=True,
        )
        assert expected_schema.read_text(encoding="utf-8") == temporary_schema.read_text(encoding="utf-8")
        assert expected_types.read_text(encoding="utf-8") == temporary_types.read_text(encoding="utf-8")
    finally:
        temporary_schema.unlink(missing_ok=True)
        temporary_types.unlink(missing_ok=True)
