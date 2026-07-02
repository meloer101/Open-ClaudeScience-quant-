import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ArtifactStore:
    def __init__(self, runs_dir: Path):
        self.runs_dir = Path(runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def create_run(self, user_request: str) -> "Run":
        now = _utc_now()
        run_id = f"run_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        run = Run(run_id=run_id, run_dir=run_dir, user_request=user_request, created_at=now)
        # Written immediately (not just at finalize()) so callers - notably the
        # web API - can show the request text while a run is still in progress,
        # before config.yaml/manifest.json exist.
        run.save_text("request.txt", user_request)
        return run


class Run:
    def __init__(self, run_id: str, run_dir: Path, user_request: str, created_at: datetime):
        self.run_id = run_id
        self.run_dir = Path(run_dir)
        self.user_request = user_request
        self.created_at = created_at
        self._started = time.perf_counter()
        self.steps: list[dict[str, Any]] = []

    def save_config(self, config: dict[str, Any]) -> Path:
        return self.save_text("config.yaml", yaml.safe_dump(config, allow_unicode=True, sort_keys=False))

    def save_code(self, filename: str, code: str) -> Path:
        return self.save_text(filename, code)

    def save_json(self, filename: str, payload: Any) -> Path:
        return self.save_text(filename, json.dumps(_jsonable(payload), ensure_ascii=False, indent=2))

    def save_text(self, filename: str, content: str) -> Path:
        path = self.run_dir / filename
        path.write_text(content, encoding="utf-8")
        return path

    def log_step(self, tool: str, args: dict[str, Any], result: Any) -> None:
        self.steps.append(
            {
                "tool": tool,
                "args": _jsonable(args),
                "result": _jsonable(result),
                "logged_at": _utc_now().isoformat(),
            }
        )

    def finalize(
        self,
        data_hash: str,
        code_hash: str,
        warnings: list[str] | None = None,
        model: str = "unknown",
        conversation_log: str | None = None,
        summary: str = "",
        metrics: dict[str, Any] | None = None,
        review: dict[str, Any] | None = None,
        parent_run_id: str | None = None,
        injected_skills: list[str] | None = None,
    ) -> Path:
        manifest = {
            "run_id": self.run_id,
            "user_request": self.user_request,
            "created_at": self.created_at.isoformat(),
            "duration_seconds": round(time.perf_counter() - self._started, 3),
            "model": model,
            "summary": summary,
            "metrics": metrics or {},
            "review": review,
            "parent_run_id": parent_run_id,
            "injected_skills": injected_skills or [],
            "data_hash": data_hash,
            "code_hash": code_hash,
            "warnings": warnings or [],
            "conversation_log": conversation_log,
            "steps": self.steps,
        }
        return self.save_json("manifest.json", manifest)


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(key): _jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_jsonable(item) for item in value]
        return str(value)


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
