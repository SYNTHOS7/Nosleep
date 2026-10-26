"""Explicit operator schema setup; never runs DDL during normal API startup."""
from pathlib import Path
from backend.storage.neon_store import NeonStore


def main():
    path = Path(__file__).resolve().parents[3] / "sql" / "neon_schema.sql"
    with NeonStore().connection() as conn:
        conn.execute(path.read_text(encoding="utf-8"))
    print("AegisGraph PostgreSQL schema is ready.")


if __name__ == "__main__":
    main()
