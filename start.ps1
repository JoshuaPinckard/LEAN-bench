$env:LEAN_BIN = ".\venv\Scripts\lean.exe"
$env:LEAN_WORKSPACE = ".\lean_workspace"

.\venv\Scripts\python.exe -m uvicorn backend.app:app --reload --reload-exclude "lean_workspace"