# Deterministic identifier serialization

Hash-based identifiers use SHA-256 over the UTF-8 bytes of canonical JSON.

- Object keys are sorted lexicographically.
- JSON uses compact separators: `,` and `:` without insignificant whitespace.
- Unicode is emitted directly (`ensure_ascii=false`).
- Numbers must be finite; `NaN` and infinities are rejected.
- Datetimes must be timezone-aware UTC and serialize with a trailing `Z`.
- Enums serialize as their string values; UUIDs serialize as strings.
- Arrays retain order; object keys must be strings.

The ID helper input payloads are deliberately explicit in `ids.py`: revisions include
the logical document ID, content hash, and pipeline configuration; chunks include
revision, index, text hash, and location; entities include workspace/type/normalized
name; relations include endpoints, qualifiers, and exact evidence; mentions include
their entity, revision, chunk, and exact span.

Regenerate committed interface artifacts with:

```powershell
python scripts/generate_contracts.py
```

Run the offline contract suite with:

```powershell
python -m pytest
```
