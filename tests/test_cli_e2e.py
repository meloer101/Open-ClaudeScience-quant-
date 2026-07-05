import json

from click.testing import CliRunner

from _fakes import FakeLLMClient


def test_cli_generates_phase0_artifacts(tmp_path, monkeypatch):
    """Drives the real CLI entrypoint end-to-end, with the LLM call replaced by
    a scripted fake so this test doesn't need network access or an API key."""
    monkeypatch.setattr("quantbench.agent.coordinator.RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr("quantbench.data.cache.DATA_CACHE_DIR", tmp_path / "data_cache")

    signal_code = (
        "def compute(df):\n"
        "    return df['close'].pct_change().fillna(0.0)\n"
    )
    script = [
        (
            "tools",
            [("fetch_ohlcv", {"symbol": "BTC/USDT", "timeframe": "4h", "start": "2023-01-01", "end": "2023-03-01"})],
        ),
        ("tools", [("run_signal_backtest", {"code": signal_code, "cost_bps": 5})]),
        ("text", "Backtest complete; treat as preliminary, Phase 0 has no reviewer yet."),
    ]
    monkeypatch.setattr("quantbench.agent.coordinator.LLMClient", lambda model: FakeLLMClient(script))

    from quantbench.cli import main

    result = CliRunner().invoke(
        main, ["测试一个简单动量信号在 BTC/USDT 4h 上的表现，2023-01-01 到 2023-03-01"]
    )

    assert result.exit_code == 0, result.output
    assert "Artifact directory:" in result.output

    run_dirs = list((tmp_path / "runs").glob("run_*"))
    assert len(run_dirs) == 1
    names = {path.name for path in run_dirs[0].iterdir()}
    assert {
        "config.yaml",
        "signal.py",
        "backtest_result.json",
        "equity_curve.png",
        "drawdown.png",
        "research_note.md",
        "manifest.json",
    }.issubset(names)

    manifest = json.loads((run_dirs[0] / "manifest.json").read_text(encoding="utf-8"))
    assert [step["tool"] for step in manifest["steps"]] == ["fetch_ohlcv", "run_signal_backtest"]


def test_cli_mcp_add_list_disable_remove(tmp_path, monkeypatch):
    """Drives the `quantbench mcp` lifecycle against tmp config files (no real ~/.quantbench)."""
    user_mcp = tmp_path / "mcp.json"
    project_mcp = tmp_path / ".mcp.json"
    legacy_mcp = tmp_path / "legacy.json"
    user_settings = tmp_path / "settings.json"
    project_settings = tmp_path / "project_settings.json"
    monkeypatch.setattr("quantbench.config_management.USER_MCP_CONFIG", user_mcp)
    monkeypatch.setattr("quantbench.config_management.PROJECT_MCP_CONFIG", project_mcp)
    monkeypatch.setattr("quantbench.skills.mcp_adapter.USER_MCP_CONFIG", user_mcp)
    monkeypatch.setattr("quantbench.skills.mcp_adapter.PROJECT_MCP_CONFIG", project_mcp)
    monkeypatch.setattr("quantbench.skills.mcp_adapter.MCP_SERVERS_CONFIG", legacy_mcp)
    monkeypatch.setattr("quantbench.settings.USER_SETTINGS_FILE", user_settings)
    monkeypatch.setattr("quantbench.settings.PROJECT_SETTINGS_FILE", project_settings)
    monkeypatch.setattr("quantbench.settings.SETTINGS_FILES", [user_settings, project_settings])

    from quantbench.cli import main

    runner = CliRunner()

    added = runner.invoke(main, ["mcp", "add-json", "fs", '{"command": "npx", "args": ["-y", "server-fs"]}'])
    assert added.exit_code == 0, added.output

    listed = runner.invoke(main, ["mcp", "list"])
    assert listed.exit_code == 0, listed.output
    assert "fs" in listed.output
    assert "True" in listed.output  # enabled column

    disabled = runner.invoke(main, ["mcp", "disable", "fs"])
    assert disabled.exit_code == 0, disabled.output
    assert json.loads(user_settings.read_text(encoding="utf-8"))["mcp"]["disabledServers"] == ["fs"]

    relisted = runner.invoke(main, ["mcp", "list"])
    assert "False" in relisted.output  # now shows disabled

    removed = runner.invoke(main, ["mcp", "remove", "fs"])
    assert removed.exit_code == 0, removed.output
    assert "mcpServers" not in user_mcp.read_text(encoding="utf-8") or "fs" not in user_mcp.read_text(encoding="utf-8")


def test_cli_mcp_test_reports_not_found(tmp_path, monkeypatch):
    user_mcp = tmp_path / "mcp.json"
    project_mcp = tmp_path / ".mcp.json"
    legacy_mcp = tmp_path / "legacy.json"
    monkeypatch.setattr("quantbench.config_management.USER_MCP_CONFIG", user_mcp)
    monkeypatch.setattr("quantbench.config_management.PROJECT_MCP_CONFIG", project_mcp)
    monkeypatch.setattr("quantbench.skills.mcp_adapter.USER_MCP_CONFIG", user_mcp)
    monkeypatch.setattr("quantbench.skills.mcp_adapter.PROJECT_MCP_CONFIG", project_mcp)
    monkeypatch.setattr("quantbench.skills.mcp_adapter.MCP_SERVERS_CONFIG", legacy_mcp)

    from quantbench.cli import main

    result = CliRunner().invoke(main, ["mcp", "test", "ghost"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()
