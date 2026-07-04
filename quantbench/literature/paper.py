from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PageText:
    """One page's extracted text. page_number is 1-indexed to match how a
    reader (and the model's page_anchors) refers to pages."""

    page_number: int
    text: str


@dataclass(frozen=True)
class Paper:
    """A single ingested paper. paper_id is a content hash prefix so the same
    PDF always resolves to the same id (reproducible, de-duplicated). `source`
    records where it came from (local path or arXiv url) for provenance."""

    paper_id: str
    title: str
    authors: list[str]
    source: str
    source_kind: str  # "pdf" | "arxiv"
    sha256: str
    pages: list[PageText] = field(default_factory=list)
    arxiv_id: str | None = None

    @property
    def n_pages(self) -> int:
        return len(self.pages)

    def full_text(self) -> str:
        return "\n\n".join(page.text for page in self.pages)

    def page_range_text(self, start: int, end: int) -> list[PageText]:
        """Pages with page_number in [start, end] inclusive (1-indexed)."""
        return [page for page in self.pages if start <= page.page_number <= end]

    def citation(self) -> str:
        who = ", ".join(self.authors) if self.authors else "unknown authors"
        return f"{who}. {self.title}. ({self.source})"

    def metadata_dict(self) -> dict:
        """Serializable metadata WITHOUT the (large) page text - the page text
        lives in text.json alongside it."""
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "authors": self.authors,
            "source": self.source,
            "source_kind": self.source_kind,
            "sha256": self.sha256,
            "arxiv_id": self.arxiv_id,
            "n_pages": self.n_pages,
        }

    def to_dict(self) -> dict:
        payload = self.metadata_dict()
        payload["pages"] = [dataclasses.asdict(page) for page in self.pages]
        return payload

    @classmethod
    def from_dict(cls, meta: dict, pages: list[dict]) -> "Paper":
        return cls(
            paper_id=meta["paper_id"],
            title=meta["title"],
            authors=list(meta.get("authors") or []),
            source=meta["source"],
            source_kind=meta["source_kind"],
            sha256=meta["sha256"],
            arxiv_id=meta.get("arxiv_id"),
            pages=[PageText(page_number=p["page_number"], text=p["text"]) for p in pages],
        )

    def literature_source(self, page_anchors: list[int] | None = None) -> dict:
        """The provenance block written into run manifest / library records /
        research notes. `page_anchors` are the pages the extraction cited."""
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "authors": self.authors,
            "source": self.source,
            "source_kind": self.source_kind,
            "arxiv_id": self.arxiv_id,
            "citation": self.citation(),
            "page_anchors": sorted(set(page_anchors)) if page_anchors else [],
        }
