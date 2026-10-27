# Start the complete app with local SQLite persistence; no cloud credentials needed.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:VECTOR_BACKEND = 'local'
$env:AUTH_MODE = 'demo'
$env:APP_ENV = 'development'
$env:RENDER = 'false'
$env:NEO4J_URI = ''
$env:CHROMA_MIRROR_ENABLED = 'false'
$env:LOCAL_DATABASE_PATH = Join-Path $PSScriptRoot 'data/aegis-local.sqlite3'
$env:SERVE_FRONTEND = 'true'
$env:HOST = '127.0.0.1'
$env:PORT = '8000'
$pythonPath = Join-Path $PSScriptRoot 'Phase4/.venv/Scripts/python.exe'
if (Test-Path -LiteralPath $pythonPath) {
    & $pythonPath run_app.py
} else {
    python run_app.py
}
exit $LASTEXITCODE
