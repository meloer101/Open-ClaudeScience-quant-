import builtins

import numpy as np
import pandas as pd

from quantbench.skills.sandbox import SandboxConfig, run_in_sandbox

# Basic signal-code sandboxing: block the builtins that would let generated signal code
# reach outside pandas/numpy (filesystem, imports, nested eval). Combined with the
# process-level isolation in quantbench.skills.sandbox (CPU/memory/wall-clock rlimits),
# this is both an import whitelist/builtin denylist AND a resource-bounded subprocess -
# a runaway or malicious compute() can no longer stall or OOM the coordinator process.
_BLOCKED_BUILTINS = {"eval", "exec", "open", "__import__", "compile", "input", "exit", "quit", "breakpoint"}
_SAFE_BUILTINS = {name: getattr(builtins, name) for name in dir(builtins) if name not in _BLOCKED_BUILTINS}


def run_signal_code(code: str, data_df: pd.DataFrame, *, sandbox: SandboxConfig | None = None) -> pd.Series:
    """Execute model-generated signal code in a resource-bounded child process
    and return the resulting series.

    `code` must define `compute(df: pd.DataFrame) -> pd.Series`. Only `pd` and
    `np` are available in scope; imports are disabled. `sandbox` overrides the
    default CPU/memory/wall-clock limits (quantbench.config.SANDBOX_*); pass it
    when a caller legitimately needs more headroom than the conservative
    defaults. Raises SandboxError (a RuntimeError) on a resource-limit breach,
    or ValueError for ordinary code/shape errors - both are plain exceptions,
    so existing callers that catch Exception around this call see no change.
    """
    return run_in_sandbox(_execute_signal_code, code, data_df, config=sandbox)


def _execute_signal_code(code: str, data_df: pd.DataFrame) -> pd.Series:
    """The unsandboxed executor. Runs inside the sandboxed child process (see
    run_in_sandbox); do not call directly from coordinator/tool code - that
    would bypass the resource limits run_signal_code enforces."""
    compute = load_signal_function(code)
    result = compute(data_df)
    if not isinstance(result, pd.Series):
        raise ValueError(f"compute() must return a pandas Series, got {type(result).__name__}")
    if len(result) != len(data_df):
        raise ValueError(f"compute() returned {len(result)} rows, expected {len(data_df)}")
    return result


def load_signal_function(code: str):
    namespace: dict = {"__builtins__": _SAFE_BUILTINS, "pd": pd, "np": np}
    try:
        exec(code, namespace)  # noqa: S102 - intentional, restricted namespace above
    except Exception as exc:
        raise ValueError(f"signal code failed to execute: {type(exc).__name__}: {exc}") from exc

    compute = namespace.get("compute")
    if not callable(compute):
        raise ValueError("signal code must define a function `compute(df) -> pd.Series`")
    return compute
