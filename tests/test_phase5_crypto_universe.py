import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import yaml

from _fakes import FakeLLMClient


def test_fetch_top_symbols_by_volume_filters_active_usdt_swaps_and_sorts(monkeypatch):
    from quantbench.data.providers import ccxt_perpetual

    class FakeExchange:
        def load_markets(self):
            return {
                "BTC/USDT": {"symbol": "BTC/USDT", "quote": "USDT", "swap": True, "active": True},
                "ETH/USDT": {"symbol": "ETH/USDT", "quote": "USDT", "swap": True, "active": True},
                "SOL/USDT": {"symbol": "SOL/USDT", "quote": "USDT", "swap": True, "active": True},
                "DOGE/USDT": {"symbol": "DOGE/USDT", "quote": "USDT", "swap": True, "active": False},
                "BTC/USDC": {"symbol": "BTC/USDC", "quote": "USDC", "swap": True, "active": True},
                "BNB/USDT": {"symbol": "BNB/USDT", "quote": "USDT", "swap": False, "active": True},
            }

        def fetch_tickers(self):
            return {
                "BTC/USDT": {"quoteVolume": 100.0},
                "ETH/USDT": {"quoteVolume": 250.0},
                "SOL/USDT": {"quoteVolume": 150.0},
                "DOGE/USDT": {"quoteVolume": 999.0},
                "BTC/USDC": {"quoteVolume": 888.0},
                "BNB/USDT": {"quoteVolume": 777.0},
            }

    captured_options = {}

    def fake_exchange_factory(options):
        captured_options.update(options)
        return FakeExchange()

    # Mocks whichever exchange id ccxt_perpetual.CCXT_EXCHANGE_ID currently
    # points at, rather than hardcoding "okx"/"binance" - this test shouldn't
    # need editing again the next time the exchange is swapped.
    monkeypatch.setitem(
        sys.modules, "ccxt", SimpleNamespace(**{ccxt_perpetual.CCXT_EXCHANGE_ID: fake_exchange_factory})
    )

    result = ccxt_perpetual.fetch_top_symbols_by_volume(quote="USDT", limit=2)

    assert captured_options["enableRateLimit"] is True
    assert captured_options["options"]["defaultType"] == "swap"
    assert result == [
        {"symbol": "ETH/USDT", "quote_volume_24h": 250.0},
        {"symbol": "SOL/USDT", "quote_volume_24h": 150.0},
    ]


def test_fetch_top_symbols_by_volume_reads_okx_style_raw_info_quote_volume(monkeypatch):
    """Regression: found by testing against a real OKX universe build, which
    silently returned zero symbols - not an error - because OKX's swap
    tickers leave the ccxt-unified quoteVolume field None and only report 24h
    quote volume under the exchange-specific raw key "volCcy24h" in `info`.
    Every row would be filtered out as "no volume data" without this
    fallback, which is exactly the kind of silent-empty-result bug that's
    easy to miss since it doesn't raise."""
    from quantbench.data.providers import ccxt_perpetual

    class FakeExchange:
        def load_markets(self):
            return {
                "BTC/USDT:USDT": {"symbol": "BTC/USDT:USDT", "quote": "USDT", "swap": True, "active": True},
                "ETH/USDT:USDT": {"symbol": "ETH/USDT:USDT", "quote": "USDT", "swap": True, "active": True},
            }

        def fetch_tickers(self):
            return {
                "BTC/USDT:USDT": {"quoteVolume": None, "info": {"volCcy24h": "500.5"}},
                "ETH/USDT:USDT": {"quoteVolume": None, "info": {"volCcy24h": "900.25"}},
            }

    monkeypatch.setitem(
        sys.modules, "ccxt", SimpleNamespace(**{ccxt_perpetual.CCXT_EXCHANGE_ID: lambda options: FakeExchange()})
    )

    result = ccxt_perpetual.fetch_top_symbols_by_volume(quote="USDT", limit=2)

    assert result == [
        {"symbol": "ETH/USDT:USDT", "quote_volume_24h": 900.25},
        {"symbol": "BTC/USDT:USDT", "quote_volume_24h": 500.5},
    ]


def test_build_crypto_perpetual_universe_marks_non_point_in_time_snapshot(monkeypatch):
    from quantbench.data import universe

    monkeypatch.setattr(
        universe,
        "fetch_top_symbols_by_volume",
        lambda quote="USDT", limit=30: [
            {"symbol": "ETH/USDT", "quote_volume_24h": 250.0},
            {"symbol": "BTC/USDT", "quote_volume_24h": 100.0},
        ],
    )

    result = universe.build_universe("top_80_usdt_perpetual", "2024-12-31", limit=2)

    assert result.name == "top_usdt_perpetual"
    assert result.symbols == ["ETH/USDT", "BTC/USDT"]
    assert result.sample_limit == 2
    assert result.asset_class == "crypto"
    assert result.point_in_time is False
    assert "not as of `as_of_date`" in result.survivorship_bias_note
    assert "not a point-in-time universe" in result.survivorship_bias_note


def test_build_universe_parses_top_n_crypto_perpetual_name(monkeypatch):
    from quantbench.data import universe

    calls = []

    def fake_fetch_top_symbols_by_volume(quote="USDT", limit=30):
        calls.append((quote, limit))
        return [{"symbol": f"SYM{i}/USDT", "quote_volume_24h": float(100 - i)} for i in range(limit)]

    monkeypatch.setattr(universe, "fetch_top_symbols_by_volume", fake_fetch_top_symbols_by_volume)

    result = universe.build_universe("top_30_usdt_perpetual", "2024-12-31")

    assert calls == [("USDT", 30)]
    assert len(result.symbols) == 30
    assert result.asset_class == "crypto"


def test_sp500_universe_exposes_equity_asset_class(monkeypatch):
    from quantbench.data import universe

    monkeypatch.setattr(
        universe,
        "fetch_current_constituents",
        lambda: pd.DataFrame({"Symbol": [f"SYM{i}" for i in range(401)]}),
    )

    result = universe.build_sp500_universe("2026-07-01")

    assert result.asset_class == "equity"


def test_build_record_prefers_universe_asset_class_over_source_guess(tmp_path, monkeypatch):
    from quantbench.library.record import build_record

    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path)
    run_dir = tmp_path / "run_20260701_000000_crypto"
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": "run_20260701_000000_crypto",
        "user_request": "crypto cross section",
        "created_at": "2026-07-01T00:00:00+00:00",
        "metrics": {},
        "review": None,
    }
    config = {
        "hypothesis": "crypto cross section",
        "universe": {
            "name": "top_usdt_perpetual",
            "asset_class": "crypto",
            "source": "manual_snapshot",
            "symbols": ["ETH/USDT", "BTC/USDT"],
        },
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")

    record = build_record("run_20260701_000000_crypto")

    assert record.asset_class == "crypto"
    assert record.cross_sectional is True


def test_cross_sectional_crypto_uses_btc_benchmark_and_writes_funding_warning(tmp_path: Path, monkeypatch):
    from quantbench.agent import coordinator as coordinator_module
    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore
    from quantbench.data.universe import UniverseDefinition

    timestamps = pd.date_range("2023-01-01", periods=80, freq="1D", tz="UTC")
    panel = pd.DataFrame(
        {
            "timestamp": list(timestamps) * 2,
            "symbol": ["ETH/USDT"] * len(timestamps) + ["BTC/USDT"] * len(timestamps),
            "open": np.tile(np.linspace(100.0, 120.0, len(timestamps)), 2),
            "high": np.tile(np.linspace(101.0, 121.0, len(timestamps)), 2),
            "low": np.tile(np.linspace(99.0, 119.0, len(timestamps)), 2),
            "close": np.concatenate(
                [np.linspace(100.0, 120.0, len(timestamps)), np.linspace(80.0, 100.0, len(timestamps))]
            ),
            "volume": 1000.0,
        }
    )
    benchmark_requests = []

    def fake_build_universe(name, as_of_date, point_in_time=False, limit=None):
        return UniverseDefinition(
            name="top_usdt_perpetual",
            as_of_date=as_of_date,
            symbols=["ETH/USDT", "BTC/USDT"],
            point_in_time=False,
            survivorship_bias_note="crypto universe note",
            source="ccxt_binance_tickers",
            sample_limit=limit,
            asset_class="crypto",
        )

    def fake_fetch_universe_ohlcv(universe, timeframe, start, end):
        return panel, {"source": "unit-test", "cache_hit": False}

    def fake_fetch_benchmark_returns(fetch_params, current_df):
        benchmark_requests.append(fetch_params)
        returns = pd.Series(np.zeros(len(timestamps)), index=timestamps)
        return returns

    monkeypatch.setattr(coordinator_module, "build_universe", fake_build_universe)
    monkeypatch.setattr(coordinator_module, "fetch_universe_ohlcv", fake_fetch_universe_ohlcv)
    monkeypatch.setattr(coordinator_module, "_fetch_benchmark_returns", fake_fetch_benchmark_returns)

    signal_code = "def compute(df):\n    return df['close'].pct_change(20).fillna(0.0)\n"
    script = [
        (
            "tools",
            [
                (
                    "build_universe",
                    {"universe_name": "top_80_usdt_perpetual", "as_of_date": "2024-12-31", "limit": 2},
                )
            ],
        ),
        (
            "tools",
            [
                    (
                        "run_cross_sectional_backtest",
                        {
                            "code": signal_code,
                            "start": "2023-01-01",
                            "end": "2023-04-01",
                            "timeframe": "1d",
                            "n_groups": 2,
                        },
                    )
                ],
            ),
        ("text", "finished"),
    ]
    result = Coordinator(run_store=ArtifactStore(tmp_path / "runs"), llm=FakeLLMClient(script)).run("crypto cross section")

    assert benchmark_requests[-1]["symbol"] == "BTC/USDT"
    assert any("do not model funding rate carry cost" in warning for warning in result.warnings)

    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert any("do not model funding rate carry cost" in warning for warning in manifest["warnings"])
    beta_findings = [finding for finding in manifest["review"]["findings"] if finding["check"] == "beta_exposure"]
    assert beta_findings[-1]["detail"]["benchmark_symbol"] == "BTC/USDT"
    note = (result.run_dir / "research_note.md").read_text(encoding="utf-8")
    assert "do not model funding rate carry cost" in note


def test_cross_sectional_equity_still_uses_spy_benchmark(tmp_path: Path, monkeypatch):
    from quantbench.agent import coordinator as coordinator_module
    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore
    from quantbench.data.universe import UniverseDefinition

    timestamps = pd.date_range("2023-01-01", periods=80, freq="1D", tz="UTC")
    panel = pd.DataFrame(
        {
            "timestamp": list(timestamps) * 2,
            "symbol": ["AAA"] * len(timestamps) + ["BBB"] * len(timestamps),
            "open": np.tile(np.linspace(100.0, 120.0, len(timestamps)), 2),
            "high": np.tile(np.linspace(101.0, 121.0, len(timestamps)), 2),
            "low": np.tile(np.linspace(99.0, 119.0, len(timestamps)), 2),
            "close": np.concatenate(
                [np.linspace(100.0, 120.0, len(timestamps)), np.linspace(80.0, 100.0, len(timestamps))]
            ),
            "volume": 1000.0,
        }
    )
    benchmark_requests = []

    def fake_build_universe(name, as_of_date, point_in_time=False, limit=None):
        return UniverseDefinition(
            name="sp500",
            as_of_date=as_of_date,
            symbols=["AAA", "BBB"],
            point_in_time=False,
            survivorship_bias_note="equity universe note",
            source="wikipedia",
            sample_limit=limit,
            asset_class="equity",
        )

    monkeypatch.setattr(coordinator_module, "build_universe", fake_build_universe)
    monkeypatch.setattr(coordinator_module, "fetch_universe_ohlcv", lambda universe, timeframe, start, end: (panel, {}))
    monkeypatch.setattr(
        coordinator_module,
        "_fetch_benchmark_returns",
        lambda fetch_params, current_df: benchmark_requests.append(fetch_params)
        or pd.Series(np.zeros(len(timestamps)), index=timestamps),
    )

    signal_code = "def compute(df):\n    return df['close'].pct_change(20).fillna(0.0)\n"
    script = [
        ("tools", [("build_universe", {"universe_name": "sp500", "as_of_date": "2024-12-31", "limit": 2})]),
        (
            "tools",
            [
                    (
                        "run_cross_sectional_backtest",
                        {
                            "code": signal_code,
                            "start": "2023-01-01",
                            "end": "2023-04-01",
                            "timeframe": "1d",
                            "n_groups": 2,
                        },
                    )
                ],
            ),
        ("text", "finished"),
    ]

    Coordinator(run_store=ArtifactStore(tmp_path / "runs"), llm=FakeLLMClient(script)).run("equity cross section")

    assert benchmark_requests[-1]["symbol"] == "SPY"
