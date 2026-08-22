"""Phase 1.6 gate: one task end-to-end through the full audit chain.

generation prompt (their exact single-shot composition) -> claude CLI ->
their gates -> tape -> judge replication -> ledger row. Prints every stage.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common
import gates
import judge_repl
from cli import call_claude

SYSTEM = (common.PROMPTS / "system_prompt_full.txt").read_text(encoding="utf-8")
USER_SINGLE = (common.PROMPTS / "user_prompt_single.txt").read_text(encoding="utf-8")

tasks = common.load_tasks()
reqs = common.load_requirements()
task = next(t for t in sorted(tasks.values(), key=lambda t: t["id"])
            if t["difficulty"] == "easy"
            and reqs[t["id"]]["yf_symbol"] == "AAPL" and reqs[t["id"]]["timeframe"] == "1d")
print(f"smoke task: id={task['id']} ({task['difficulty']}, "
      f"{reqs[task['id']]['yf_symbol']}@{reqs[task['id']]['timeframe']})")
print("task text head:", task["reformulated_task"][:200].replace("\n", " "))

# their exact single-shot request: one user message (generator.py:411)
gen_prompt = SYSTEM + USER_SINGLE.replace("{prompt}", task["reformulated_task"])

out_dir = common.RESULTS / "smoke"
raw = call_claude(gen_prompt, "sonnet", out_dir / f"gen_{task['id']}.txt", min_bytes=300)
print(f"\ngeneration: {len(raw)} chars")

g = gates.run_gates(raw, common.cache_path_for(task))
print(f"gates: structure={g['structure_ok']} backtest={g['backtest_ok']} "
      f"trades={g['total_trades']} gates_pass={g['gates_pass']}")
if g["error"]:
    print("gate error:", g["error"])
print("tape head:", [(e['dt'], e['side']) for e in g["tape"][:4]])

j = None
if g["gates_pass"]:
    j = judge_repl.judge(task["reformulated_task"], g["cleaned_code"],
                         out_dir / f"judge_{task['id']}.txt")
    print(f"judge: aligned={j['judge_aligned']} score={j['judge_score']} "
          f"mode={j['judge_mode']}/{j['parse_mode']}")
    print("judge text tail:", j["judge_text"][-200:].replace("\n", " "))

common.ledger_append({
    "phase": "smoke", "task_id": task["id"], "role": "smoke", "model": "sonnet",
    "sample_idx": 0, "gates": {k: v for k, v in g.items() if k not in ("tape", "cleaned_code")},
    "n_fills": len(g["tape"]),
    "judge": ({k: v for k, v in j.items() if k != "judge_text"} if j else None),
})
print("\nSMOKE TEST COMPLETE — ledger row written")
