"""Per-family drafter surfaces for phase 2 under the 2026-08-21 owner ruling
(one drafter per family: claude-sonnet-5, gpt-5.6-terra @ medium, gemini
flash via Vertex pending the funding word). Same contract as cli.call_claude:
returns stdout text, writes out_path + sibling .prompt.txt, raises
SessionLimitError on quota banners so batch runners halt resumably.

All calls run in the certified clean room (C:/lbres): allowlisted env,
auth-only homes - and REQUIRE a same-day canary pass file, the same gate as
instruments/generate.js. No pass file -> RoomNotCertified."""
import json
import os
import subprocess
from datetime import date
from pathlib import Path

from cli import SessionLimitError, CLIError, call_claude  # noqa: F401  (claude stays on the proven path)

LBRES = Path("C:/lbres")
HOMES = LBRES / "homes"
NODE = Path(os.environ.get("LB_NODE", r"C:\Program Files\nodejs\node.exe"))
CODEX_JS = Path(r"C:\Users\joshp\AppData\Roaming\npm\node_modules\@openai\codex\bin\codex.js")


class RoomNotCertified(RuntimeError):
    pass


def _require_canary():
    stamp = date.today().isoformat()
    if not (LBRES / f"CANARY-PASS-{stamp}.json").exists():
        raise RoomNotCertified(f"no same-day canary pass (CANARY-PASS-{stamp}.json); run instruments/canary.js")


def _clean_env(extra):
    env = {
        "SystemRoot": r"C:\Windows", "windir": r"C:\Windows",
        "PATH": r"C:\Windows\System32;" + str(NODE.parent),
        "TEMP": str(LBRES / "tmp"), "TMP": str(LBRES / "tmp"),
        "USERPROFILE": str(HOMES / "blank"), "HOME": str(HOMES / "blank"),
        "APPDATA": str(HOMES / "appdata"), "LOCALAPPDATA": str(HOMES / "localappdata"),
        "PROGRAMDATA": r"C:\ProgramData", "COMSPEC": r"C:\Windows\System32\cmd.exe",
    }
    env.update(extra)
    return env


def call_codex(prompt: str, model: str, out_path: Path, effort: str = "medium",
               timeout: int = 1200, min_bytes: int = 150) -> str:
    """codex exec in the clean room; auth-only CODEX_HOME (jpinc005)."""
    _require_canary()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.with_suffix(out_path.suffix + ".prompt.txt").write_text(prompt, encoding="utf-8")
    home = HOMES / "codex"
    last_msg = out_path.with_suffix(out_path.suffix + ".last.txt")
    args = [str(NODE), str(CODEX_JS), "exec", "--skip-git-repo-check", "--ephemeral",
            "-s", "read-only", "--json", "-o", str(last_msg),
            "-m", model, "-c", f"model_reasoning_effort={effort}", "-"]
    r = subprocess.run(args, input=prompt, encoding="utf-8", capture_output=True,
                       env=_clean_env({"CODEX_HOME": str(home)}), timeout=timeout)
    text = last_msg.read_text(encoding="utf-8") if last_msg.exists() else (r.stdout or "")
    lower = (text + (r.stderr or "")).lower()
    for banner in ("usage limit", "session limit", "refresh token", "log out and sign in"):
        if banner in lower:
            raise SessionLimitError(f"codex: {banner}")
    if len(text.encode()) < min_bytes:
        raise CLIError(f"codex output too small ({len(text)}B); stderr tail: {(r.stderr or '')[-200:]}")
    out_path.write_text(text, encoding="utf-8")
    return text


def call_drafter(family: str, prompt: str, out_path: Path, timeout: int = 1200) -> str:
    """The per-family dispatch of record (owner ruling 2026-08-21)."""
    if family == "claude":
        _require_canary()
        return call_claude(prompt, "claude-sonnet-5", out_path, timeout=timeout, min_bytes=300)
    if family == "codex":
        return call_codex(prompt, "gpt-5.6-terra", out_path, effort="medium", timeout=timeout, min_bytes=300)
    if family == "gemini":
        raise RuntimeError("gemini drafter surface pends the owner's Vertex word (HYPOTHESES.md SS C)")
    raise ValueError(f"unknown family {family}")
