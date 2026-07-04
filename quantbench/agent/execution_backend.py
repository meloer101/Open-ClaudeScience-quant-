from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Protocol, TypeVar

from quantbench.config import EXECUTION_BACKEND

T = TypeVar("T")
R = TypeVar("R")


class ExecutionBackend(Protocol):
    """Dispatches a fan-out of independent tasks (e.g. screen_factors' per-candidate
    backtests). Only `local` is implemented; `remote` is an interface reservation for
    SSH/Modal-style offloading once single-machine compute becomes the bottleneck."""

    name: str

    def map(self, fn: Callable[[T], R], items: list[T], *, max_workers: int) -> list[R]: ...


class LocalBackend:
    """Current behavior: a bounded ThreadPoolExecutor on this machine. Results come
    back in completion order (as before) - callers already sort downstream, so order
    is not load-bearing."""

    name = "local"

    def map(self, fn: Callable[[T], R], items: list[T], *, max_workers: int) -> list[R]:
        if not items:
            return []
        workers = max(1, min(len(items), max_workers))
        results: list[R] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(fn, item) for item in items]
            for future in as_completed(futures):
                results.append(future.result())
        return results


class RemoteBackend:
    """Interface reservation only. Fails loudly rather than silently falling back to
    local, so a misconfigured remote run is never mistaken for a local one."""

    name = "remote"

    def map(self, fn: Callable[[T], R], items: list[T], *, max_workers: int) -> list[R]:
        raise NotImplementedError(
            "remote execution backend is planned but not implemented; "
            "set execution_backend='local' (QUANTBENCH_EXECUTION_BACKEND=local)"
        )


def get_execution_backend(name: str | None = None) -> ExecutionBackend:
    resolved = (name or EXECUTION_BACKEND or "local").lower()
    if resolved == "local":
        return LocalBackend()
    if resolved == "remote":
        return RemoteBackend()
    raise ValueError(f"unknown execution_backend {resolved!r}; expected 'local' or 'remote'")
