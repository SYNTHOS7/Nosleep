# Uses models already installed in Ollama; no cloud account or automatic model pull.
param([int]$Port = 8004)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:VECTOR_BACKEND = 'local'
$env:AUTH_MODE = 'demo'
$env:APP_ENV = 'development'
$env:RENDER = 'false'
$env:NEO4J_URI = ''
$env:UNSTRUCTURED_API_KEY = ''
$env:UNSTRUCTURED_API_URL = ''
$env:LANGSMITH_TRACING = 'false'
$env:LANGCHAIN_TRACING_V2 = 'false'
$env:EMBEDDING_PROVIDER = 'ollama'
$env:EXTRACTOR_PROVIDER = 'ollama'
$env:OLLAMA_URL = 'http://127.0.0.1:11434'
$env:OLLAMA_EMBED_MODEL = 'nomic-embed-text:latest'
$env:OLLAMA_EXTRACT_MODEL = 'qwen2.5-coder:7b'
$env:INGEST_WORKERS = '1'
$env:LOCAL_DATABASE_PATH = Join-Path $PSScriptRoot 'data/aegis-local-ai.sqlite3'
$env:UPLOAD_DIR = Join-Path $PSScriptRoot 'data/ai-uploads'
$env:OPERATIONS_DIR = Join-Path $PSScriptRoot 'data/ai-operations'
$env:SERVE_FRONTEND = 'true'
$env:HOST = '127.0.0.1'
$env:PORT = "$Port"
$pythonPath = Join-Path $PSScriptRoot 'Phase4/.venv/Scripts/python.exe'
if (Test-Path -LiteralPath $pythonPath) { & $pythonPath run_app.py }
else { python run_app.py }
exit $LASTEXITCODE
