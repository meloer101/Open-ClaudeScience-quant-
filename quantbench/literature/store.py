from __future__ import annotations

import json
import shutil
from pathlib import Path

from quantbench.config import LITERATURE_DIR
from quantbench.literature.paper import Paper


class PaperStore:
    """On-disk store for ingested papers, one directory per paper:

        literature/<paper_id>/
            source.pdf       raw bytes (for the web viewer)
            text.json        [{page_number, text}, ...]
            metadata.json    title/authors/source/sha256/...

    Mirrors FactorStore's read/write conventions (JSON, mkdir on write)."""

    def __init__(self, literature_dir: Path = LITERATURE_DIR) -> None:
        self.literature_dir = Path(literature_dir)

    def _paper_dir(self, paper_id: str) -> Path:
        return self.literature_dir / paper_id

    def exists(self, paper_id: str) -> bool:
        return (self._paper_dir(paper_id) / "metadata.json").exists()

    def save(self, paper: Paper, pdf_bytes: bytes | None = None) -> Path:
        paper_dir = self._paper_dir(paper.paper_id)
        paper_dir.mkdir(parents=True, exist_ok=True)
        (paper_dir / "metadata.json").write_text(
            json.dumps(paper.metadata_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (paper_dir / "text.json").write_text(
            json.dumps(
                [{"page_number": p.page_number, "text": p.text} for p in paper.pages],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        if pdf_bytes is not None:
            (paper_dir / "source.pdf").write_bytes(pdf_bytes)
        return paper_dir

    def load(self, paper_id: str) -> Paper:
        paper_dir = self._paper_dir(paper_id)
        meta_path = paper_dir / "metadata.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"paper not found: {paper_id}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        pages = json.loads((paper_dir / "text.json").read_text(encoding="utf-8"))
        return Paper.from_dict(meta, pages)

    def pdf_path(self, paper_id: str) -> Path | None:
        path = self._paper_dir(paper_id) / "source.pdf"
        return path if path.exists() else None

    def list_papers(self) -> list[dict]:
        """Metadata (no page text) for every ingested paper, newest first by
        directory mtime."""
        if not self.literature_dir.exists():
            return []
        rows: list[tuple[float, dict]] = []
        for meta_path in self.literature_dir.glob("*/metadata.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            rows.append((meta_path.stat().st_mtime, meta))
        rows.sort(key=lambda item: item[0], reverse=True)
        return [meta for _, meta in rows]

    def delete(self, paper_id: str) -> None:
        paper_dir = self._paper_dir(paper_id)
        if paper_dir.exists():
            shutil.rmtree(paper_dir)
