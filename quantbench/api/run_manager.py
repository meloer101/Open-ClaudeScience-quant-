"""Triggers new Coordinator runs in the background.

v1: a plain thread pool + filesystem-based status (manifest.json present =
completed, error.json present = failed, neither = running). No task queue -
this is a local single-user tool, and status derived from the filesystem
survives an API process restart, which an in-memory-only tracker wouldn't.
"""

from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor

from quantbench.agent.coordinator import Coordinator
from quantbench.artifact.store import ArtifactStore
from quantbench.config import RUNS_DIR


class RunManager:
    def __init__(self, run_store: ArtifactStore | None = None, max_workers: int = 2):
        self._store = run_store or ArtifactStore(RUNS_DIR)
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def submit(self, user_request: str) -> str:
        run = self._store.create_run(user_request)
        coordinator = Coordinator()

        def _task() -> None:
            try:
                coordinator.execute(run, user_request)
            except Exception:
                run.save_json("error.json", {"traceback": traceback.format_exc()})

        self._executor.submit(_task)
        return run.run_id
