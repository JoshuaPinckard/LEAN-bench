"""Tape comparison per PLAN.md D3.

Primary key:   ordered (fill_timestamp, side) sequence  == tape_exec.tape_key
Secondary key: ordered (fill_timestamp, side, size) sequence (sensitivity check)

Both tapes come from the identical execution stack (tape_exec wrapper ->
bt.num2date().isoformat()), so timestamps are already consistently normalized;
comparison is exact string equality on the key tuples.
"""


def primary_key(tape):
    return [(e["dt"], e["side"]) for e in tape]


def secondary_key(tape):
    return [(e["dt"], e["side"], round(float(e["size"]), 8)) for e in tape]


def compare(candidate_tape, reference_tape) -> dict:
    return {
        "primary_match": primary_key(candidate_tape) == primary_key(reference_tape),
        "secondary_match": secondary_key(candidate_tape) == secondary_key(reference_tape),
        "candidate_fills": len(candidate_tape),
        "reference_fills": len(reference_tape),
    }
