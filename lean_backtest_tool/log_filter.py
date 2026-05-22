"""Pure tag-based log filter + determinism stripping.

No I/O, no global state. Input: raw log string. Output: filtered string.

Algorithm (spec §4.2):
  1. Apply BLOCK_STRIPPERS to the whole raw log (multi-line patterns, e.g. the
     .NET runtime welcome banner that survives line-based filtering).
  2. Split on lines.
  3. For each line, identify its LEAN tag (`r"(?:^|\s)(\w+)::"`).
  4. Lines without a tag inherit the most recent tagged line's keep/drop
     decision — multi-line stack traces under an ERROR:: header stay together.
  5. Drop the line if its (inherited) tag is in DROPPED_TAGS.
  6. Apply DETERMINISM_STRIPPERS to each surviving line.
  7. Rejoin with "\n".
"""
from typing import Optional

from . import spec_constants


def _tag_of(line: str) -> Optional[str]:
    """Return the tag (without the '::') if this line introduces a tagged
    section, else None for a continuation/untagged line."""
    m = spec_constants.TAG_PATTERN.search(line)
    return m.group(1) if m else None


def _should_keep(tag: Optional[str], inherited: Optional[str]) -> bool:
    """Keep/drop decision for a line given its own tag and the inherited tag.

    Rules:
      - A line with its own tag is judged on that tag.
      - A line without a tag inherits the previous decision.
      - Before any tagged line has been seen, follow UNTAGGED_PREFIX_POLICY.
    """
    effective = tag if tag is not None else inherited
    if effective is None:
        return spec_constants.UNTAGGED_PREFIX_POLICY == "keep"
    if effective in spec_constants.DROPPED_TAGS:
        return False
    if effective in spec_constants.KEPT_TAGS:
        return True
    # Unknown tag — spec §5 EMPIRICAL #1: default to keeping.
    return spec_constants.UNKNOWN_TAG_POLICY == "keep"


def _strip_nondeterminism(line: str) -> str:
    """Apply the regex set from spec_constants in order."""
    for pattern, replacement in spec_constants.DETERMINISM_STRIPPERS:
        line = pattern.sub(replacement, line)
    return line


def filter_log(raw_log: str) -> str:
    """Tag-filter + determinism-strip. See module docstring for algorithm.

    Empty input returns empty output. A raw_log of only untagged lines is
    handled per UNTAGGED_PREFIX_POLICY.
    """
    if not raw_log:
        return ""

    for pattern, replacement in spec_constants.BLOCK_STRIPPERS:
        raw_log = pattern.sub(replacement, raw_log)

    out_lines: list[str] = []
    inherited_tag: Optional[str] = None

    for line in raw_log.splitlines():
        line_tag = _tag_of(line)
        keep = _should_keep(line_tag, inherited_tag)
        if line_tag is not None:
            inherited_tag = line_tag
        if keep:
            out_lines.append(_strip_nondeterminism(line))

    return "\n".join(out_lines)
