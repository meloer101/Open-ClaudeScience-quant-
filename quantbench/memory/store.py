from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from quantbench.config import PROJECT_ROOT


@dataclass(frozen=True)
class UserMemoryFact:
    fact_id: str
    type: str
    description: str
    provenance: dict[str, Any]
    created_at: str
    confidence: float
    fields: dict[str, Any]
    statement: str
    stale: bool = False


class UserMemoryStore:
    def __init__(self, memory_dir: Path | None = None):
        self.memory_dir = Path(memory_dir) if memory_dir is not None else PROJECT_ROOT / "memory" / "user"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def read_all(self) -> list[UserMemoryFact]:
        facts = [self._read(path) for path in sorted(self.memory_dir.glob("*.md")) if path.name != "INDEX.md"]
        return [fact for fact in facts if fact is not None]

    def write(self, fact: dict[str, Any]) -> UserMemoryFact:
        existing = self._find_conflicting_default(fact)
        fact_id = existing.fact_id if existing is not None else str(fact.get("fact_id") or self._new_fact_id(fact))
        created_at = existing.created_at if existing is not None else str(fact.get("created_at") or _utc_now())
        payload = UserMemoryFact(
            fact_id=fact_id,
            type=str(fact["type"]),
            description=str(fact["description"]),
            provenance=dict(fact.get("provenance") or {}),
            created_at=created_at,
            confidence=float(fact.get("confidence", 0.5)),
            fields=dict(fact.get("fields") or {}),
            statement=str(fact.get("statement") or fact["description"]),
            stale=bool(fact.get("stale", False)),
        )
        self._write_fact(payload)
        self.render_index()
        return payload

    def update(self, fact_id: str, updates: dict[str, Any]) -> UserMemoryFact:
        current = self.get(fact_id)
        payload = {
            "fact_id": current.fact_id,
            "type": current.type,
            "description": current.description,
            "provenance": current.provenance,
            "created_at": current.created_at,
            "confidence": current.confidence,
            "fields": current.fields,
            "statement": current.statement,
            "stale": current.stale,
            **updates,
        }
        return self.write(payload)

    def delete(self, fact_id: str) -> None:
        path = self.memory_dir / f"{fact_id}.md"
        if path.exists():
            path.unlink()
        self.render_index()

    def get(self, fact_id: str) -> UserMemoryFact:
        fact = self._read(self.memory_dir / f"{fact_id}.md")
        if fact is None:
            raise FileNotFoundError(fact_id)
        return fact

    def default_facts(self) -> list[UserMemoryFact]:
        return [
            fact
            for fact in self.read_all()
            if not fact.stale and fact.type in {"default_preference", "default"} and bool(fact.fields)
        ]

    def render_index(self) -> str:
        lines = []
        for fact in self.read_all():
            if fact.stale:
                continue
            fields = ", ".join(f"{key}={value}" for key, value in sorted(fact.fields.items()))
            suffix = f" ({fields})" if fields else ""
            lines.append(f"- {fact.fact_id} [{fact.type}, confidence={fact.confidence:g}]: {fact.description}{suffix}")
        content = "\n".join(lines)
        if content:
            content += "\n"
        (self.memory_dir / "INDEX.md").write_text(content, encoding="utf-8")
        return content

    def append_event(self, event: dict[str, Any]) -> dict[str, Any]:
        payload = {"when": _utc_now(), **event}
        with (self.memory_dir / "memory_events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return payload

    def read_events(self) -> list[dict[str, Any]]:
        path = self.memory_dir / "memory_events.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _find_conflicting_default(self, fact: dict[str, Any]) -> UserMemoryFact | None:
        if fact.get("type") not in {"default_preference", "default"}:
            return None
        fields = set((fact.get("fields") or {}).keys())
        if not fields:
            return None
        for existing in self.default_facts():
            if existing.type == fact.get("type") and fields.intersection(existing.fields):
                return existing
        return None

    def _new_fact_id(self, fact: dict[str, Any]) -> str:
        description = str(fact.get("description") or "memory")
        slug = re.sub(r"[^a-z0-9]+", "-", description.lower()).strip("-")[:48] or "memory"
        return f"{slug}-{uuid.uuid4().hex[:6]}"

    def _write_fact(self, fact: UserMemoryFact) -> None:
        frontmatter = {
            "type": fact.type,
            "description": fact.description,
            "provenance": fact.provenance,
            "created_at": fact.created_at,
            "confidence": fact.confidence,
            "fields": fact.fields,
            "stale": fact.stale,
        }
        content = "---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False) + "---\n" + fact.statement.strip() + "\n"
        (self.memory_dir / f"{fact.fact_id}.md").write_text(content, encoding="utf-8")

    def _read(self, path: Path) -> UserMemoryFact | None:
        if not path.exists() or path.name == "INDEX.md":
            return None
        content = path.read_text(encoding="utf-8")
        metadata: dict[str, Any] = {}
        statement = content
        if content.startswith("---\n"):
            _, frontmatter, statement = content.split("---\n", 2)
            metadata = yaml.safe_load(frontmatter) or {}
        return UserMemoryFact(
            fact_id=path.stem,
            type=str(metadata.get("type") or "fact"),
            description=str(metadata.get("description") or ""),
            provenance=dict(metadata.get("provenance") or {}),
            created_at=str(metadata.get("created_at") or ""),
            confidence=float(metadata.get("confidence", 0.5)),
            fields=dict(metadata.get("fields") or {}),
            statement=statement.strip(),
            stale=bool(metadata.get("stale", False)),
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
