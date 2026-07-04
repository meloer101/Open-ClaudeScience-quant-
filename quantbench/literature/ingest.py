from __future__ import annotations

import hashlib
import io
import re
import xml.etree.ElementTree as ET

import requests
from pypdf import PdfReader

from quantbench.literature.paper import PageText, Paper

_USER_AGENT = "quantbench/0.1"
_ARXIV_API = "http://export.arxiv.org/api/query"
_ARXIV_ATOM = "{http://www.w3.org/2005/Atom}"


def _paper_id_from_bytes(pdf_bytes: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    return digest[:16], digest


def _extract_pages(pdf_bytes: bytes) -> list[PageText]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages: list[PageText] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # pypdf can raise on malformed pages; keep the page, empty text
            text = ""
        pages.append(PageText(page_number=index, text=text.strip()))
    return pages


def _title_from_pages(pages: list[PageText]) -> str:
    """Best-effort title: first non-empty line of page 1. Callers with better
    metadata (arXiv) override this."""
    for page in pages:
        for line in page.text.splitlines():
            line = line.strip()
            if len(line) >= 8:
                return line[:200]
    return "Untitled paper"


def ingest_pdf_bytes(pdf_bytes: bytes, *, source: str, title: str | None = None,
                     authors: list[str] | None = None, source_kind: str = "pdf",
                     arxiv_id: str | None = None) -> Paper:
    if not pdf_bytes:
        raise ValueError("empty PDF bytes")
    paper_id, sha = _paper_id_from_bytes(pdf_bytes)
    pages = _extract_pages(pdf_bytes)
    if not any(page.text for page in pages):
        raise ValueError(
            "no extractable text in PDF (scanned/image-only PDFs need OCR, not supported in v1)"
        )
    return Paper(
        paper_id=paper_id,
        title=title or _title_from_pages(pages),
        authors=authors or [],
        source=source,
        source_kind=source_kind,
        sha256=sha,
        pages=pages,
        arxiv_id=arxiv_id,
    )


def ingest_pdf_with_bytes(path: str) -> tuple[Paper, bytes]:
    from pathlib import Path

    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")
    pdf_bytes = file_path.read_bytes()
    return ingest_pdf_bytes(pdf_bytes, source=str(file_path)), pdf_bytes


def ingest_pdf(path: str) -> Paper:
    return ingest_pdf_with_bytes(path)[0]


# --- arXiv --------------------------------------------------------------------

_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")


def parse_arxiv_id(url_or_id: str) -> str:
    """Accepts an arXiv URL (abs/pdf) or a bare id like 2101.01234 / 2101.01234v2."""
    match = _ARXIV_ID_RE.search(url_or_id)
    if not match:
        raise ValueError(f"could not parse an arXiv id from {url_or_id!r}")
    return match.group(1) + (match.group(2) or "")


def _fetch_arxiv_metadata(arxiv_id: str, *, session: requests.Session | None = None) -> dict:
    getter = session.get if session is not None else requests.get
    response = getter(
        _ARXIV_API,
        params={"id_list": arxiv_id.split("v")[0], "max_results": 1},
        timeout=30,
        headers={"User-Agent": _USER_AGENT},
    )
    response.raise_for_status()
    root = ET.fromstring(response.text)
    entry = root.find(f"{_ARXIV_ATOM}entry")
    if entry is None:
        return {"title": None, "authors": []}
    title_el = entry.find(f"{_ARXIV_ATOM}title")
    title = " ".join(title_el.text.split()) if title_el is not None and title_el.text else None
    authors = [
        name_el.text.strip()
        for author_el in entry.findall(f"{_ARXIV_ATOM}author")
        if (name_el := author_el.find(f"{_ARXIV_ATOM}name")) is not None and name_el.text
    ]
    return {"title": title, "authors": authors}


def _download_arxiv_pdf(arxiv_id: str, *, session: requests.Session | None = None) -> bytes:
    getter = session.get if session is not None else requests.get
    response = getter(
        f"https://arxiv.org/pdf/{arxiv_id}",
        timeout=60,
        headers={"User-Agent": _USER_AGENT},
    )
    response.raise_for_status()
    return response.content


def ingest_arxiv_with_bytes(url_or_id: str, *, session: requests.Session | None = None) -> tuple[Paper, bytes]:
    arxiv_id = parse_arxiv_id(url_or_id)
    meta = _fetch_arxiv_metadata(arxiv_id, session=session)
    pdf_bytes = _download_arxiv_pdf(arxiv_id, session=session)
    paper = ingest_pdf_bytes(
        pdf_bytes,
        source=f"https://arxiv.org/abs/{arxiv_id}",
        title=meta.get("title"),
        authors=meta.get("authors") or [],
        source_kind="arxiv",
        arxiv_id=arxiv_id,
    )
    return paper, pdf_bytes


def ingest_arxiv(url_or_id: str, *, session: requests.Session | None = None) -> Paper:
    return ingest_arxiv_with_bytes(url_or_id, session=session)[0]


def is_arxiv_reference(text: str) -> bool:
    lowered = text.strip().lower()
    return "arxiv.org" in lowered or bool(_ARXIV_ID_RE.fullmatch(text.strip()))


def ingest_with_bytes(source: str) -> tuple[Paper, bytes]:
    """Dispatch on the source string: arXiv url/id -> arXiv, else local PDF.
    Returns the Paper and the raw PDF bytes so callers can persist source.pdf
    (needed by the web viewer) regardless of source kind."""
    if is_arxiv_reference(source):
        return ingest_arxiv_with_bytes(source)
    return ingest_pdf_with_bytes(source)


def ingest(source: str) -> Paper:
    return ingest_with_bytes(source)[0]


def ingest_and_store(source: str, store) -> Paper:
    """Ingest and persist to a PaperStore (with raw PDF bytes). Single place that
    guarantees source.pdf is written for both local and arXiv papers."""
    paper, pdf_bytes = ingest_with_bytes(source)
    store.save(paper, pdf_bytes=pdf_bytes)
    return paper
