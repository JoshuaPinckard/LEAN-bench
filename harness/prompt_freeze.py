"""Canonical prompt-set freezing for LEAN-Bench reproducibility.

The frozen artifact is the single source of truth for "what prompts ran in
the benchmark." Its SHA256 is stamped on every call so any result row can be
traced back to the exact prompt definition that produced it.

Design rules:
  - Only benchmark-defining fields are included; UI/runtime/audit telemetry
    is excluded so cosmetic edits don't invalidate the hash.
  - Output JSON is canonical: sorted keys at every level, prompts sorted by
    prompt_id, ASCII-only, no insignificant whitespace.
  - The hash is computed over the canonical bytes — anyone with the artifact
    file can reproduce the hash from a fresh clone.

See docs/benchmark_decision_log.md for the rationale.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

# Fields that define the benchmark identity of a prompt. Anything not in
# this list is excluded from the canonical form. Adding a field here is a
# methodology change and invalidates every prior hash — bump BENCHMARK_VERSION
# in harness/constants.py.
CANONICAL_PROMPT_FIELDS: tuple[str, ...] = (
    # identity
    "prompt_id",
    "version",
    # text
    "original_text",
    "original_url",
    "reformulated_text",
    "reformulation_notes",
    # provenance
    "source",
    "source_date",
    "is_post_cutoff",
    # categorization
    "strategy_type",
    "strategy_complexity",
    "api_complexity",
    # LEAN configuration (everything the model conditions on)
    "securities_type",
    "securities_type_detailed",
    "resolution",
    "implementation_type",
    "indicators",
    "universe_type",
    "universe_index",
    "universe_index_other",
    "tickers",
    "start_date",
    "end_date",
    "cash",
    # evaluation rules
    "evaluation_mode",
    "interpretation_strictness",
    "implementation_underspecified",
    "underspecification_notes",
    # leak audit (an audit decision IS a benchmark-defining fact)
    "leak_audit_status",
    "leak_audit_notes",
    # exclusion flag (kept so the frozen set can include curator-excluded
    # rows for audit, while runtime ignores them — see is_eligible below)
    "excluded_from_benchmark",
)

# Fields explicitly DROPPED from the canonical form. Listed for clarity; the
# CANONICAL_PROMPT_FIELDS allowlist is what actually enforces this.
EXCLUDED_FIELDS: tuple[str, ...] = (
    "created_at",                   # timestamp
    "ai_prepopulated",              # curator workflow telemetry
    "curator_modified_fields",      # curator workflow telemetry
    # Legacy / retired columns are never in the canonical form.
)

# ---- JSON column decode helpers ----------------------------------------

_JSON_LIST_COLS: tuple[str, ...] = ("tickers", "indicators")


def _decode_json_list(raw: Any) -> list:
    if raw in (None, "", []):
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _normalize_prompt(row: dict) -> dict:
    """Project a raw prompts-row dict down to the canonical key set, with
    JSON list columns decoded and field order stabilized via JSON sort_keys.

    Returns a plain dict — sorting and ASCII encoding happen at serialization.
    """
    out: dict[str, Any] = {}
    for key in CANONICAL_PROMPT_FIELDS:
        value = row.get(key)
        if key in _JSON_LIST_COLS:
            value = _decode_json_list(value)
        # Coerce SQLite int-bools to bool so the canonical form is stable
        # regardless of how the source DB happened to store them.
        if key in ("is_post_cutoff", "implementation_underspecified", "excluded_from_benchmark"):
            if value is None:
                value = False
            else:
                value = bool(value)
        out[key] = value
    return out


def is_eligible(prompt_row: dict) -> bool:
    """True iff this prompt belongs in the frozen benchmark set.

    - Adhoc prompts (source='adhoc') are dev-only and never included.
    - Curator-flagged excluded prompts (excluded_from_benchmark=1) are dropped.
    """
    if str(prompt_row.get("source") or "") == "adhoc":
        return False
    if bool(prompt_row.get("excluded_from_benchmark")):
        return False
    return True


# ---- Canonical serialization -------------------------------------------

def canonicalize(prompts: Iterable[dict]) -> bytes:
    """Return the canonical JSON bytes for an iterable of prompt rows.

    The output is the exact byte string the SHA256 is computed over and the
    exact content written to disk.
    """
    rows = sorted(
        (_normalize_prompt(p) for p in prompts if is_eligible(p)),
        key=lambda r: r.get("prompt_id") or "",
    )
    payload = {
        "schema":  "lean_bench_frozen_prompt_set_v1",
        "count":   len(rows),
        "prompts": rows,
    }
    # ensure_ascii=True: a non-ASCII char would otherwise change bytes vs.
    # codepoints depending on encoding choice. Force one stable representation.
    # separators=(",", ":"): no insignificant whitespace.
    # sort_keys=True: sort keys at every level.
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def sha256_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


# ---- Loading & verification ---------------------------------------------

def load_frozen(path: Path | str) -> tuple[bytes, str]:
    """Read the frozen artifact and return (canonical_bytes, sha256_hex).

    Re-canonicalizes the on-disk content so we don't depend on the file having
    been written byte-for-byte; this lets a hand-edit of the file (e.g. to
    reformat) be detected as a mismatch when it materially changes content.
    """
    raw = Path(path).read_text(encoding="utf-8")
    parsed = json.loads(raw)
    prompts = parsed.get("prompts", [])
    canonical = canonicalize(prompts)
    return canonical, sha256_of(canonical)
