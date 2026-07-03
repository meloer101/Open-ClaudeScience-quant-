from __future__ import annotations

import multiprocessing as mp
from dataclasses import dataclass
from typing import Any, Callable

from quantbench.config import (
    SANDBOX_CPU_SECONDS,
    SANDBOX_MAX_WRITE_MB,
    SANDBOX_MEM_MB,
    SANDBOX_WALL_TIMEOUT_S,
)

# 'spawn' (not 'fork'): the child gets a fresh interpreter with no inherited
# threads, locks, or open file descriptors from the parent (notably the LLM
# client's connection pool) - fork-safety issues in a long-lived coordinator
# process are a much worse bug than the extra ~100ms interpreter startup cost.
_CONTEXT = mp.get_context("spawn")


class SandboxError(RuntimeError):
    """Raised when the sandboxed call hits a resource limit or otherwise
    fails to produce a result. A plain RuntimeError subclass so existing
    `except Exception` handlers around tool execution (e.g. the coordinator's
    agent loop) already turn this into a structured {"error": ...} result
    without any changes on their end."""


@dataclass(frozen=True)
class SandboxConfig:
    cpu_seconds: int = SANDBOX_CPU_SECONDS
    mem_mb: int = SANDBOX_MEM_MB
    wall_timeout_s: float = SANDBOX_WALL_TIMEOUT_S
    max_write_mb: int = SANDBOX_MAX_WRITE_MB


_DEFAULT_CONFIG = SandboxConfig()


def run_in_sandbox(func: Callable[..., Any], *args: Any, config: SandboxConfig | None = None) -> Any:
    """Runs func(*args) in a child process with CPU/address-space/file-size
    rlimits and a wall-clock backstop, and returns its result. `func` must be
    a module-level function (picklable by reference) and its return value
    must be picklable (a pandas Series/DataFrame qualifies).

    Raises SandboxError if the child is killed by a resource limit, times
    out, or otherwise exits without reporting a result. Raises whatever
    exception `func` itself raised (e.g. ValueError from bad signal code)
    unchanged, so callers see the same exception types as the unsandboxed
    path."""
    config = config or _DEFAULT_CONFIG
    result_queue: mp.Queue = _CONTEXT.Queue()
    process = _CONTEXT.Process(target=_run_in_child, args=(func, args, config, result_queue))

    process.start()
    process.join(config.wall_timeout_s)

    if process.is_alive():
        process.terminate()
        process.join(2.0)
        if process.is_alive():
            process.kill()
            process.join()
        raise SandboxError(f"sandbox: wall-clock timeout exceeded ({config.wall_timeout_s}s)")

    if result_queue.empty():
        raise SandboxError(
            f"sandbox: child process terminated abnormally (exit code {process.exitcode}) without "
            "reporting a result - likely killed by the OS for exceeding a resource limit "
            f"(CPU {config.cpu_seconds}s / memory {config.mem_mb}MB)"
        )

    status, payload = result_queue.get()
    if status == "error":
        raise SandboxError(payload)
    if status == "exception":
        exc_type, message = payload
        raise exc_type(message)
    return payload


def _apply_rlimits(config: SandboxConfig) -> list[str]:
    """Applies each POSIX rlimit independently and returns the names of any
    that this platform refused to set, instead of treating one unsupported
    limit as fatal. Notably RLIMIT_AS is unenforceable on macOS/Darwin -
    `setrlimit` fails with EINVAL even though `getrlimit` reports it as
    unlimited - while RLIMIT_CPU and RLIMIT_FSIZE work on both Darwin and
    Linux. CPU time plus the parent's wall-clock join() backstop still bound
    a runaway process even where the memory cap can't be enforced."""
    import resource

    unsupported = []
    for name, limit_id, value in (
        ("RLIMIT_CPU", resource.RLIMIT_CPU, config.cpu_seconds),
        ("RLIMIT_AS", resource.RLIMIT_AS, config.mem_mb * 1024 * 1024),
        ("RLIMIT_FSIZE", resource.RLIMIT_FSIZE, config.max_write_mb * 1024 * 1024),
    ):
        try:
            resource.setrlimit(limit_id, (value, value))
        except (ValueError, OSError):
            unsupported.append(name)
    return unsupported


def _run_in_child(func: Callable[..., Any], args: tuple, config: SandboxConfig, result_queue: mp.Queue) -> None:
    """Runs entirely inside the spawned child process. Never raises back into
    multiprocessing's process bootstrap - every failure mode is caught and
    reported through result_queue instead, since an uncaught exception here
    would just look like an unexplained nonzero exit code to the parent."""
    _apply_rlimits(config)

    try:
        result = func(*args)
    except MemoryError:
        result_queue.put(("error", "sandbox: memory limit exceeded"))
        return
    except Exception as exc:  # noqa: BLE001 - forward the original exception type/message, not a crash
        result_queue.put(("exception", (type(exc), str(exc))))
        return

    try:
        result_queue.put(("ok", result))
    except Exception as exc:  # noqa: BLE001 - e.g. an unpicklable result; report it rather than hang the parent
        result_queue.put(("error", f"sandbox: failed to serialize result: {exc}"))
