"""Seeded, stratified draw of 20 audit tasks from sample_A.json (pre-registered in PLAN.md D1).

Quota: 10 easy / 6 medium / 4 hard, seed 20260712.
Within each stratum: sort by id ascending, random.Random(SEED).sample(stratum, k).
Replacement queues (for dead-data swaps, D1): the stratum remainder shuffled by
the same continuing RNG stream.

Writes sample_20.json with the draw, queues, and input-file hash.
"""
import hashlib
import json
import random
from pathlib import Path

HERE = Path(__file__).parent
SEED = 20260712
QUOTA = {"easy": 10, "medium": 6, "hard": 4}

src = (HERE / "sample_A.json").read_bytes()
tasks = json.loads(src.decode("utf-8"))

rng = random.Random(SEED)
selected, queues = [], {}
for diff, k in QUOTA.items():
    stratum = sorted((t for t in tasks if t["difficulty"] == diff), key=lambda t: t["id"])
    picked = rng.sample(stratum, k)
    picked_ids = {t["id"] for t in picked}
    rest = [t for t in stratum if t["id"] not in picked_ids]
    rng.shuffle(rest)
    selected.extend(picked)
    queues[diff] = [t["id"] for t in rest]

selected.sort(key=lambda t: t["id"])

out = {
    "seed": SEED,
    "quota": QUOTA,
    "sample_A_sha256": hashlib.sha256(src).hexdigest(),
    "selected_ids": [t["id"] for t in selected],
    "replacement_queues": queues,
    "tasks": selected,
}
(HERE / "sample_20.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

print("selected ids:", out["selected_ids"])
print("pairs needed:", sorted({(t["yf_symbol"], t["timeframe"]) for t in selected}))
print("difficulty counts:", {d: sum(1 for t in selected if t["difficulty"] == d) for d in QUOTA})
