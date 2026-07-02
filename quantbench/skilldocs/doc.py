from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SkillDoc:
    name: str
    description: str
    triggers: list[str]
    body: str
    path: str


def parse_skill_md(path: Path) -> SkillDoc:
    text = Path(path).read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path} is missing YAML frontmatter")
    _, frontmatter, body = text.split("---", 2)
    meta: dict[str, Any] = yaml.safe_load(frontmatter) or {}
    missing = [key for key in ("name", "description", "triggers") if not meta.get(key)]
    if missing:
        raise ValueError(f"{path} is missing frontmatter field(s): {', '.join(missing)}")
    body = body.strip()
    if not body:
        raise ValueError(f"{path} has empty Skill body")
    triggers = meta["triggers"]
    if not isinstance(triggers, list) or not all(isinstance(item, str) and item for item in triggers):
        raise ValueError(f"{path} triggers must be a non-empty string list")
    return SkillDoc(
        name=str(meta["name"]),
        description=str(meta["description"]),
        triggers=triggers,
        body=body,
        path=str(Path(path)),
    )
