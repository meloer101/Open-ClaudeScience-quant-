from __future__ import annotations

from pathlib import Path

from quantbench.config import SKILL_DOCS_DIR
from quantbench.skilldocs.doc import SkillDoc, parse_skill_md


class SkillRegistryDocs:
    def __init__(self, docs_dir: Path = SKILL_DOCS_DIR) -> None:
        self.docs_dir = Path(docs_dir)

    def load_all(self) -> list[SkillDoc]:
        if not self.docs_dir.exists():
            return []
        return [parse_skill_md(path) for path in sorted(self.docs_dir.glob("*.md"))]

    def get(self, name: str) -> SkillDoc:
        for doc in self.load_all():
            if doc.name == name:
                return doc
        raise FileNotFoundError(name)

    def match(self, request_text: str, *, limit: int = 3) -> list[SkillDoc]:
        text = request_text.lower()
        matches: list[tuple[int, SkillDoc]] = []
        for doc in self.load_all():
            score = sum(1 for trigger in doc.triggers if trigger.lower() in text)
            if score:
                matches.append((score, doc))
        matches.sort(key=lambda item: (-item[0], item[1].name))
        return [doc for _, doc in matches[:limit]]
