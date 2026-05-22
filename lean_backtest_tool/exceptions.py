"""Tool-specific exception types.

These are raised internally by the runner and translated to RunResult.exit_status
in tool.run(). They should not leak to the caller.
"""


class LeanBacktestToolError(Exception):
    """Base class for tool-internal errors."""


class DockerUnavailable(LeanBacktestToolError):
    """Raised when the Docker daemon cannot be reached or the image is missing.

    Caller maps this to exit_status="docker_error".
    """


class InfraError(LeanBacktestToolError):
    """Raised when LEAN failed to even produce an output directory.

    Distinct from DockerUnavailable: Docker ran, but something went wrong before
    LEAN could write artifacts. Caller maps this to exit_status="infra_error".
    """


class TimeoutKilled(LeanBacktestToolError):
    """Raised when the per-backtest wall-clock budget was exceeded.

    Caller maps this to exit_status="timeout" and appends TIMEOUT_EXCEEDED to the
    output. The partial log (whatever was written before the kill) is still used.
    """
