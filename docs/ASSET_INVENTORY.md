# Asset inventory and route review order

Open Asset inventory & route priority in the workbench. Record exact graph entity names, business criticality, declared exposure, owner and notes. The service matches names case-insensitively; it does not infer aliases or discover hosts. A record without graph evidence is allowed and labeled unmatched.

All context is analyst-supplied and unverified. It does not change source assertions, create network links or establish exploitability. Route assessment uses the existing directed evidence traversal and retains its source quotes, chunk IDs and path IDs. Negative, uncertain, conditional and disputed links remain excluded.

## Transparent review ordering

The method is review-order-v1, an ordinal triage aid, not CVSS or a risk probability:

- Unknown target criticality: unassessed, with missing context shown.
- High/critical target criticality: review first.
- Medium target criticality and an internet-exposed entry: review first.
- Other known target criticalities: review next.

Review-first routes appear before unassessed routes, followed by review-next routes. Within a band, declared target criticality breaks ties. Entry exposure is taken only from the entry's exact inventory record; a CVE entry may therefore have unknown exposure. Declared isolation is flagged for comparison with cited connectivity; it does not silently remove evidence. Every route keeps exploitability=not_determined and a checklist for current connectivity, versions/patches, prerequisites, privileges and effective controls. No remediation executes.

## Storage and access

SQLite and Neon adapters persist inventory separately from extracted evidence. Rerun the explicit Neon schema setup before using this feature with a pre-existing hosted database. In-memory demo mode keeps inventory only for that process. User deletions remove analyst context, not source documents or graph evidence.

Workspace viewers can list context and assess routes. Editors/admins can create, edit and remove context. The server stamps the current actor and UTC update time. Updates/deletes require the current version and opaque instance token. This prevents stale edits and stale deletes after an asset has been removed and recreated. Concurrent creates use atomic database constraints rather than last-write-wins. A 409 response requires refreshing and selecting the current record.

API routes: GET/PUT /v1/workspaces/{ws}/assets; DELETE /v1/workspaces/{ws}/assets/{asset_id}?expected_version=...&expected_token=...; GET /v1/workspaces/{ws}/route-assessment?entry_point=....

Verification includes real SQLite restart and concurrent-write tests, Neon SQL contract tests with a test double, route provenance checks, exclusion of unsafe edges and API role isolation. Live Neon verification remains pending connection. This feature does not provide a CMDB connector, automatic exposure validation, attack simulation or proof of exploitability. Downloaded investigation reports remain evidence reports; this manual inventory context is a separate view.
