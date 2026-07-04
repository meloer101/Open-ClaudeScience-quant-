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
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from quantbench.agent.coordinator import Coordinator, RunCancelled
from quantbench.api.session import SessionStore, summarize_run
from quantbench.artifact.store import ArtifactStore
from quantbench.config import RUNS_DIR

# Sentinel pushed after the terminal event so event_stream() knows to stop
# without needing a separate "is this run still active" check.
_STREAM_END = object()


class RunManager:
    def __init__(self, run_store: ArtifactStore | None = None, max_workers: int = 2):
        self._store = run_store or ArtifactStore(RUNS_DIR)
        self._session_store = SessionStore(self._store.runs_dir)
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._queues: dict[str, queue.Queue] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._staging_waiters: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _run_task(self, run, event_queue: queue.Queue, work: Any) -> None:
        cancel_event = self._cancel_events[run.run_id]
        try:
            work(cancel_event)
        except RunCancelled:
            run.save_json("cancelled.json", {"run_id": run.run_id})
            event_queue.put({"type": "cancelled"})
            event_queue.put(_STREAM_END)
        except Exception:
            run.save_json("error.json", {"traceback": traceback.format_exc()})
            event_queue.put({"type": "error", "message": traceback.format_exc()})
            event_queue.put(_STREAM_END)
        finally:
            self._cancel_events.pop(run.run_id, None)

    def submit(self, user_request: str) -> str:
        run = self._store.create_run(user_request)
        coordinator = Coordinator()
        event_queue: queue.Queue = queue.Queue()
        self._queues[run.run_id] = event_queue
        self._cancel_events[run.run_id] = threading.Event()

        def on_event(event: dict[str, Any]) -> None:
            event_queue.put(event)
            if event.get("type") == "final":
                event_queue.put(_STREAM_END)

        def work(cancel_event: threading.Event) -> None:
            def staging_confirm(run_id: str, artifact: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
                return self._await_staging_confirmation(run_id, event_queue, cancel_event, artifact, config)

            coordinator.execute(
                run,
                user_request,
                on_event=on_event,
                cancel_event=cancel_event,
                staging_confirm=staging_confirm,
            )

        self._executor.submit(self._run_task, run, event_queue, work)
        return run.run_id

    def submit_session_turn(self, session_id: str, user_message: str, session_context: str, turn_index: int) -> str:
        run = self._store.create_run(user_message)
        coordinator = Coordinator(run_store=self._store)
        event_queue: queue.Queue = queue.Queue()
        self._queues[run.run_id] = event_queue
        self._cancel_events[run.run_id] = threading.Event()

        def on_event(event: dict[str, Any]) -> None:
            event_queue.put(event)
            if event.get("type") == "final":
                event_queue.put(_STREAM_END)

        def work(cancel_event: threading.Event) -> None:
            def staging_confirm(run_id: str, artifact: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
                return self._await_staging_confirmation(run_id, event_queue, cancel_event, artifact, config)

            coordinator.execute(
                run,
                user_message,
                on_event=on_event,
                cancel_event=cancel_event,
                staging_confirm=staging_confirm,
                session_context=session_context,
                session_id=session_id,
                turn_index=turn_index,
            )
            self._session_store.update_turn_summary(session_id, turn_index, summarize_run(run.run_id))

        self._executor.submit(self._run_task, run, event_queue, work)
        return run.run_id

    def fork(self, parent_run_id: str, modification: str) -> str:
        run = self._store.create_run(f"Fork {parent_run_id}: {modification}")
        coordinator = Coordinator()
        event_queue: queue.Queue = queue.Queue()
        self._queues[run.run_id] = event_queue
        self._cancel_events[run.run_id] = threading.Event()

        def on_event(event: dict[str, Any]) -> None:
            event_queue.put(event)
            if event.get("type") == "final":
                event_queue.put(_STREAM_END)

        def work(cancel_event: threading.Event) -> None:
            coordinator.execute_fork(run, parent_run_id, modification, on_event=on_event, cancel_event=cancel_event)

        self._executor.submit(self._run_task, run, event_queue, work)
        return run.run_id

    def cancel(self, run_id: str) -> bool:
        """Signal a running run to stop before its next LLM call/tool call.
        Returns False if the run isn't currently tracked as active (already
        finished, or the API process restarted since it was submitted)."""
        cancel_event = self._cancel_events.get(run_id)
        if cancel_event is None:
            return False
        cancel_event.set()
        with self._lock:
            waiter = self._staging_waiters.get(run_id)
            if waiter is not None:
                waiter["event"].set()
        return True

    def cancel_all(self) -> None:
        """Signal every in-flight run to stop. Called on API shutdown so a
        Ctrl-C doesn't leave background threads spinning through MAX_STEPS
        while the process tries to exit."""
        for cancel_event in self._cancel_events.values():
            cancel_event.set()

    def confirm_staging(self, run_id: str, overrides: dict[str, Any]) -> bool:
        with self._lock:
            waiter = self._staging_waiters.get(run_id)
            if waiter is None:
                return False
            waiter["overrides"] = overrides
            waiter["event"].set()
            return True

    def _await_staging_confirmation(
        self,
        run_id: str,
        event_queue: queue.Queue,
        cancel_event: threading.Event,
        artifact: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any] | None:
        event = threading.Event()
        waiter = {"event": event, "overrides": None}
        with self._lock:
            self._staging_waiters[run_id] = waiter
        event_queue.put({"type": "staging", "artifact": artifact, "config": config})
        try:
            while not event.wait(timeout=0.1):
                if cancel_event.is_set():
                    raise RunCancelled(run_id)
            if cancel_event.is_set():
                raise RunCancelled(run_id)
            return waiter.get("overrides") or {}
        finally:
            with self._lock:
                self._staging_waiters.pop(run_id, None)

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
