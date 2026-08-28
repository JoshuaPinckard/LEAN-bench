#!/usr/bin/env python3
"""Generate sentence-atom variants for the LEAN-Bench options arm."""

import hashlib
import json
import re
from pathlib import Path


DONOR = Path(__file__).with_name("O1v0.txt")
OUTPUT_DIR = Path(__file__).with_name("variants-o1")
MANIFEST = Path(__file__).with_name("variants-o1.json")
DONOR_SHA = "8220c41350874a3818b5aec80b812b0fb2cbf527496369dbe8fb9899dc86bdd9"


# (id, role, description, [(old, new, expected_count)])
VARIANTS = [
    (
        "O1p1",
        "placebo",
        "Reorder two independent data-subscription specifications without changing content.",
        [
            (
                "Use New York time and minute-resolution, raw-price SPY equity data. "
                "Subscribe to SPY options at minute resolution and keep the option universe "
                "broad enough to contain the contracts specified below.",
                "Subscribe to SPY options at minute resolution and keep the option universe "
                "broad enough to contain the contracts specified below. "
                "Use New York time and minute-resolution, raw-price SPY equity data.",
                1,
            ),
        ],
    ),
    (
        "O1c1",
        "control",
        "Delete the DTE definition, whose calendar-date meaning is recoverable from the adjacent expiry rule.",
        [
            (
                "Days to expiration means the difference between the contract expiration "
                "date and the current algorithm date, measured in calendar dates rather "
                "than trading sessions or 24-hour periods. ",
                "",
                1,
            ),
        ],
    ),
    (
        "O1a1",
        "anchor",
        "Blank the repeatedly recoverable underlying symbol.",
        [
            (
                "Backtest SPY from April 1, 2023 through June 30, 2026 with $100,000 initial cash.",
                "Backtest ____ from April 1, 2023 through June 30, 2026 with $100,000 initial cash.",
                1,
            ),
        ],
    ),
    (
        "O1a2",
        "anchor",
        "Blank the implementation language, recoverable from the requested file suffix and framework register.",
        [
            (
                "Implement a complete QuantConnect LEAN algorithm in Python using the QCAlgorithm framework.",
                "Implement a complete QuantConnect LEAN algorithm in ____ using the QCAlgorithm framework.",
                1,
            ),
        ],
    ),
    (
        "O1e1",
        "eligible",
        "Delete the strike-selection convention.",
        [
            (
                "Within that expiration, consider only call contracts and select the lowest "
                "strike that is greater than or equal to 101% of the current SPY price. ",
                "Within that expiration, consider only call contracts. ",
                1,
            ),
            (
                "Thus the selected call is the first listed strike at least 1% out of the money; "
                "break an equal-strike tie by the ascending string value of the contract Symbol.",
                "",
                1,
            ),
        ],
    ),
    (
        "O1e2",
        "eligible",
        "Delete the expiry and minimum-DTE selection convention.",
        [
            (
                "Choose the nearest expiration whose calendar date is at least 7 calendar "
                "days after the current algorithm date. ",
                "",
                1,
            ),
        ],
    ),
    (
        "O1e3",
        "eligible",
        "Delete the option-type convention and its redundant grammatical traces.",
        [
            (
                "Trade one long SPY call at a time. The option type is call, never put.",
                "Trade one long SPY option at a time.",
                1,
            ),
            (
                "Within that expiration, consider only call contracts and select the lowest strike",
                "Within that expiration, select the lowest strike",
                1,
            ),
            (
                "Thus the selected call is the first listed strike",
                "Thus the selected contract is the first listed strike",
                1,
            ),
        ],
    ),
    (
        "O1e4",
        "eligible",
        "Delete the position-size convention.",
        [
            (
                "Buy exactly 1 contract. ",
                "",
                1,
            ),
        ],
    ),
    (
        "O1e5",
        "eligible",
        "Delete the numerical profit-target threshold.",
        [
            (
                "A 50% profit target is reached when that midpoint is at least 1.50 times "
                "the filled entry price. ",
                "",
                1,
            ),
        ],
    ),
    (
        "O1e6",
        "eligible",
        "Delete the exercise-or-assignment equity-position handling convention.",
        [
            (
                "If exercise or assignment processing nevertheless creates a SPY equity "
                "position, liquidate the entire SPY equity position with a market order "
                "immediately and do not treat it as a strategy entry.",
                "",
                1,
            ),
        ],
    ),
    (
        "O1e7",
        "eligible",
        "Delete the no-match handling convention.",
        [
            (
                "If the current Slice has no option chain, no expiration satisfies the rule, "
                "or no contract at the selected expiration satisfies the type and strike rules, "
                "skip that entry signal without throwing an exception or falling back to "
                "another contract. A skipped signal is not queued for later; wait for a new "
                "bullish crossover.\n\n",
                "",
                1,
            ),
        ],
    ),
    (
        "O1e8",
        "eligible",
        "Delete the slow-average lookback parameter.",
        [
            (
                "The slow average is a 20-bar simple moving average of five-minute closing prices.",
                "The slow average is a simple moving average of five-minute closing prices.",
                1,
            ),
        ],
    ),
]


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def apply_edits(donor, variant_id, edits):
    result = donor
    for edit_number, (old, new, expected_count) in enumerate(edits, start=1):
        actual_count = result.count(old)
        assert actual_count == expected_count, (
            f"{variant_id} edit {edit_number}: expected {expected_count} exact "
            f"occurrence(s), found {actual_count}: {old!r}"
        )
        result = result.replace(old, new)
        assert result.count(old) == 0, (
            f"{variant_id} edit {edit_number}: old span survived replacement"
        )

    assert result != donor, f"{variant_id}: edits did not change donor"
    return result


def assert_surface_integrity(variant_id, text):
    assert text.endswith("\n"), f"{variant_id}: missing final newline"
    assert "\r" not in text, f"{variant_id}: CR byte introduced"
    assert "\t" not in text, f"{variant_id}: tab introduced"
    assert "\n\n\n" not in text, f"{variant_id}: triple blank line introduced"
    assert "  " not in text, f"{variant_id}: doubled space introduced"
    assert not re.search(r"(?m)^\s*(?:[-*+]|\d+[.)])\s*$", text), (
        f"{variant_id}: orphan list marker"
    )
    assert not re.search(r"[,;:]\s*(?:\n\n|\Z)", text), (
        f"{variant_id}: dangling punctuation"
    )
    assert not re.search(r"(?m)^\s*[.,;:!?]", text), (
        f"{variant_id}: orphan or dangling leading punctuation"
    )


def main():
    donor_bytes = DONOR.read_bytes()
    actual_donor_sha = sha256_bytes(donor_bytes)
    assert actual_donor_sha == DONOR_SHA, (
        f"donor SHA mismatch: expected {DONOR_SHA}, got {actual_donor_sha}"
    )
    assert b"\r" not in donor_bytes, "donor must use LF line endings"
    assert donor_bytes.endswith(b"\n"), "donor must end with one LF"

    donor = donor_bytes.decode("utf-8")
    ids = [variant_id for variant_id, _, _, _ in VARIANTS]
    assert len(ids) == len(set(ids)), "duplicate variant id"

    roles = [role for _, role, _, _ in VARIANTS]
    assert roles.count("placebo") == 1, "expected exactly one placebo"
    assert roles.count("control") == 1, "expected exactly one control"
    assert roles.count("anchor") == 2, "expected exactly two anchors"
    assert 6 <= roles.count("eligible") <= 8, "expected 6-8 eligible variants"
    assert set(roles) == {"placebo", "control", "anchor", "eligible"}, (
        "unexpected variant role"
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "donor": DONOR.name,
        "donor_sha256": actual_donor_sha,
        "variants": [],
    }

    for variant_id, role, description, edits in VARIANTS:
        variant = apply_edits(donor, variant_id, edits)
        assert_surface_integrity(variant_id, variant)

        variant_bytes = variant.encode("utf-8")
        output_path = OUTPUT_DIR / f"{variant_id}.txt"
        output_path.write_bytes(variant_bytes)

        manifest["variants"].append(
            {
                "id": variant_id,
                "role": role,
                "description": description,
                "path": output_path.relative_to(MANIFEST.parent).as_posix(),
                "sha256": sha256_bytes(variant_bytes),
                "edits": [
                    {
                        "old": old,
                        "new": new,
                        "expected_count": expected_count,
                    }
                    for old, new, expected_count in edits
                ],
            }
        )

    manifest_text = json.dumps(
        manifest,
        indent=2,
        ensure_ascii=False,
        sort_keys=False,
    ) + "\n"
    MANIFEST.write_text(manifest_text, encoding="utf-8", newline="\n")

    print(
        f"generated {len(VARIANTS)} variants from {DONOR.name} "
        f"({actual_donor_sha})"
    )


if __name__ == "__main__":
    main()