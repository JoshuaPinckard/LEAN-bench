"""Hardened headless claude CLI invocation (PLAN.md 1.5, lean-infra doctrine).

- direct claude.exe path (PATH resolves to a .ps1 shim that non-shell subprocess
  can't spawn); list-form args so the empty --tools value survives
- real file handles for stdin/stdout (piped grandchildren survive timeouts on
  Windows and hold file locks)
- quota/login banners are written INTO output files by the CLI; detect them and
  raise SessionLimitError so batch runners halt resumably instead of burning
  retries
"""
import subprocess
import time
from pathlib import Path

CLAUDE_EXE = (Path.home() / "AppData" / "Roaming" / "npm" / "node_modules"
              / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe")

BANNERS = ("hit your session limit", "Not logged in", "usage limit")


class SessionLimitError(RuntimeError):
    pass


class CLIError(RuntimeError):
    pass


def call_claude(prompt: str, model: str, out_path: Path, timeout: int = 900,
                attempts: int = 2, min_bytes: int = 150) -> str:
    """Run `claude -p --model <model> --tools ""` with prompt on stdin.

    Returns stdout text. Writes <out_path> (raw stdout) and sibling .prompt.txt.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path = out_path.with_suffix(out_path.suffix + ".prompt.txt")
    prompt_path.write_text(prompt, encoding="utf-8")

    last_err = None
    for attempt in range(1, attempts + 1):
        try:
            with open(prompt_path, "rb") as fin, open(out_path, "wb") as fout:
                p = subprocess.run(
                    [str(CLAUDE_EXE), "-p", "--model", model, "--tools", ""],
                    stdin=fin, stdout=fout, stderr=subprocess.PIPE, timeout=timeout,
                )
        except subprocess.TimeoutExpired:
            last_err = f"timeout after {timeout}s (attempt {attempt})"
            time.sleep(10)
            continue

        text = out_path.read_text(encoding="utf-8", errors="replace").strip()

        for banner in BANNERS:
            if banner.lower() in text.lower() and len(text) < 500:
                raise SessionLimitError(f"CLI banner detected: {text[:120]!r}")

        if p.returncode == 0 and len(text.encode("utf-8")) >= min_bytes:
            return text

        stderr = p.stderr.decode("utf-8", errors="replace")[-500:] if p.stderr else ""
        last_err = (f"attempt {attempt}: rc={p.returncode}, "
                    f"{len(text)} chars, stderr tail: {stderr!r}")
        time.sleep(10)

    raise CLIError(f"claude CLI failed after {attempts} attempts: {last_err}")
