import json

from _pdf_fixture import make_text_pdf
from test_llm_usage_tracking import FakeUsageScriptedLLMClient


_EXTRACTION_JSON = json.dumps(
    {
        "factor_name": "momentum_12_1",
        "economic_hypothesis": "Past winners keep winning.",
        "formula": "r_{t-12..t-1}",
        "compute_spec": "df['close'].pct_change(231).shift(21)",
        "suggested_universe": "sp500",
        "asset_class": "equity",
        "direction": "long_high",
        "reported_results": {"sharpe": 0.9, "annual_return": 0.11, "rank_ic": 0.04},
        "page_anchors": [1, 2],
        "assumptions": ["equal-weight deciles"],
        "known_caveats": ["ignores transaction costs"],
    }
)


def _ingest_fixture(tmp_path):
    from quantbench.literature.ingest import ingest_pdf_with_bytes
    from quantbench.literature.store import PaperStore

    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(
        make_text_pdf([["Momentum Paper", "12-1 momentum."], ["Reported Sharpe 0.9."]])
    )
    paper, pdf_bytes = ingest_pdf_with_bytes(str(pdf))
    store = PaperStore(tmp_path / "lit")
    store.save(paper, pdf_bytes=pdf_bytes)
    return store, paper


def _run(tmp_path, monkeypatch):
    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore

    monkeypatch.setattr("litellm.completion_cost", lambda completion_response, model: 0.0007)
    store, paper = _ingest_fixture(tmp_path)
    # Turn 1: Literature Agent extraction. Turn 2: main coordinator loop (no
    # tools -> empty metrics; the reproduction table still forms with the
    # paper's reported numbers and null 'reproduced' values).
    llm = FakeUsageScriptedLLMClient([("text", _EXTRACTION_JSON), ("text", "done, no backtest in this test")])
    coordinator = Coordinator(run_store=ArtifactStore(tmp_path / "runs"), llm=llm)
    result = coordinator.run_from_paper(paper.paper_id, paper_store=store)
    return result, paper


def test_run_from_paper_writes_extraction_and_comparison_artifacts(tmp_path, monkeypatch):
    result, paper = _run(tmp_path, monkeypatch)

    extraction = json.loads((result.run_dir / "factor_extraction.json").read_text(encoding="utf-8"))
    assert extraction["factor_name"] == "momentum_12_1"

    comparison = json.loads((result.run_dir / "reproduction_comparison.json").read_text(encoding="utf-8"))
    metrics = {row["metric"]: row for row in comparison["rows"]}
    assert metrics["sharpe"]["reported"] == 0.9
    assert metrics["annual_return"]["reported"] == 0.11
    assert metrics["rank_ic"]["reported"] == 0.04
    assert comparison["literature_source"]["paper_id"] == paper.paper_id


def test_run_from_paper_appends_comparison_to_research_note(tmp_path, monkeypatch):
    result, _ = _run(tmp_path, monkeypatch)
    note = (result.run_dir / "research_note.md").read_text(encoding="utf-8")
    assert "文献复现对比" in note
    assert "论文报告" in note


def test_run_from_paper_records_literature_source_and_usage_in_manifest(tmp_path, monkeypatch):
    result, paper = _run(tmp_path, monkeypatch)

    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["literature_source"]["paper_id"] == paper.paper_id
    assert manifest["literature_source"]["page_anchors"] == [1, 2]

    steps = {record["step"] for record in manifest["llm_usage"]}
    assert "subagent:literature" in steps  # extraction cost is now visible


def test_run_from_paper_config_carries_literature_source(tmp_path, monkeypatch):
    import yaml

    result, paper = _run(tmp_path, monkeypatch)
    config = yaml.safe_load((result.run_dir / "config.yaml").read_text(encoding="utf-8"))
    assert config["literature_source"]["paper_id"] == paper.paper_id


def test_library_can_filter_by_literature_source(tmp_path, monkeypatch):
    result, paper = _run(tmp_path, monkeypatch)
    # Point the library reader at this test's runs dir.
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path / "runs")

    from quantbench.library.index import ExperimentIndex

    matched = ExperimentIndex.build().filter(source=paper.paper_id).records
    assert [record.run_id for record in matched] == [result.run_id]
    assert matched[0].literature_paper_id == paper.paper_id

    # A non-matching source returns nothing.
    assert ExperimentIndex.build().filter(source="nonexistent-paper").records == []
