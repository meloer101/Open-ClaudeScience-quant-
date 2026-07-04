import json

from _fakes import FakeLLMClient
from _pdf_fixture import make_text_pdf


def _paper(pages):
    from quantbench.literature.ingest import ingest_pdf_bytes

    return ingest_pdf_bytes(make_text_pdf(pages), source="test.pdf")


_EXTRACTION_JSON = json.dumps(
    {
        "factor_name": "momentum_12_1",
        "economic_hypothesis": "Past winners keep winning over the medium term.",
        "formula": "r_{t-12..t-1}",
        "compute_spec": "df['close'].pct_change(231).shift(21)",
        "suggested_universe": "sp500",
        "suggested_timeframe": "1d",
        "asset_class": "equity",
        "direction": "long_high",
        "reported_results": {"sharpe": 0.9, "annual_return": 0.11, "rank_ic": 0.04, "sample_period": "1990-2010"},
        "page_anchors": [1, 2],
        "assumptions": ["equal-weight deciles"],
        "known_caveats": ["ignores transaction costs"],
    }
)


def test_extract_factor_parses_structured_extraction():
    from quantbench.literature.agent import extract_factor

    paper = _paper([["Momentum", "Definition on this page."], ["Results: Sharpe 0.9."]])
    llm = FakeLLMClient([("text", _EXTRACTION_JSON)])

    extraction = extract_factor(llm, paper)

    assert extraction.factor_name == "momentum_12_1"
    assert "winners" in extraction.economic_hypothesis
    assert extraction.reported_results["sharpe"] == 0.9
    assert extraction.page_anchors == [1, 2]
    assert extraction.assumptions == ["equal-weight deciles"]
    assert extraction.direction == "long_high"


def test_extract_factor_uses_read_paper_section_tool():
    from quantbench.literature.agent import extract_factor

    paper = _paper([["Intro page"], ["The factor is defined here on page 2."], ["Page 3 results"]])
    # First the model reads page 2, then returns its extraction JSON.
    llm = FakeLLMClient(
        [
            ("tools", [("read_paper_section", {"start_page": 2})]),
            ("text", _EXTRACTION_JSON),
        ]
    )

    extraction = extract_factor(llm, paper)
    assert extraction.factor_name == "momentum_12_1"

    # The tool result (page 2 text) must have been fed back to the model as a
    # tool message on the second turn.
    second_turn_messages = llm.calls[1][0]
    tool_messages = [m for m in second_turn_messages if m.get("role") == "tool"]
    assert tool_messages
    assert "page 2" in tool_messages[0]["content"]


def test_read_paper_section_skill_bounds_and_errors():
    from quantbench.literature.agent import _build_read_section_skill

    paper = _paper([["one"], ["two"], ["three"]])
    skill = _build_read_section_skill(paper)

    ok = skill.fn(start_page=1, end_page=2)
    assert [p["page_number"] for p in ok["pages"]] == [1, 2]
    assert ok["n_pages_total"] == 3

    single = skill.fn(start_page=3)
    assert [p["page_number"] for p in single["pages"]] == [3]

    assert "error" in skill.fn(start_page=0)
    assert "error" in skill.fn(start_page=9, end_page=10)


def test_extraction_defaults_when_fields_missing():
    from quantbench.literature.agent import extract_factor

    paper = _paper([["a"], ["b"]])
    llm = FakeLLMClient([("text", json.dumps({"factor_name": "x", "compute_spec": "df['close']"}))])

    extraction = extract_factor(llm, paper)
    assert extraction.factor_name == "x"
    assert extraction.reported_results == {}
    assert extraction.page_anchors == []
    assert extraction.known_caveats == []
