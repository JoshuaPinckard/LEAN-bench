$env:LEAN_BIN = ".\venv\Scripts\lean.exe"
$env:LEAN_WORKSPACE = ".\lean_workspace"

# --reload-dir restricts the file watcher to source directories only.
# Without this, uvicorn watches the whole cwd — and every backtest writes a
# `main.py` into lean_workspace/leanbench_*/, which triggers a reload that
# kills the in-flight /api/generate request (browser sees ERR_FAILED + a
# misleading CORS error because the connection dies before any response
# headers are sent). --reload-exclude alone is not reliable for this on
# Windows; explicit --reload-dir is.
.\venv\Scripts\python.exe -m uvicorn backend.app:app `
    --reload `
    --reload-dir backend `
    --reload-dir harness `
    --port 8010
