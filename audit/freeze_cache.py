"""Build and FREEZE the market-data cache for the 20 audit tasks (PLAN.md D10 / 1.3).

Downloads each needed (yf_symbol, timeframe) pair once, using QuantCode-Bench's own
download windows (scripts/build_cache.py:download_pair, imported directly so the
windows can't drift), then:
  - writes the pickle to frozen_cache/<safe>_<tf>.pkl   (audit ground-truth copy)
  - copies it to QuantCode-Bench/data/cache/            (so their stack resolves it)
  - records sha256 / rows / index range / tz in frozen_cache/cache_manifest.json

Applies the D1 replacement policy: if a pair can't be downloaded, the affected task
is swapped for the next same-difficulty task from the seeded replacement queue, and
the swap is logged. Writes sample_20_final.json (the definitive audit task list).

Idempotent: existing frozen pickles are kept, only missing pairs are downloaded.
"""
import hashlib
import importlib.util
import json
import pickle
import shutil
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE / "QuantCode-Bench"
FROZEN = HERE / "frozen_cache"
THEIR_CACHE = REPO / "data" / "cache"

spec = importlib.util.spec_from_file_location("build_cache", REPO / "scripts" / "build_cache.py")
build_cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_cache)

FROZEN.mkdir(exist_ok=True)
THEIR_CACHE.mkdir(parents=True, exist_ok=True)

sample = json.loads((HERE / "sample_20.json").read_text(encoding="utf-8"))
all_tasks = {t["id"]: t for t in json.loads((HERE / "sample_A.json").read_text(encoding="utf-8"))}
reqs = {r["task_id"]: r for r in json.loads(
    (REPO / "data" / "task_data_requirements.json").read_text(encoding="utf-8"))}


def safe_name(symbol: str) -> str:
    return symbol.replace("=", "_").replace("^", "_")


def pair_of(task):
    """Data binding per D2: prefer task_data_requirements.json, cross-check task fields."""
    r = reqs.get(task["id"])
    if r and (r["yf_symbol"] != task["yf_symbol"] or r["timeframe"] != task["timeframe"]):
        print(f"  NOTE task {task['id']}: requirements bind {r['yf_symbol']}@{r['timeframe']} "
              f"but task says {task['yf_symbol']}@{task['timeframe']} — using requirements")
        return r["yf_symbol"], r["timeframe"]
    return task["yf_symbol"], task["timeframe"]


pair_status = {}  # (symbol, tf) -> bool


def ensure_pair(symbol: str, tf: str) -> bool:
    key = (symbol, tf)
    if key in pair_status:
        return pair_status[key]
    dst = FROZEN / f"{safe_name(symbol)}_{tf}.pkl"
    if dst.exists():
        pair_status[key] = True
        return True
    print(f"downloading {symbol}@{tf} ...", flush=True)
    df = build_cache.download_pair(symbol, tf)
    ok = df is not None and len(df) > 0
    if ok:
        with open(dst, "wb") as f:
            pickle.dump(df, f)
        print(f"  OK {len(df)} bars {df.index[0]} .. {df.index[-1]}")
    else:
        print(f"  FAILED {symbol}@{tf}")
    pair_status[key] = ok
    return ok


final, swaps = [], []
queues = {d: list(ids) for d, ids in sample["replacement_queues"].items()}

for task in sample["tasks"]:
    cur = task
    while True:
        sym, tf = pair_of(cur)
        if ensure_pair(sym, tf):
            final.append(cur)
            break
        q = queues[cur["difficulty"]]
        if not q:
            raise SystemExit(f"replacement queue for {cur['difficulty']} exhausted at task {cur['id']}")
        repl = all_tasks[q.pop(0)]
        swaps.append({"out": cur["id"], "in": repl["id"], "reason": f"no data for {sym}@{tf}"})
        print(f"SWAP: task {cur['id']} -> {repl['id']} (no data for {sym}@{tf})")
        cur = repl

manifest = {}
for pkl_file in sorted(FROZEN.glob("*.pkl")):
    with open(pkl_file, "rb") as f:
        raw = f.read()
    df = pickle.loads(raw)
    manifest[pkl_file.name] = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "rows": len(df),
        "index_min": str(df.index[0]),
        "index_max": str(df.index[-1]),
        "tz": str(getattr(df.index, "tz", None)),
        "columns": list(df.columns),
    }
    shutil.copy2(pkl_file, THEIR_CACHE / pkl_file.name)

(FROZEN / "cache_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
(HERE / "sample_20_final.json").write_text(json.dumps({
    "source": "sample_20.json",
    "swaps": swaps,
    "selected_ids": [t["id"] for t in final],
    "tasks": final,
}, indent=2), encoding="utf-8")

print(f"\nfrozen pairs: {len(manifest)}; swaps: {len(swaps)}")
print("final ids:", [t["id"] for t in final])
