import builtins

import numpy as np
import pandas as pd

# Basic signal-code sandboxing: block the builtins that would let generated signal code
# reach outside pandas/numpy (filesystem, imports, nested eval). This is not a
# process-level sandbox (that's a later hardening step); it is only an import
# whitelist and builtin denylist for local research code.
_BLOCKED_BUILTINS = {"eval", "exec", "open", "__import__", "compile", "input", "exit", "quit", "breakpoint"}
_SAFE_BUILTINS = {name: getattr(builtins, name) for name in dir(builtins) if name not in _BLOCKED_BUILTINS}


def run_signal_code(code: str, data_df: pd.DataFrame) -> pd.Series:
    """Execute model-generated signal code and return the resulting series.

    `code` must define `compute(df: pd.DataFrame) -> pd.Series`. Only `pd` and
    `np` are available in scope; imports are disabled.
    """
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
