"""Extract QuantCode-Bench's prompts verbatim by importing their modules (PLAN.md 1.1/1.2).

- prompts/system_prompt_full.txt  <- generator.SYSTEM_PROMPT_EN (full, replaces the
  truncated qcb_system_prompt.txt produced by the old naive triple-quote scan)
- prompts/judge_prompt_template.txt <- judge.StrategyJudge._create_evaluation_prompt
  called with literal placeholder strings, so the file contains {task_description}
  and {generated_code} markers to fill by .replace() (not .format(), to avoid
  brace-escaping issues with code content).
"""
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "QuantCode-Bench"))

from quantcode_bench.generator import SYSTEM_PROMPT_EN, _USER_PROMPT_SINGLE_EN  # noqa: E402
from quantcode_bench.judge import StrategyJudge  # noqa: E402

out = HERE / "prompts"
out.mkdir(exist_ok=True)

(out / "system_prompt_full.txt").write_text(SYSTEM_PROMPT_EN, encoding="utf-8")
# Their single-shot request is ONE user message: SYSTEM_PROMPT_EN +
# _USER_PROMPT_SINGLE_EN.format(prompt=task)  (generator.py:411)
(out / "user_prompt_single.txt").write_text(_USER_PROMPT_SINGLE_EN, encoding="utf-8")
tmpl = StrategyJudge._create_evaluation_prompt("{task_description}", "{generated_code}")
(out / "judge_prompt_template.txt").write_text(tmpl, encoding="utf-8")

old = (HERE / "qcb_system_prompt.txt").read_text(encoding="utf-8")
print(f"system prompt: {len(SYSTEM_PROMPT_EN)} chars "
      f"(old truncated extract: {len(old)}), "
      f"sha256 {hashlib.sha256(SYSTEM_PROMPT_EN.encode()).hexdigest()[:16]}")
print("system prompt TAIL >>>", SYSTEM_PROMPT_EN[-400:].replace("\n", " | "))
print(f"judge template: {len(tmpl)} chars")
