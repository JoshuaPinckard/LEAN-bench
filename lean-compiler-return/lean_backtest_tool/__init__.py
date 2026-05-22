"""lean_backtest_tool.

Single-responsibility tool: take (code, language, runtime_config), run one
backtest against pinned LEAN in Docker, return a filtered deterministic log
string suitable for handing to an LLM as feedback.

See docs/spec.md for the full design contract.
"""
from .tool import run, RunConfig, RunResult
from . import spec_constants
from . import exceptions

__all__ = ["run", "RunConfig", "RunResult", "spec_constants", "exceptions"]
