import json


def test_trust_policy_flags_current_snapshot_universe():
    from quantbench.review.trust_policy import assess_universe_trust

    assessment = assess_universe_trust(
        {"asset_class": "equity", "point_in_time": False, "covers_delisted": False, "source": "current"}
    )

    assert assessment.tier == "current_snapshot_survivorship_biased"
    assert assessment.severity == "warning"
    assert "survivorship" in assessment.message


def test_review_report_includes_launch_trust_policy():
    import pandas as pd

    from quantbench.review.report import run_review

    returns = pd.Series([0.01, -0.02, 0.03, 0.01] * 20)
    report = run_review(
        code="def compute(df):\n    return df['close'].pct_change()\n",
        returns=returns,
        cost_bps=5,
        rerun_at_cost=lambda _: {"sharpe": 1.0},
        rerun_with_code=lambda _: {"sharpe": 1.0},
        out_of_sample_data=pd.DataFrame({"close": range(80)}),
        run_on_data=lambda _: {"sharpe": 1.0},
        universe={"asset_class": "crypto", "point_in_time": True, "covers_delisted": False},
    )

    finding = next(item for item in report.findings if item.check == "launch_trust_policy")
    assert finding.detail["tier"] == "crypto_pit_snapshot_limited"


def test_crypto_seed_snapshot_loader_returns_packaged_seed():
    from quantbench.data.universe import crypto_seed_snapshots

    snapshots = crypto_seed_snapshots("2026-07-04", "2026-07-04")

    assert "2026-07-04" in snapshots
    assert "BTC/USDT:USDT" in snapshots["2026-07-04"]


def test_perpetual_schema_accepts_optional_open_interest():
    from quantbench.data.perpetual_schema import PerpetualMarketRow

    row = PerpetualMarketRow(
        timestamp="2026-07-04T00:00:00Z",
        symbol="BTC/USDT:USDT",
        close=100.0,
        volume=10.0,
        funding_rate=0.0001,
        open_interest=None,
    ).to_row()

    assert row["funding_rate"] == 0.0001
    assert row["open_interest"] is None


def test_retention_audit_detects_missing_slice(tmp_path, monkeypatch):
    from quantbench.api import run_reader
    from quantbench.data.retention import audit_run_data_retention

    monkeypatch.setattr(run_reader, "RUNS_DIR", tmp_path)
    run_dir = tmp_path / "run_missing"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps({"data_slices": [{"path": str(tmp_path / "missing.parquet"), "content_hash": "abc"}]}),
        encoding="utf-8",
    )

    report = audit_run_data_retention("run_missing")

    assert report["status"] == "failed"
    assert report["missing"] == [str(tmp_path / "missing.parquet")]


def test_llm_eval_works_with_fake_client(tmp_path):
    from quantbench.evals.llm_eval import run_llm_cases

    cases = tmp_path / "cases.yaml"
    cases.write_text(
        """
cases:
  - name: fake
    prompt: say risks
    required_findings: [survivorship, point-in-time]
""",
        encoding="utf-8",
    )

    class FakeClient:
        def complete(self, messages):
            return "survivorship and point-in-time limits"

    result = run_llm_cases(cases, FakeClient())[0]

    assert result.passed is True


def test_single_asset_signal_export_returns_structured_unsupported(monkeypatch):
    from quantbench.factors.entry import FactorEntry
    from quantbench.factors.signal_export import build_signal_export

    monkeypatch.setattr("quantbench.factors.signal_export.refresh_and_recompute_weights", lambda *_: None)
    entry = FactorEntry(
        name="single",
        family="momentum",
        asset_class="crypto",
        code="def compute(df): return df['close']",
        parameters=[],
        source_run_id="run_single",
        source_verdict="PROMISING",
        source_metrics={},
        source_findings=[],
        saved_from_rejected=False,
        saved_at="2026-07-04T00:00:00Z",
        lifecycle_state="candidate",
        lifecycle_history=[],
    )

    payload = build_signal_export(entry)

    assert payload["status"] == "unsupported"
    assert payload["reason"] == "single_asset_export_not_supported"
