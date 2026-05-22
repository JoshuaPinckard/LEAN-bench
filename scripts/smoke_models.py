"""Quick smoke test for the frozen model lineup. Calls each model with a
trivial prompt and reports success/failure. Used to verify model IDs after
config changes.

Usage: python scripts/smoke_models.py
"""
from __future__ import annotations

import asyncio
import sys
from harness.models import MODELS_FROZEN
from harness.providers import anthropic_client, openai_client, gemini_client

PROVIDER_CALL = {
    "anthropic": anthropic_client.call,
    "openai":    openai_client.call,
    "google":    gemini_client.call,
}


async def smoke(friendly: str) -> tuple[str, bool, str]:
    info = MODELS_FROZEN[friendly]
    pinned = info["model_id"]
    provider = info["provider"]
    call = PROVIDER_CALL[provider]
    try:
        resp = await call(
            model_pinned=pinned,
            messages=[{"role": "user", "content": "reply with the single word OK"}],
            max_tokens=16,
        )
        text = (resp["response_text"] or "").strip()[:40]
        return friendly, True, f"{pinned} -> {text!r}"
    except Exception as exc:
        return friendly, False, f"{pinned} -> {type(exc).__name__}: {str(exc)[:200]}"


async def main(targets: list[str]) -> int:
    if not targets:
        targets = list(MODELS_FROZEN)
    results = await asyncio.gather(*(smoke(t) for t in targets))
    fails = 0
    for friendly, ok, msg in results:
        flag = "PASS" if ok else "FAIL"
        print(f"  {flag}  {friendly:22} {msg}")
        if not ok:
            fails += 1
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
