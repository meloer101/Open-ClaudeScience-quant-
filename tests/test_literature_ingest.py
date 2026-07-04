import pytest

from _pdf_fixture import make_text_pdf


def _write_pdf(tmp_path, name, pages):
    path = tmp_path / name
    path.write_bytes(make_text_pdf(pages))
    return path


def test_ingest_pdf_extracts_pages_and_deterministic_id(tmp_path):
    from quantbench.literature.ingest import ingest_pdf

    pdf = _write_pdf(
        tmp_path,
        "paper.pdf",
        [["Cross-Sectional Momentum", "We test 12-1 momentum."], ["Sharpe was 0.9 out of sample."]],
    )
    paper = ingest_pdf(str(pdf))

    assert paper.n_pages == 2
    assert "Momentum" in paper.pages[0].text
    assert "0.9" in paper.pages[1].text
    assert paper.title == "Cross-Sectional Momentum"
    assert paper.source_kind == "pdf"
    # Same bytes -> same id (content hash prefix), so re-ingesting de-duplicates.
    assert ingest_pdf(str(pdf)).paper_id == paper.paper_id


def test_ingest_rejects_pdf_with_no_extractable_text(tmp_path):
    from quantbench.literature.ingest import ingest_pdf

    pdf = _write_pdf(tmp_path, "blank.pdf", [[]])  # a page with no Tj text
    with pytest.raises(ValueError, match="no extractable text"):
        ingest_pdf(str(pdf))


def test_paper_store_round_trip_and_listing(tmp_path):
    from quantbench.literature.ingest import ingest_pdf_with_bytes
    from quantbench.literature.store import PaperStore

    pdf = _write_pdf(tmp_path, "paper.pdf", [["Title Line", "Body."]])
    paper, pdf_bytes = ingest_pdf_with_bytes(str(pdf))

    store = PaperStore(tmp_path / "lit")
    store.save(paper, pdf_bytes=pdf_bytes)

    loaded = store.load(paper.paper_id)
    assert loaded.full_text() == paper.full_text()
    assert store.pdf_path(paper.paper_id) is not None
    assert store.pdf_path(paper.paper_id).read_bytes() == pdf_bytes

    listing = store.list_papers()
    assert len(listing) == 1
    assert listing[0]["paper_id"] == paper.paper_id
    assert listing[0]["title"] == "Title Line"

    store.delete(paper.paper_id)
    assert not store.exists(paper.paper_id)


def test_page_range_text_is_one_indexed(tmp_path):
    from quantbench.literature.ingest import ingest_pdf

    pdf = _write_pdf(tmp_path, "p.pdf", [["page one"], ["page two"], ["page three"]])
    paper = ingest_pdf(str(pdf))

    pages = paper.page_range_text(2, 3)
    assert [p.page_number for p in pages] == [2, 3]
    assert "two" in pages[0].text


@pytest.mark.parametrize(
    "reference,expected",
    [
        ("https://arxiv.org/abs/2101.01234", "2101.01234"),
        ("https://arxiv.org/pdf/2101.01234v2", "2101.01234v2"),
        ("2101.01234", "2101.01234"),
        ("arXiv:2401.09999", "2401.09999"),
    ],
)
def test_parse_arxiv_id(reference, expected):
    from quantbench.literature.ingest import parse_arxiv_id

    assert parse_arxiv_id(reference) == expected


def test_is_arxiv_reference_discriminates_local_paths():
    from quantbench.literature.ingest import is_arxiv_reference

    assert is_arxiv_reference("https://arxiv.org/abs/2101.01234")
    assert is_arxiv_reference("2101.01234")
    assert not is_arxiv_reference("/Users/me/papers/momentum.pdf")
    assert not is_arxiv_reference("momentum.pdf")


def test_ingest_arxiv_uses_injected_session_no_real_network():
    """ingest_arxiv accepts a requests-like session, so the arXiv metadata +
    PDF fetch can be stubbed - exercised here with a fake session, zero network."""
    from types import SimpleNamespace

    from quantbench.literature.ingest import ingest_arxiv
    from _pdf_fixture import make_text_pdf

    atom = (
        '<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
        "<title>Fake Momentum Paper</title>"
        "<author><name>Ada Lovelace</name></author>"
        "</entry></feed>"
    )
    pdf_bytes = make_text_pdf([["Fake Momentum Paper", "A synthetic abstract."]])

    class FakeSession:
        def get(self, url, params=None, timeout=None, headers=None):
            if "export.arxiv.org" in url:
                return SimpleNamespace(text=atom, raise_for_status=lambda: None)
            return SimpleNamespace(content=pdf_bytes, raise_for_status=lambda: None)

    paper = ingest_arxiv("https://arxiv.org/abs/2101.01234", session=FakeSession())
    assert paper.title == "Fake Momentum Paper"
    assert paper.authors == ["Ada Lovelace"]
    assert paper.source_kind == "arxiv"
    assert paper.arxiv_id == "2101.01234"
