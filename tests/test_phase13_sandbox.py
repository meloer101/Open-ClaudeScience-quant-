import time

import pandas as pd
import pytest


def _sample_df(n=20):
    return pd.DataFrame({"close": [float(i) for i in range(n)]})


def _probe_rlimit_as(queue) -> None:
    import resource

    try:
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
        queue.put(True)
    except (ValueError, OSError):
        queue.put(False)


def _rlimit_as_is_enforceable() -> bool:
    """RLIMIT_AS is unenforceable on macOS/Darwin - setrlimit to any finite
    value fails with EINVAL there even though the constant is defined and
    getrlimit reports the current limit as unlimited. Probed in a throwaway
    subprocess (not this test process) so the probe itself can't leave the
    real limit lowered for the rest of the run."""
    import multiprocessing as mp

    ctx = mp.get_context("spawn")
    queue = ctx.Queue()
    process = ctx.Process(target=_probe_rlimit_as, args=(queue,))
    process.start()
    process.join(5.0)
    return queue.get() if not queue.empty() else False


def test_run_signal_code_matches_unsandboxed_execution_for_well_behaved_code():
    from quantbench.skills.codeexec import _execute_signal_code, run_signal_code

    code = "def compute(df):\n    return df['close'] * 2.0\n"
    df = _sample_df()

    sandboxed = run_signal_code(code, df)
    unsandboxed = _execute_signal_code(code, df)

    pd.testing.assert_series_equal(sandboxed, unsandboxed)


def test_run_signal_code_keeps_two_positional_argument_signature():
    from quantbench.skills.codeexec import run_signal_code

    code = "def compute(df):\n    return df['close']\n"
    result = run_signal_code(code, _sample_df())
    assert isinstance(result, pd.Series)


def test_run_signal_code_still_blocks_open_builtin():
    from quantbench.skills.codeexec import run_signal_code

    code = "def compute(df):\n    open('/tmp/should-not-exist', 'w')\n    return df['close']\n"
    with pytest.raises(NameError, match="open"):
        run_signal_code(code, _sample_df())


def test_run_signal_code_infinite_loop_hits_cpu_limit():
    from quantbench.skills.codeexec import run_signal_code
    from quantbench.skills.sandbox import SandboxConfig, SandboxError

    code = "def compute(df):\n    while True:\n        pass\n"
    tight_config = SandboxConfig(cpu_seconds=1, mem_mb=512, wall_timeout_s=5.0)

    started = time.monotonic()
    with pytest.raises(SandboxError):
        run_signal_code(code, _sample_df(), sandbox=tight_config)
    elapsed = time.monotonic() - started

    assert elapsed < tight_config.wall_timeout_s + 2.0


@pytest.mark.skipif(
    not _rlimit_as_is_enforceable(),
    reason="RLIMIT_AS is not enforceable on this platform (known macOS/Darwin limitation - "
    "setrlimit(RLIMIT_AS, ...) fails with EINVAL there even for a finite, lowered value). "
    "The sandbox degrades gracefully (CPU limit + wall-clock backstop still apply) but "
    "cannot bound memory on such platforms without a heavier isolation mechanism (e.g. "
    "cgroups on Linux, which PHASE13 explicitly defers rather than adding Docker for).",
)
def test_run_signal_code_memory_bomb_hits_address_space_limit():
    from quantbench.skills.codeexec import run_signal_code
    from quantbench.skills.sandbox import SandboxConfig, SandboxError

    code = "def compute(df):\n    np.zeros((400_000_000,), dtype='float64')\n    return df['close']\n"
    tight_config = SandboxConfig(cpu_seconds=5, mem_mb=200, wall_timeout_s=10.0)

    with pytest.raises(SandboxError):
        run_signal_code(code, _sample_df(), sandbox=tight_config)


def test_run_signal_code_wall_clock_backstop_fires_before_a_looser_cpu_limit():
    from quantbench.skills.codeexec import run_signal_code
    from quantbench.skills.sandbox import SandboxConfig, SandboxError

    # cpu_seconds is intentionally looser than wall_timeout_s here, so this
    # only passes if the parent's own wall-clock join(timeout) is doing real
    # work rather than just waiting on RLIMIT_CPU to fire.
    code = "def compute(df):\n    while True:\n        pass\n"
    tight_config = SandboxConfig(cpu_seconds=30, mem_mb=512, wall_timeout_s=1.5)

    started = time.monotonic()
    with pytest.raises(SandboxError, match="timeout"):
        run_signal_code(code, _sample_df(), sandbox=tight_config)
    elapsed = time.monotonic() - started

    assert elapsed < tight_config.wall_timeout_s + 3.0
