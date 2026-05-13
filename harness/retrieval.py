"""Retrieval preprocessor: enriches a user prompt with a focused QuantConnect
LEAN documentation snippet before it hits any benchmarked model.

Applied only under tool-using conditions (CONDITIONS_WITH_RETRIEVAL — currently
S2_docs, S3_web, A1_agentic_full); S1_base is the unaugmented baseline.

Two Sonnet calls per uncached prompt:
  1. Index selection: Sonnet sees the prompt plus an index of available doc
     files under qc_docs/ and returns a JSON array of relevant filenames.
  2. Summarization: Sonnet sees the prompt plus the contents of those files
     (HTML stripped, total content capped) and returns a focused snippet.

The output is cached in `retrieval_cache` keyed by SHA256(prompt) so the same
prompt under any condition for any of the 6 benchmarked models receives the
identical snippet — preserving the "all models see the same docs" invariant.

Deterministic per Sonnet version (temperature=0). Snippet is empty when
qc_docs/ has no scannable files or both Sonnet calls fail; in that case the
orchestrator appends nothing and the call proceeds as if the prompt were
unaugmented.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from anthropic import AsyncAnthropic

if TYPE_CHECKING:
    from harness.storage import Store

# --- Configuration --------------------------------------------------------

QC_DOCS_DIR = Path("qc_docs")
RETRIEVAL_MODEL = "claude-sonnet-4-6"

# Subdirectory whitelist relative to qc_docs/. Only files under these roots are
# eligible for the retrieval index. Skips infrastructure dirs (code-generators,
# skill-templates, project-templates, etc.) that hold noise rather than API
# documentation. Adjust this list as the corpus evolves.
RELEVANT_DOC_ROOTS: tuple[str, ...] = (
    "03 Writing Algorithms",
    "06 LEAN Engine",
    "04 Research Environment",
)

# Cap on the index size sent to Sonnet for stage 1. Files past the cap are
# truncated alphabetically; raise if the docs grow and you want full coverage.
MAX_INDEX_FILES = 800
# Stage 1 picks up to this many files for stage 2.
MAX_FILES_PER_RETRIEVAL = 6
# Hard ceiling on the concatenated content sent to stage 2 (rough char limit).
MAX_TOTAL_CONTENT_CHARS = 80_000
# Per-file content cap (truncate long HTML files).
MAX_PER_FILE_CHARS = 20_000
# Max tokens Sonnet may produce for the final snippet.
MAX_SNIPPET_TOKENS = 2048

# --- Anthropic client (lazy) ---------------------------------------------

_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic()
    return _client


# --- Helpers --------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def prompt_hash(prompt: str) -> str:
    """Stable SHA256 hash used as the retrieval_cache key."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _strip_html(text: str) -> str:
    """Crude HTML-to-text: drop tags, collapse whitespace. Cheap, lossy."""
    return _WS_RE.sub(" ", _HTML_TAG_RE.sub(" ", text)).strip()


def _list_doc_files() -> list[Path]:
    """Walk qc_docs/ and return Paths of .html / .md files under the relevant
    roots, capped at MAX_INDEX_FILES (alphabetical truncation)."""
    if not QC_DOCS_DIR.exists():
        return []
    files: list[Path] = []
    for root in RELEVANT_DOC_ROOTS:
        root_dir = QC_DOCS_DIR / root
        if not root_dir.exists():
            continue
        for ext in ("*.html", "*.md"):
            files.extend(root_dir.rglob(ext))
    files = sorted(set(files), key=lambda p: str(p))
    return files[:MAX_INDEX_FILES]


def _file_label(path: Path) -> str:
    """Short label for the index sent to Sonnet: just the relative path."""
    try:
        return str(path.relative_to(QC_DOCS_DIR)).replace("\\", "/")
    except ValueError:
        return path.name


# --- Sonnet calls ---------------------------------------------------------

async def _select_relevant_files(prompt: str, file_paths: list[Path]) -> list[Path]:
    """Stage 1: Sonnet picks up to MAX_FILES_PER_RETRIEVAL relevant files."""
    labels = [_file_label(p) for p in file_paths]
    index_text = "\n".join(labels)
    instruction = (
        "You are selecting QuantConnect LEAN documentation files relevant to a "
        "user's algorithmic-trading prompt.\n\n"
        f"User prompt:\n{prompt}\n\n"
        f"Available documentation file paths (one per line):\n{index_text}\n\n"
        "Return ONLY a JSON array of the file paths most relevant to "
        "implementing the user's request, exactly as written above. Limit to the "
        f"{MAX_FILES_PER_RETRIEVAL} most relevant. If none are clearly relevant, "
        'return []. Example: ["03 Writing Algorithms/28 Indicators/01 Introduction.html"]'
    )
    client = _get_client()
    resp = await client.messages.create(
        model=RETRIEVAL_MODEL,
        max_tokens=512,
        temperature=0,
        messages=[{"role": "user", "content": instruction}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        picked = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(picked, list):
        return []
    valid = {_file_label(p): p for p in file_paths}
    return [valid[s] for s in picked if isinstance(s, str) and s in valid][:MAX_FILES_PER_RETRIEVAL]


async def _summarize_for_prompt(prompt: str, file_contents: dict[str, str]) -> str:
    """Stage 2: Sonnet writes a focused docs snippet from the selected files."""
    if not file_contents:
        return ""
    parts: list[str] = []
    total = 0
    for name, content in file_contents.items():
        clean = _strip_html(content)[:MAX_PER_FILE_CHARS]
        block = f"### {name}\n{clean}"
        if total + len(block) > MAX_TOTAL_CONTENT_CHARS:
            break
        parts.append(block)
        total += len(block)
    combined = "\n\n".join(parts)
    instruction = (
        "You are preparing a documentation excerpt for an AI engineer "
        "implementing a QuantConnect LEAN algorithm in Python. Keep it under "
        "800 words and cover only the LEAN API surface the engineer will need: "
        "relevant method signatures, indicator names, data subscription patterns, "
        "and order placement calls. No fluff, no preamble. Return ONLY the "
        "snippet text.\n\n"
        f"User's algorithm request:\n{prompt}\n\n"
        f"Relevant LEAN documentation:\n{combined}"
    )
    client = _get_client()
    resp = await client.messages.create(
        model=RETRIEVAL_MODEL,
        max_tokens=MAX_SNIPPET_TOKENS,
        temperature=0,
        messages=[{"role": "user", "content": instruction}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


# --- Public entry point ---------------------------------------------------

async def get_retrieval_snippet(prompt: str, store: "Store") -> str:
    """Return the LEAN-docs snippet to append to `prompt`. Cached by hash.

    Returns "" gracefully when qc_docs/ is empty, Sonnet selects nothing
    relevant, or any Sonnet call fails. The orchestrator should treat an
    empty snippet as "do not augment the prompt".
    """
    h = prompt_hash(prompt)
    cached = store.get_cached_retrieval(h)
    if cached is not None:
        return cached

    files = _list_doc_files()
    if not files:
        store.set_cached_retrieval(h, prompt, "", model_used=RETRIEVAL_MODEL)
        return ""

    try:
        selected = await _select_relevant_files(prompt, files)
        contents: dict[str, str] = {}
        for path in selected:
            try:
                contents[_file_label(path)] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        snippet = await _summarize_for_prompt(prompt, contents) if contents else ""
    except Exception:
        snippet = ""

    store.set_cached_retrieval(h, prompt, snippet, model_used=RETRIEVAL_MODEL)
    return snippet
