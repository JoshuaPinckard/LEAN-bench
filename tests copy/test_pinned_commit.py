"""Spec D1: pinned LEAN commit must not drift.

This test catches accidental Docker image bumps that would silently change
the version of LEAN used by the F-arm of the benchmark.
"""
from lean_backtest_tool import spec_constants


def test_pinned_commit_hash_is_immutable():
    assert spec_constants.LEAN_COMMIT_HASH == "d2daf42d34a0c97225794e9b1afaef820434db69", (
        "Pinned commit changed. If this is intentional, update the spec, "
        "regenerate findings.md against the new image, and only then update "
        "this assertion."
    )
