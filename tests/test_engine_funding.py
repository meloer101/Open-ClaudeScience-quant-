import pandas as pd

from quantbench.agent.helpers.research_notes_support import _append_crypto_perpetual_warning
from quantbench.agent.run_context import _RunContext
from quantbench.engine.funding import funding_cost_by_period


def test_funding_cost_by_period_sums_intraday_rows_within_rebalance_period():
    weights = pd.DataFrame(
        {"BTC/USDT": [1.0, 0.0]},
        index=pd.to_datetime(["2024-01-01", "2024-01-02"], utc=True),
    )
    funding_rates = pd.DataFrame(
        {
            "symbol": ["BTC/USDT", "BTC/USDT", "BTC/USDT"],
            "timestamp": pd.to_datetime(
                ["2024-01-01 00:00", "2024-01-01 08:00", "2024-01-01 16:00"],
                utc=True,
            ),
            "funding_rate": [0.01, 0.01, 0.01],
        }
    )

    result = funding_cost_by_period(weights, funding_rates)

    assert result.cost.iloc[0] == 0.03
    assert result.cost.iloc[1] == 0.0
    assert result.coverage["raw_rows"] == 3
    assert result.coverage["aligned_rows"] == 3


def test_funding_cost_by_period_reports_missing_period_symbol_coverage():
    weights = pd.DataFrame(
        {
            "BTC/USDT": [1.0, 1.0],
            "ETH/USDT": [-1.0, -1.0],
        },
        index=pd.to_datetime(["2024-01-01", "2024-01-02"], utc=True),
    )
    funding_rates = pd.DataFrame(
        {
            "symbol": ["BTC/USDT", "ETH/USDT", "BTC/USDT"],
            "timestamp": pd.to_datetime(
                ["2024-01-01 00:00", "2024-01-01 08:00", "2024-01-02 00:00"],
                utc=True,
            ),
            "funding_rate": [0.01, 0.02, 0.03],
        }
    )

    result = funding_cost_by_period(weights, funding_rates)

    assert result.coverage["expected_period_symbol_pairs"] == 4
    assert result.coverage["observed_period_symbol_pairs"] == 3
    assert result.coverage["missing_period_symbol_pairs"] == 1
    assert result.coverage["coverage_ratio"] == 0.75


def test_crypto_funding_warning_uses_aligned_coverage_numbers():
    ctx = _RunContext()
    ctx.funding_meta = {
        "alignment": {
            "coverage_ratio": 0.75,
            "missing_period_symbol_pairs": 1,
        },
        "failed": {},
    }

    warnings = _append_crypto_perpetual_warning(ctx)

    assert len(warnings) == 1
    assert "Aligned funding coverage=75.0%" in warnings[0]
    assert "missing period-symbol pairs=1" in warnings[0]


def test_crypto_funding_warning_is_suppressed_when_alignment_is_complete():
    ctx = _RunContext()
    ctx.funding_meta = {
        "alignment": {
            "coverage_ratio": 1.0,
            "missing_period_symbol_pairs": 0,
        },
        "failed": {},
    }

    assert _append_crypto_perpetual_warning(ctx) == []
    assert ctx.warnings == []
