"""Their evaluation gates, ported verbatim from quantcode_bench/reward.py (PLAN.md 1.5).

Gate 1: _clean_code + _validate_code_structure (exact copies).
Gates 2-3: execution + has_trades via tape_exec (their wrapper + tape recorder).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import tape_exec  # noqa: E402


def clean_code(code: str) -> str:
    """Verbatim port of reward._clean_code."""
    if not code:
        return ""
    if "</think>" in code:
        last_end = code.rfind("</think>")
        code = code[last_end + len("</think>"):].strip()
    elif "<think>" in code:
        lines = code.split("\n")
        for i, line in enumerate(lines):
            if line.strip().startswith(("import ", "from ", "class ", "def ")):
                code = "\n".join(lines[i:])
                break
        else:
            code = ""
    if "```python" in code:
        parts = code.split("```python")
        if len(parts) > 1:
            code = parts[1].split("```")[0].strip()
    elif "```" in code:
        parts = code.split("```")
        for i, part in enumerate(parts):
            if i % 2 == 1 and part.strip():
                code = part.strip()
                break
    lines = code.split("\n")
    for i, line in enumerate(lines):
        if line.strip().startswith(("import ", "from ")):
            code = "\n".join(lines[i:])
            break
    return code.strip()


def validate_code_structure(code: str):
    """Verbatim port of reward._validate_code_structure."""
    if not code:
        return False, "Empty code"
    if "import backtrader" not in code:
        return False, "Missing 'import backtrader' statement"
    if not re.search(r"class\s+\w+\s*\(\s*bt\.Strategy\s*\)", code):
        return False, "Missing strategy class inheriting from bt.Strategy"
    if "def next(self)" not in code:
        return False, "Missing next() method"
    return True, ""


def run_gates(raw_code: str, cache_path) -> dict:
    """Full gate pipeline on raw model output. Returns gate outcomes + tape."""
    cleaned = clean_code(raw_code)
    ok, err = validate_code_structure(cleaned)
    if not ok:
        return {"cleaned_code": cleaned, "structure_ok": False,
                "backtest_ok": False, "has_trades": False,
                "gates_pass": False, "error": f"Validation failed: {err}",
                "total_trades": 0, "tape": []}

    r = tape_exec.run_tape(cleaned, str(cache_path))
    return {"cleaned_code": cleaned, "structure_ok": True,
            "backtest_ok": bool(r.get("success")),
            "has_trades": bool(r.get("has_trades")),
            "gates_pass": bool(r.get("success")) and bool(r.get("has_trades")),
            "error": r.get("error"),
            "total_trades": r.get("total_trades", 0),
            "total_return": r.get("total_return"),
            "tape": r.get("tape", [])}
