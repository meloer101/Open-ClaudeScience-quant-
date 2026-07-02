"""Triggers new Coordinator runs in the background.

v1 (background execution + polling): a plain thread pool + filesystem-based
status (manifest.json present = completed, error.json present = failed,
neither = running). No task queue - this is a local single-user tool, and
status derived from the filesystem survives an API process restart, which an
in-memory-only tracker wouldn't.

v2 (this file): additionally keeps a small in-memory event queue per run_id,
fed by Coordinator's `on_event` hook, so the SSE endpoint can stream live
tool-call progress. This part IS in-memory only and does not survive a
restart - a client reconnecting after a restart just falls back to polling
/status, which still works from the filesystem.
"""

from __future__ import annotations

import queue
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from quantbench.agent.coordinator import Coordinator
from quantbench.artifact.store import ArtifactStore
from quantbench.config import RUNS_DIR

# Sentinel pushed after the terminal event so event_stream() knows to stop
# without needing a separate "is this run still active" check.
_STREAM_END = object()


class RunManager:
    def __init__(self, run_store: ArtifactStore | None = None, max_workers: int = 2):
        self._store = run_store or ArtifactStore(RUNS_DIR)
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._queues: dict[str, queue.Queue] = {}

    def submit(self, user_request: str) -> str:
        run = self._store.create_run(user_request)
        coordinator = Coordinator()
        event_queue: queue.Queue = queue.Queue()
        self._queues[run.run_id] = event_queue

        def on_event(event: dict[str, Any]) -> None:
            event_queue.put(event)
            if event.get("type") == "final":
                event_queue.put(_STREAM_END)

        def _task() -> None:
            try:
                coordinator.execute(run, user_request, on_event=on_event)
            except Exception:
                run.save_json("error.json", {"traceback": traceback.format_exc()})
                event_queue.put({"type": "error", "message": traceback.format_exc()})
                event_queue.put(_STREAM_END)

        self._executor.submit(_task)
        return run.run_id

    def fork(self, parent_run_id: str, modification: str) -> str:
        run = self._store.create_run(f"Fork {parent_run_id}: {modification}")
        coordinator = Coordinator()
        event_queue: queue.Queue = queue.Queue()
        self._queues[run.run_id] = event_queue

        def on_event(event: dict[str, Any]) -> None:
            event_queue.put(event)
            if event.get("type") == "final":
                event_queue.put(_STREAM_END)

        def _task() -> None:
            try:
                coordinator.execute_fork(run, parent_run_id, modification, on_event=on_event)
            except Exception:
                run.save_json("error.json", {"traceback": traceback.format_exc()})
                event_queue.put({"type": "error", "message": traceback.format_exc()})
                event_queue.put(_STREAM_END)

        self._executor.submit(_task)
        return run.run_id

    def has_live_stream(self, run_id: str) -> bool:
        return run_id in self._queues

    def stream_events(self, run_id: str, timeout: float = 30.0):
        """Yield queued events for run_id until the terminal sentinel arrives
        or `timeout` seconds pass with nothing new (client likely gone)."""
        event_queue = self._queues.get(run_id)
        if event_queue is None:
            return
        try:
            while True:
                try:
                    item = event_queue.get(timeout=timeout)
                except queue.Empty:
                    return
                if item is _STREAM_END:
                    return
                yield item
        finally:
            self._queues.pop(run_id, None)
