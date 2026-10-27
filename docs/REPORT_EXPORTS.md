# Investigation report downloads

After running an investigation, choose Download report for a portable UTF-8 text file or Download JSON for structured evidence. No cloud storage or account is needed in local mode. Downloads use the authenticated API when login is enabled.

GET /v1/workspaces/{ws}/investigation/report?entry_point=...&format=txt or json generates a fresh investigation snapshot. It may differ from an earlier on-screen result. Existing workspace read permissions apply; other workspaces are denied. Successful downloads are recorded in metadata-only request audit history when persistent request controls are enabled.

Reports contain exact source quotes, document/chunk IDs, revisions, pages, offsets, potential path IDs and both sides of returned conflicts. Each path hop references a source entry. Before sending the file, the server checks the workspace document revision set and verifies quote spans against current source chunks. A changed workspace or unsupported quote returns HTTP 409 rather than an inconsistent report.

The text format prefixes every source-data line with > and is delivered as a plain-text attachment with no-store/nosniff headers. It does not render HTML or execute embedded instructions. Downloads include workspace source data: review the file before sharing it. This is not automatic secret redaction.

The workspace checksum identifies the document revision set, not the entire application state. It is not a digital signature, tamper-proof audit or proof of publisher authenticity. Reports do not establish exploitability, execute remediation or create persistent report history on the server. Empty evidence is represented explicitly and does not certify the environment as safe.

Verified with regression checks for exact quote offsets, route citation coverage, opposing claims, workspace authorization, changed revisions and fabricated evidence rejection. The full four-phase suite and frontend checks are required before release.
