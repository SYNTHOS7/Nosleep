# Repository review — final feature scope

The feature scope is frozen after repository review. Further work focuses on defects, accuracy, usability, tests, security, deployment and operational reliability. Do not add integrations or product features without an explicit change of scope.

## Local workflow

Open Repository investigation. Provide a public https://github.com/owner/repository URL, or a repository ZIP. GitHub imports resolve the default branch to a full commit SHA before downloading that immutable snapshot. ZIP uploads use an archive SHA256, not a claimed Git identity. No private GitHub credentials are collected.

The results show source coverage, candidate findings, exact file and line locations, code-line hashes, suggested changes and unresolved assumptions. GitHub findings link to code at the pinned commit. Source contents are not persisted, to avoid retaining secrets. Download JSON for the review and source manifest. Rescan and compare the latest two records from the same origin/ruleset. Identity uses path, rule and line content, tolerating line-number shifts. Changed lines appear as new/disappeared candidates; disappearance is not proof of remediation. Uploaded ZIP identity is user-provided context: comparing unrelated ZIPs is possible and must be avoided.

## Coverage and limits

Five rules: Python dynamic execution, shell=True subprocess calls, pickle loading, disabled requests/httpx TLS verification, and JSX raw HTML rendering. Python uses AST and basic import alias resolution. JS/TS uses one narrow line-pattern rule which can match comments or strings. Python route declarations are candidates only. This is not whole-codebase semantic understanding, taint analysis, verified reachability, vulnerability dependency scanning, secret scanning, or runtime exploitation. Findings are not attached to graph attack paths because the current analyzer cannot prove those edges. No severity or exploitability score is invented. Scanner report imports remain available separately.

## Boundaries

Read-only source handling; no checkout, hooks, builds, package installs or repository execution. Public GitHub endpoints only, no user-controlled hosts, redirects, proxy credentials or private tokens. 60-second download budget, network timeouts, 10 MiB compressed / 20 MiB expanded, 5,000 ZIP entries, 300 KB per supported file, 1,000 candidates. Unsafe paths, symlinks, encrypted entries and malformed archives are rejected. Unsupported/generated files are skipped and Python parse failures are shown. External requests go only to GitHub API/codeload. GitHub rate limits and oversized repositories may require a smaller ZIP.

Workspace readers can inspect history/compare. Editors can import. SQLite and Neon persist records, with the latest 20 exposed in the UI. Reapply sql/neon_schema.sql before using an existing hosted database. Memory mode is ephemeral. Raw code is not retained and review records currently need an operator retention policy. Cloud connectivity, large-scale load, deep analysis accuracy and hosted security remain unverified. This delivery is not a production certification.
