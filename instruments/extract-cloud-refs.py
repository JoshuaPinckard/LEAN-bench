"""Extract the v2 cloud reference implementations into the audit's ref format.

The 60 audit-ref cloud tasks (v2 template: commit ref_impl.md) probe the
HARNESS SENSITIVITY of the audit's determinacy screen: do reference
implementations from the agentic cloud harness carry different assumptions
than the API panel's references on the same tasks? This extracts each
envelope's committed ref_impl.md into audit/results/refs_cloud/ as
task<id>_cloud.json with {task_id, model, code, assumptions, template_sha256,
cloud_task_id}. Tapes require execution through the audit driver and are NOT
produced here; every output records tape: null so nothing downstream can
mistake extraction for execution.

    python instruments/extract-cloud-refs.py
"""
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(R, "batches", "cloud", "cloud_auditrefs.collected.jsonl")
OUT = os.path.join(R, "audit", "results", "refs_cloud")
os.makedirs(OUT, exist_ok=True)

ok = bad = 0
for line in io.open(SRC, encoding="utf-8"):
    if not line.strip():
        continue
    r = json.loads(line)
    if r.get("collect_status") != "program":
        bad += 1
        continue
    raw = r.get("raw_text") or ""
    # the committed file arrives as a unified diff; take added lines
    added = "\n".join(l[1:] for l in raw.split("\n")
                      if l.startswith("+") and not l.startswith("+++"))
    body = added if "```" in added else raw
    py = re.search(r"```python\s*\n(.*?)```", body, re.S)
    js = re.search(r"```json\s*\n(.*?)```", body, re.S)
    assumptions = None
    if js:
        try:
            assumptions = json.loads(js.group(1)).get("assumptions")
        except Exception:
            assumptions = {"parse_error": js.group(1)[:200]}
    rec = {
        "task_id": r.get("audit_task_id"),
        "model": "codex-cloud(cloud-default)",
        "surface": "codex-cloud-harness",
        "code": py.group(1) if py else None,
        "assumptions": assumptions,
        "tape": None,                 # NOT executed - extraction only
        "total_trades": None,
        "template_sha256": r.get("template_sha256"),
        "cloud_task_id": r.get("task_id"),
    }
    if rec["code"] is None:
        bad += 1
        continue
    path = os.path.join(OUT, f"task{rec['task_id']}_cloud.json")
    io.open(path, "w", encoding="utf-8", newline="\n").write(
        json.dumps(rec, indent=1))
    ok += 1

print(f"extracted {ok} cloud references -> audit/results/refs_cloud/ "
      f"({bad} envelopes without an extractable python block)")
print("tapes are NOT executed here; the harness-sensitivity comparison runs "
      "after the audit driver executes these against the panel refs.")
