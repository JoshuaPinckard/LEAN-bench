"""Phase 1.4 gate: tape_exec.py must work on REAL tz-aware yfinance pickles.

Runs the repo's own example strategy (class only — the file's __main__ block would
execute a live yfinance download inside python -c, a finding in its own right)
against every frozen pickle, and prints tape heads so timestamp shape can be
inspected. Exit nonzero if any daily run fails or trades zero times.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import tape_exec  # noqa: E402

example = (HERE / "QuantCode-Bench" / "examples" / "sma_crossover.py").read_text(encoding="utf-8")
strategy_code = example.split('if __name__ == "__main__":')[0]

failures = []
for pkl in sorted((HERE / "frozen_cache").glob("*.pkl")):
    r = tape_exec.run_tape(strategy_code, str(pkl))
    tape = r.get("tape", [])
    head = tape_exec.tape_key(tape)[:3]
    print(f"{pkl.name:<22} success={r.get('success')} trades={r.get('total_trades')} "
          f"fills={len(tape)} head={head}")
    if not r.get("success"):
        print(f"   ERROR: {r.get('error')}")
        failures.append(pkl.name)
    elif not tape:
        # SMA(10/30) crossover should fire on every multi-month series
        failures.append(pkl.name + " (zero fills)")

print("\nVALIDATION:", "FAIL " + str(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
