from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quantbench.api import run_reader
from quantbench.config import RUNS_DIR


@dataclass(frozen=True)
class SessionTurn:
    turn_index: int
    user_message: str
    run_id: str | None
    summary: dict[str, Any]


@dataclass(frozen=True)
class Session:
    session_id: str
    created_at: str
    turns: list[SessionTurn]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_from_dict(payload: dict[str, Any]) -> Session:
    return Session(
        session_id=str(payload["session_id"]),
        created_at=str(payload["created_at"]),
        turns=[SessionTurn(**turn) for turn in payload.get("turns", [])],
    )


class SessionStore:
    def __init__(self, runs_dir: Path = RUNS_DIR):
        self.runs_dir = Path(runs_dir)
        self.sessions_dir = self.runs_dir / "_sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def create(self) -> Session:
        session = Session(
            session_id=f"session_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}",
            created_at=_utc_now(),
            turns=[],
        )
        self._write(session)
        return session

    def get(self, session_id: str) -> Session:
        path = self._path(session_id)
        if not path.exists():
            raise FileNotFoundError(session_id)
        return _session_from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list(self) -> list[Session]:
        if not self.sessions_dir.exists():
            return []
        return [
            _session_from_dict(json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(self.sessions_dir.glob("session_*.json"), reverse=True)
        ]

    def append_turn(
        self,
        session_id: str,
        user_message: str,
        run_id: str | None,
        summary: dict[str, Any] | None = None,
    ) -> SessionTurn:
        session = self.get(session_id)
        turn = SessionTurn(
            turn_index=len(session.turns),
            user_message=user_message,
            run_id=run_id,
            summary=summary or {},
        )
        self._write(Session(session.session_id, session.created_at, [*session.turns, turn]))
        return turn

    def update_turn_summary(self, session_id: str, turn_index: int, summary: dict[str, Any]) -> None:
        session = self.get(session_id)
        turns = [
            SessionTurn(turn.turn_index, turn.user_message, turn.run_id, summary)
            if turn.turn_index == turn_index
            else turn
            for turn in session.turns
        ]
        self._write(Session(session.session_id, session.created_at, turns))

    def _path(self, session_id: str) -> Path:
        if "/" in session_id or ".." in session_id:
            raise FileNotFoundError(session_id)
        return self.sessions_dir / f"{session_id}.json"

    def _write(self, session: Session) -> None:
        self._path(session.session_id).write_text(json.dumps(asdict(session), ensure_ascii=False, indent=2), encoding="utf-8")


def summarize_run(run_id: str) -> dict[str, Any]:
    manifest = run_reader.read_manifest(run_id) or {}
    config = run_reader.read_config(run_id) or {}
    metrics = manifest.get("metrics") or {}
    review = manifest.get("review") or {}
    return {
        "hypothesis": config.get("hypothesis") or manifest.get("user_request") or run_reader.read_user_request(run_id),
        "verdict": review.get("verdict"),
        "key_metrics": _key_metrics(metrics),
        "run_id": run_id,
    }


def build_session_context(session: Session) -> str:
    lines = []
    for turn in session.turns:
        summary = turn.summary or {}
        run_id = summary.get("run_id") or turn.run_id
        if not run_id:
            continue
        metrics = summary.get("key_metrics") or {}
        metric_text = ", ".join(f"{key}={value}" for key, value in sorted(metrics.items()))
        parts = [
            f"run_id={run_id}",
            f"hypothesis={summary.get('hypothesis') or turn.user_message}",
        ]
        if summary.get("verdict"):
            parts.append(f"verdict={summary['verdict']}")
        if metric_text:
            parts.append(metric_text)
        lines.append("- " + "; ".join(parts))
    if not lines:
        return ""
    return "本 session 已有 run 摘要如下（仅结构化摘要，不含原始对话）：\n" + "\n".join(lines)


def _key_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    keys = ("sharpe", "annual_return", "max_drawdown", "turnover_annual", "ic_mean")
    return {key: metrics[key] for key in keys if key in metrics}
