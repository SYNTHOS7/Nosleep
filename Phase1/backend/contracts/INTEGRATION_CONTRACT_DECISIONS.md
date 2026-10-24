# Task 1 integration-contract decisions

These additive Pydantic v2 contracts are transport boundaries for Tasks 2, 3,
and 4. They do not replace the 13 canonical storage models or `EntityMention`.
Every model rejects unknown fields. Local, structural validation is performed
by Pydantic; workspace ownership, active-revision checks, semantic conflict
validation, and publication checks that require persisted state remain Task 1
repository/lifecycle responsibilities and are deliberately not implemented by
this milestone.

Pydantic JSON Schema and generated TypeScript declarations describe fields and
primitive constraints only. They do not replace runtime Pydantic validation for
cross-field rules (for example endpoint XOR and deterministic IDs) or
cross-record rules (for example source provenance and package closure).

## Ownership and local boundaries

- **Task 2** produces `ExtractionBatch`. It supplies one document revision's
  chunks, entities, mentions, values, source relations, and exactly one finite,
  non-zero vector per chunk. `embedding_dimension` is positive and every vector
  has that exact length. The batch locally enforces shared workspace/document/
  revision provenance and reference closure. Task 1 later verifies repository
  ownership and stores/routs those vectors; Task 2 owns embedding generation.
- **Task 1** creates `CorpusSnapshot` from Neo4j's authoritative workspace
  publication state. It contains only workspace, epoch, active revision IDs,
  and a UTC capture time. The approved sources do not define embedding-profile
  fields as snapshot fields. An active embedding profile remains a repository
  policy, not an invented transport field.
- **Task 3** supplies `DerivedDelta` against a `CorpusSnapshot`; it can stage
  topics, memberships, pair-level conflicts, and explicit conflict IDs to
  retire. Task 1 is the only publisher. Local validation allows memberships
  only for snapshot-active or the named staged revision; repository validation
  later checks workspace, expected epoch, source evidence, and whether a
  retirement would remove a conflict still supported in the resulting snapshot.
- **Task 4** consumes `EvidencePackage`. It must authorize the workspace before
  requesting source content. The package is partial only in the sense that
  unrelated records may be omitted; all supplied references must close inside
  the package and belong to its snapshot.

## Identities and provenance

`Value.id` is SHA-256 of canonical JSON with `workspace_id`, `kind`,
`normalized_value`, and `unit`. Values must already be normalized by the
upstream producer; this helper intentionally performs no numeric, date, or
unit normalization. Unit normalization is therefore an upstream responsibility.

`Conflict.id` is SHA-256 of canonical JSON with `workspace_id`, `kind`, and
the two relation IDs lexicographically sorted. The persisted left/right fields
must use that same order. Detector state, explanation, evidence listing, and
detector version are excluded because they are mutable. A matching deterministic
ID prevents duplicate representations of a pair; it does not prove that the
relations contradict. Task 1 later validates pair workspace/evidence and a
retirement request against the resulting publication snapshot. The current
`Conflict` schema models only one relation pair, so alternate pair support is
represented by distinct conflict records rather than silently added fields.

`EvidencePath.id` is SHA-256 of canonical JSON with `workspace_id`,
`snapshot_epoch`, and ordered `EvidencePathStep` records. Each step preserves
the source relation endpoints, direction, evidence chunk, revision, and
document. Adjacent traversal endpoints must connect. Paths therefore have a
new ID after a corpus epoch changes, which makes citations snapshot-specific.
Topic memberships are derived metadata and never path steps.

Contract instances are frozen to prevent ordinary field reassignment. Python
containers inside a frozen model can still be mutated, so Task 1 provides
`revalidate_extraction_batch`, `revalidate_evidence_path`, and
`revalidate_evidence_package`. Repositories/services must call the relevant
helper whenever a contract crosses a mutable trust boundary. For standalone
paths, repositories must additionally call `validate_evidence_path_provenance`
with the relation/chunk/revision/document records they retrieved under their
workspace and active-revision filters. The helper deliberately does not query a
database or claim that a model alone can validate records it was not supplied.

## Publication and evidence limitations

`PublishReceipt` describes only the authoritative Neo4j publication outcome.
It requires staged-vector verification before a new active revision, but it
does not claim cross-store atomicity. Cleanup and read-probe requirements are
reported separately from whether Neo4j publication occurred.

`EvidencePackage` includes conflicts and checks document/revision/chunk,
mention, relation, topic-membership, conflict, and path reference closure.
When `truncated` is true, both available and searched chunk counts are required.
`Topic.summary_evidence_ids` is intentionally not interpreted or validated:
its referent type remains unresolved and is not a blocker for these contracts.
