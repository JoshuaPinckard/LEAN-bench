"""Shared paths, task access, and the append-only run ledger (PLAN.md 1.5)."""
import json
import threading
from pathlib import Path

HERE = Path(__file__).parent
AUDIT = HERE.parent
REPO = AUDIT / "QuantCode-Bench"
FROZEN = AUDIT / "frozen_cache"
PROMPTS = AUDIT / "prompts"
RESULTS = AUDIT / "results"
LEDGER = RESULTS / "ledger.jsonl"

_ledger_lock = threading.Lock()


def load_tasks(scope: str = "census"):
    """Task list keyed by id.

    scope='census' (default since the owner's 2026-08-19 full-corpus ruling):
    ALL 400 QuantCode-Bench tasks, text from the bench's own frozen corpus
    file - the same source census/phase1_census.py used.
    scope='pilot': the original 20-task sample (kept for the pilot redo)."""
    if scope == "pilot":
        data = json.loads((AUDIT / "sample_20_final.json").read_text(encoding="utf-8"))
        return {t["id"]: t for t in data["tasks"]}
    tasks = json.loads((REPO / "data" / "benchmark_tasks_multiframe.json").read_text(encoding="utf-8"))
    return {t["id"]: t for t in tasks}


def load_requirements():
    reqs = json.loads((REPO / "data" / "task_data_requirements.json").read_text(encoding="utf-8"))
    return {r["task_id"]: r for r in reqs}


def safe_name(symbol: str) -> str:
    return symbol.replace("=", "_").replace("^", "_")


def cache_path_for(task) -> Path:
    """Frozen pickle for a task's data binding (D2: requirements file wins)."""
    reqs = load_requirements()
    r = reqs.get(task["id"])
    sym = r["yf_symbol"] if r else task["yf_symbol"]
    tf = r["timeframe"] if r else task["timeframe"]
    p = FROZEN / f"{safe_name(sym)}_{tf}.pkl"
    if not p.exists():
        raise FileNotFoundError(f"frozen cache missing for task {task['id']}: {p}")
    return p


def ledger_key(rec) -> str:
    return "|".join(str(rec[k]) for k in ("phase", "task_id", "role", "model", "sample_idx"))


def ledger_load():
    if not LEDGER.exists():
        return {}
    out = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            out[ledger_key(rec)] = rec
    return out


def ledger_append(rec):
    RESULTS.mkdir(exist_ok=True)
    with _ledger_lock:
        with open(LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
