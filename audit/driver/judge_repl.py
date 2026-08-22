"""Their LLM judge, replicated over claude CLI (PLAN.md D8).

Prompt: judge.StrategyJudge._create_evaluation_prompt verbatim (extracted template,
filled by .replace). Parsing: verbatim ports of _parse_alignment and
_fallback_evaluation. A CLI failure follows their control flow: evaluate()'s
except-path -> _fallback_evaluation (keyword heuristic), flagged judge_mode=fallback.
"""
import re
from pathlib import Path

from cli import call_claude, SessionLimitError

TEMPLATE = (Path(__file__).parent.parent / "prompts" / "judge_prompt_template.txt").read_text(encoding="utf-8")

JUDGE_MODEL = "sonnet"  # their README-endorsed judge family (see PLAN.md D8)


def parse_alignment(evaluation_text: str):
    """Verbatim port of judge._parse_alignment."""
    try:
        rating_patterns = [
            r'rating:\s*\[\[(\d+)\]\]',
            r'rating\s*\[\[(\d+)\]\]',
            r'\[\[(\d+)\]\]',
            r'rating:\s*(\d+)',
        ]
        evaluation_lower = evaluation_text.lower().strip()
        for pattern in rating_patterns:
            matches = re.findall(pattern, evaluation_lower)
            if matches:
                try:
                    score = int(matches[-1])
                    return (score == 1), score, "rating"
                except ValueError:
                    continue
        positive_keywords = ["matches", "correct", "aligned", "yes", "compliant"]
        negative_keywords = ["doesn't match", "incorrect", "not aligned", "no", "non-compliant"]
        last_part = evaluation_lower[-300:]
        positive_count = sum(1 for kw in positive_keywords if kw in last_part)
        negative_count = sum(1 for kw in negative_keywords if kw in last_part)
        if positive_count > negative_count:
            return True, 1, "keyword"
        elif negative_count > positive_count:
            return False, 0, "keyword"
        return False, 0, "keyword-tie"
    except Exception:
        return False, 0, "parse-error"


def fallback_evaluation(task_description: str, generated_code: str):
    """Verbatim port of judge._fallback_evaluation (their no-API heuristic)."""
    if not generated_code or len(generated_code.strip()) < 100:
        return False, "Code is too short or empty"
    code_lower = generated_code.lower()
    task_lower = task_description.lower()
    indicator_keywords = [
        "sma", "ema", "rsi", "macd", "bollinger", "vix", "moving average",
    ]
    task_indicators = [kw for kw in indicator_keywords if kw in task_lower]
    if not task_indicators:
        has_strategy = "class" in code_lower and "bt.strategy" in code_lower
        return has_strategy, "No specific indicators in task, checking basic structure"
    code_has_indicators = any(ind in code_lower for ind in task_indicators)
    if code_has_indicators:
        return True, f"Code appears to use task indicators: {task_indicators}"
    return False, f"Code does not use task indicators: {task_indicators}"


def judge(task_description: str, generated_code: str, out_path: Path) -> dict:
    prompt = (TEMPLATE
              .replace("{task_description}", task_description)
              .replace("{generated_code}", generated_code))
    try:
        text = call_claude(prompt, JUDGE_MODEL, out_path, min_bytes=100)
        aligned, score, parse_mode = parse_alignment(text)
        return {"judge_aligned": aligned, "judge_score": score,
                "judge_mode": "cli", "parse_mode": parse_mode,
                "judge_text": text}
    except SessionLimitError:
        raise
    except Exception as e:
        aligned, expl = fallback_evaluation(task_description, generated_code)
        return {"judge_aligned": aligned, "judge_score": 1 if aligned else 0,
                "judge_mode": "fallback", "parse_mode": "fallback",
                "judge_text": expl, "judge_error": str(e)}
