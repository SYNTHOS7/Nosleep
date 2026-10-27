# Local AI and offline intelligence

The default local launcher remains a fast hash/rule demo. `./start_local_ai.ps1` starts a separate real-AI workspace at http://127.0.0.1:8004 using Ollama models already installed on this computer:

- qwen2.5-coder:7b for schema-constrained entity/relation extraction.
- nomic-embed-text:latest for learned 768-dimensional document/query embeddings.

No cloud account, API key, automatic model download or remote fallback is used. Ollama must run locally at http://127.0.0.1:11434. The adapter accepts HTTP loopback addresses only, ignores proxy environment settings and rejects redirects. The AI launcher disables external PDF parsing and LangSmith tracing. If a model is missing or fails, ingestion/query fails rather than quietly using hash vectors or cloud inference.

AI data uses data/aegis-local-ai.sqlite3, ai-uploads and ai-operations. The rule/hash demo uses separate files. Each completed batch records its embedding profile including the installed model digest. Startup, ingestion and query checks reject mismatched vector spaces. To change embedding models, use a fresh database or explicitly re-ingest the corpus; there is no automatic destructive reindex. Models updated during an embedding call are rejected. Keep model tags unchanged during a running session.

## Grounding boundaries

The language model has no tools or command execution. JSON schema validation, exact quote matching, endpoint-name checks and predicate vocabulary cues constrain its output. Negation and uncertainty cues prevent affirmative certain attack edges. Extraction cache keys include workspace, chunk, revision, model and prompt identity. These controls do not prove model interpretation is always correct; inspect the exact source quotes. Indirect/pronominal relations may be dropped deliberately. Scanner/catalog imports keep their dedicated deterministic adapters.

The LangGraph investigation remains a deterministic coordinator over retrieved evidence and graph paths. Answers are still evidence excerpts; free-form model answer synthesis and autonomous remediation are not implemented. Local model inference can be slow and resource intensive; the AI launcher uses one ingestion worker. Health labels indicate configuration, not a general model-quality certification.

## Offline threat catalogs

Upload one `*.nvd.json` NVD 2.0 response or `*.stix.json` STIX 2.0/2.1 bundle in the Corpus panel. POST /v1/workspaces/{ws}/imports/intel?format=nvd or stix is also available. Maximum 5 MiB and 5000 supported records; use slices for large official catalogs. Imports preserve supported record fields, deduplicate equivalent snapshots, and index explicit CVE and ATT&CK technique IDs. They never fetch external links or infer environment-specific exploit routes. Publisher authenticity remains unverified. Unsupported types and relationships remain passive source text; this is not a full STIX graph implementation.

## Verification on this machine

The existing local models were used, with no downloads. A real embedding check produced 768 dimensions and cosine similarity 0.879 for two car/road sentences versus 0.439 for an unrelated baking sentence. This is a small sanity check, not a general benchmark. Real structured extraction preserved affirmative, negative and possible claims. A live API upload produced two directed routes from Edge_Gateway via Auth_Service to Customer_Database; negative Backup_Vault access and uncertain Test_Server access were excluded. Source quotes and model profiles were inspected.

The required four-phase suite remains the default offline regression check. Model-independent tests cover loopback restrictions, no-fallback behavior, vector dimensions, profile isolation, quote/modality guards, cache isolation and both catalog formats. Live model checks are separate and hardware-dependent.

Sources: https://docs.ollama.com/api/embed, https://docs.ollama.com/api/chat, https://docs.ollama.com/capabilities/structured-outputs, https://ollama.com/library/nomic-embed-text, https://nvd.nist.gov/developers/vulnerabilities and https://github.com/mitre-attack/attack-stix-data.
