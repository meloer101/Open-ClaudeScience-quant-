import json
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


def test_load_mcp_config_uses_explicit_tool_whitelist_and_defaults(tmp_path: Path):
    from quantbench.skills.mcp_adapter import load_mcp_config

    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "market",
                        "transport": {"type": "stdio", "command": "python", "args": ["-m", "server"]},
                    },
                    {
                        "name": "fundamentals",
                        "transport": {"type": "stdio", "command": "python", "args": ["server.py"], "env": {"A": "B"}},
                        "enabled_tools": ["get_fundamentals"],
                        "allow_write": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    servers = load_mcp_config(config_path)

    assert [server.name for server in servers] == ["market", "fundamentals"]
    assert servers[0].enabled_tools == []
    assert servers[0].allow_write is False
    assert servers[1].enabled_tools == ["get_fundamentals"]
    assert servers[1].transport.command == "python"
    assert servers[1].transport.env == {"A": "B"}


def test_load_mcp_config_accepts_claude_mcpservers_format(tmp_path: Path):
    from quantbench.skills.mcp_adapter import load_mcp_config

    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "filesystem": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"],
                        "env": {"FOO": "bar"},
                        "quantbench": {"enabledTools": ["read_file"], "allowWrite": False},
                    },
                    "remote": {"type": "http", "url": "https://mcp.example.com/mcp"},
                }
            }
        ),
        encoding="utf-8",
    )

    servers = load_mcp_config(config_path, scope="user")

    assert [server.name for server in servers] == ["filesystem", "remote"]
    assert servers[0].transport.command == "npx"
    assert servers[0].enabled_tools == ["read_file"]
    assert servers[0].scope == "user"
    assert servers[1].transport.type == "http"
    assert servers[1].transport.url == "https://mcp.example.com/mcp"


def test_load_merged_mcp_config_project_overrides_user_and_filters_disabled(tmp_path: Path):
    from quantbench.skills.mcp_adapter import load_merged_mcp_config

    user_config = tmp_path / "user_mcp.json"
    project_config = tmp_path / "project_mcp.json"
    user_config.write_text(
        json.dumps({"mcpServers": {"shared": {"command": "python", "args": ["user.py"]}, "user-only": {"command": "u"}}}),
        encoding="utf-8",
    )
    project_config.write_text(
        json.dumps({"mcpServers": {"shared": {"command": "python", "args": ["project.py"]}, "off": {"command": "off"}}}),
        encoding="utf-8",
    )

    servers = load_merged_mcp_config(
        [("user", user_config), ("project", project_config)],
        settings={"mcp": {"disabledServers": ["off"]}},
    )

    assert [server.name for server in servers] == ["shared", "user-only"]
    shared = next(server for server in servers if server.name == "shared")
    assert shared.scope == "project"
    assert shared.transport.args == ["project.py"]


def test_load_merged_mcp_config_legacy_has_lowest_default_priority(tmp_path: Path, monkeypatch):
    from quantbench.skills import mcp_adapter
    from quantbench.skills.mcp_adapter import load_merged_mcp_config

    legacy_config = tmp_path / "legacy.json"
    user_config = tmp_path / "user.json"
    project_config = tmp_path / "project.json"
    legacy_config.write_text(json.dumps({"mcpServers": {"x": {"command": "LEGACY"}}}), encoding="utf-8")
    user_config.write_text(json.dumps({"mcpServers": {"x": {"command": "USER"}}}), encoding="utf-8")
    project_config.write_text(json.dumps({"mcpServers": {"x": {"command": "PROJECT"}}}), encoding="utf-8")
    monkeypatch.setattr(mcp_adapter, "MCP_SERVERS_CONFIG", legacy_config)
    monkeypatch.setattr(mcp_adapter, "USER_MCP_CONFIG", user_config)
    monkeypatch.setattr(mcp_adapter, "PROJECT_MCP_CONFIG", project_config)

    servers = load_merged_mcp_config(settings={})

    assert len(servers) == 1
    assert servers[0].transport.command == "PROJECT"
    assert servers[0].scope == "project"


def test_load_mcp_config_skips_invalid_servers_with_warning(tmp_path: Path):
    from quantbench.skills.mcp_adapter import load_mcp_config

    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text(
        json.dumps(
            {
                "servers": [
                    {"name": "missing_transport", "enabled_tools": ["get_ohlcv"]},
                    {
                        "name": "ok",
                        "transport": {"type": "stdio", "command": "python", "args": ["server.py"]},
                        "enabled_tools": ["get_ohlcv"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.warns(UserWarning, match="missing_transport"):
        servers = load_mcp_config(config_path)

    assert [server.name for server in servers] == ["ok"]


def test_is_readonly_tool_rejects_obvious_side_effects():
    from quantbench.skills.mcp_adapter import is_readonly_tool

    assert is_readonly_tool(SimpleNamespace(name="get_ohlcv", description="Read price bars"))
    assert not is_readonly_tool(SimpleNamespace(name="create_order", description="Place a trade"))
    assert not is_readonly_tool(SimpleNamespace(name="delete_x", description="Read data"))
    assert not is_readonly_tool(SimpleNamespace(name="send_report", description="Email results"))
    assert not is_readonly_tool(SimpleNamespace(name="prices", description="Execute an order"))


def test_authorization_required_hint_detects_auth_challenges():
    from quantbench.skills.mcp_adapter import authorization_required_hint

    assert authorization_required_hint("HTTPStatusError: 401 Unauthorized") is not None
    assert authorization_required_hint("Server responded 403 Forbidden") is not None
    assert authorization_required_hint("WWW-Authenticate: Bearer") is not None
    assert authorization_required_hint("oauth token required") is not None
    # Non-auth failures fall through to the raw error.
    assert authorization_required_hint("TimeoutError: timed out after 5s") is None
    assert authorization_required_hint("ConnectionRefusedError: [Errno 61]") is None


def test_mcp_manager_builds_registry_skill_and_records_audit(tmp_path: Path):
    from quantbench.agent.run_context import _RunContext
    from quantbench.skills.mcp_adapter import MCPClientManager, MCPServerConfig, StdioTransportConfig
    from quantbench.skills.registry import SkillRegistry

    server_path = tmp_path / "mock_mcp_server.py"
    server_path.write_text(
        textwrap.dedent(
            """
            from mcp.server.fastmcp import FastMCP

            mcp = FastMCP("mock")

            @mcp.tool()
            def get_ohlcv(symbol: str) -> dict:
                return {"symbol": symbol, "close": [100.0, 101.5]}

            @mcp.tool()
            def get_secret(symbol: str) -> dict:
                return {"symbol": symbol, "secret": True}

            if __name__ == "__main__":
                mcp.run()
            """
        ),
        encoding="utf-8",
    )
    ctx = _RunContext()
    manager = MCPClientManager(
        [
            MCPServerConfig(
                name="mock",
                transport=StdioTransportConfig(command="python3", args=[str(server_path)], env={}),
                enabled_tools=["get_ohlcv"],
            )
        ],
        ctx,
        call_timeout_s=5.0,
    )
    try:
        registry = SkillRegistry()
        for skill in manager.build_skills():
            registry.register(skill)

        assert [schema["function"]["name"] for schema in registry.schemas()] == ["mcp_mock_get_ohlcv"]
        result = registry.execute("mcp_mock_get_ohlcv", {"symbol": "AAPL"})

        assert result == {"symbol": "AAPL", "close": [100.0, 101.5]}
        assert registry.execute("mcp_mock_get_secret", {"symbol": "AAPL"}) == {"error": "unknown tool: mcp_mock_get_secret"}
        assert len(ctx.mcp_calls) == 1
        assert ctx.mcp_calls[0]["server"] == "mock"
        assert ctx.mcp_calls[0]["tool"] == "get_ohlcv"
        assert ctx.mcp_calls[0]["args"] == {"symbol": "AAPL"}
        assert len(ctx.mcp_calls[0]["result_sha256"]) == 64
    finally:
        manager.close()


def test_mcp_manager_rejects_allow_write_server_without_connecting():
    from quantbench.agent.run_context import _RunContext
    from quantbench.skills.mcp_adapter import MCPClientManager, MCPServerConfig, StdioTransportConfig

    manager = MCPClientManager(
        [
            MCPServerConfig(
                name="writer",
                transport=StdioTransportConfig(command="definitely-not-a-real-command"),
                enabled_tools=["get_ohlcv"],
                allow_write=True,
            )
        ],
        _RunContext(),
        call_timeout_s=0.1,
    )
    try:
        with pytest.warns(UserWarning, match="allow_write=true"):
            assert manager.build_skills() == []
    finally:
        manager.close()


def test_mcp_tool_error_returns_structured_error_and_audit(tmp_path: Path):
    from quantbench.agent.run_context import _RunContext
    from quantbench.skills.mcp_adapter import MCPClientManager, MCPServerConfig, StdioTransportConfig
    from quantbench.skills.registry import SkillRegistry

    server_path = tmp_path / "error_mcp_server.py"
    server_path.write_text(
        textwrap.dedent(
            """
            from mcp.server.fastmcp import FastMCP

            mcp = FastMCP("error")

            @mcp.tool()
            def get_ohlcv(symbol: str) -> dict:
                raise RuntimeError(f"no data for {symbol}")

            if __name__ == "__main__":
                mcp.run()
            """
        ),
        encoding="utf-8",
    )
    ctx = _RunContext()
    manager = MCPClientManager(
        [
            MCPServerConfig(
                name="mock",
                transport=StdioTransportConfig(command="python3", args=[str(server_path)], env={}),
                enabled_tools=["get_ohlcv"],
            )
        ],
        ctx,
        call_timeout_s=5.0,
    )
    try:
        registry = SkillRegistry()
        for skill in manager.build_skills():
            registry.register(skill)

        result = registry.execute("mcp_mock_get_ohlcv", {"symbol": "AAPL"})

        assert "error" in result
        assert "no data for AAPL" in result["error"]
        assert ctx.mcp_calls[0]["error"] == result["error"]
    finally:
        manager.close()


def test_mcp_tool_timeout_returns_structured_error_and_audit(tmp_path: Path):
    from quantbench.agent.run_context import _RunContext
    from quantbench.skills.mcp_adapter import MCPClientManager, MCPServerConfig, StdioTransportConfig
    from quantbench.skills.registry import SkillRegistry

    server_path = tmp_path / "slow_mcp_server.py"
    server_path.write_text(
        textwrap.dedent(
            """
            import time
            from mcp.server.fastmcp import FastMCP

            mcp = FastMCP("slow")

            @mcp.tool()
            def get_ohlcv(symbol: str) -> dict:
                time.sleep(1.0)
                return {"symbol": symbol}

            if __name__ == "__main__":
                mcp.run()
            """
        ),
        encoding="utf-8",
    )
    ctx = _RunContext()
    manager = MCPClientManager(
        [
            MCPServerConfig(
                name="mock",
                transport=StdioTransportConfig(command="python3", args=[str(server_path)], env={}),
                enabled_tools=["get_ohlcv"],
            )
        ],
        ctx,
        call_timeout_s=5.0,
    )
    try:
        registry = SkillRegistry()
        for skill in manager.build_skills():
            registry.register(skill)
        manager.call_timeout_s = 0.2

        result = registry.execute("mcp_mock_get_ohlcv", {"symbol": "AAPL"})

        assert "timed out" in result["error"]
        assert "timed out" in ctx.mcp_calls[0]["error"]
    finally:
        manager.close()


def test_run_manifest_includes_mcp_calls(tmp_path: Path):
    from quantbench.artifact.store import ArtifactStore

    run = ArtifactStore(tmp_path).create_run("request")
    run.finalize(
        data_hash="sha256:data",
        code_hash="sha256:code",
        mcp_calls=[{"server": "mock", "tool": "get_ohlcv", "result_sha256": "a" * 64}],
    )

    manifest = json.loads((run.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mcp_calls"] == [{"server": "mock", "tool": "get_ohlcv", "result_sha256": "a" * 64}]


def test_run_review_adds_external_data_info_without_changing_verdict():
    from quantbench.review.report import run_review

    returns = pd.Series([0.01, 0.02, -0.01, 0.005] * 20)
    data = pd.DataFrame({"close": range(len(returns))})
    report = run_review(
        code="def compute(df):\n    return df['close'].pct_change().fillna(0)\n",
        returns=returns,
        cost_bps=5.0,
        rerun_at_cost=lambda _bps: {"sharpe": 1.0},
        rerun_with_code=lambda _code: {"sharpe": 1.0},
        out_of_sample_data=data,
        run_on_data=lambda _data: {"sharpe": 1.0},
        mcp_calls=[{"server": "mock", "tool": "get_ohlcv"}],
    )

    finding = next(item for item in report.findings if item.check == "external_data_unverified")
    assert finding.severity == "info"
    assert "mock/get_ohlcv" in finding.message
    assert report.verdict != "REJECTED"


def test_coordinator_mcp_tool_call_flows_into_manifest_and_review(tmp_path: Path, monkeypatch):
    from _fakes import FakeLLMClient
    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore

    server_path = tmp_path / "mock_mcp_server.py"
    server_path.write_text(
        textwrap.dedent(
            """
            from mcp.server.fastmcp import FastMCP

            mcp = FastMCP("mock")

            @mcp.tool()
            def get_ohlcv(symbol: str) -> dict:
                return {"symbol": symbol, "close": [100.0, 101.0]}

            if __name__ == "__main__":
                mcp.run()
            """
        ),
        encoding="utf-8",
    )
    mcp_config = tmp_path / "mcp_servers.json"
    mcp_config.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "mock",
                        "transport": {"type": "stdio", "command": "python3", "args": [str(server_path)]},
                        "enabled_tools": ["get_ohlcv"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("quantbench.agent.coordinator.MCP_SERVERS_CONFIG", mcp_config)

    def fake_fetch_ohlcv(symbol: str, timeframe: str, start: str, end: str):
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2024-01-01", periods=80, freq="D"),
                "open": [100.0 + i for i in range(80)],
                "high": [101.0 + i for i in range(80)],
                "low": [99.0 + i for i in range(80)],
                "close": [100.5 + i for i in range(80)],
                "volume": [1000.0 + i for i in range(80)],
            }
        )
        path = tmp_path / f"{symbol.replace('/', '_')}.parquet"
        df.to_parquet(path, index=False)
        return path, df, {"source": "test", "symbol": symbol, "timeframe": timeframe, "start": start, "end": end}

    monkeypatch.setattr("quantbench.agent.coordinator.fetch_ohlcv", fake_fetch_ohlcv)
    code = "def compute(df):\n    return df['close'].pct_change().fillna(0.0)\n"
    script = [
        ("tools", [("mcp_mock_get_ohlcv", {"symbol": "AAPL"})]),
        ("tools", [("fetch_ohlcv", {"symbol": "AAPL", "timeframe": "1d", "start": "2024-01-01", "end": "2024-03-20"})]),
        ("tools", [("run_signal_backtest", {"code": code, "cost_bps": 5})]),
        ("text", "done"),
    ]

    result = Coordinator(run_store=ArtifactStore(tmp_path / "runs"), llm=FakeLLMClient(script)).run("use external data")

    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mcp_calls"][0]["server"] == "mock"
    assert manifest["mcp_calls"][0]["tool"] == "get_ohlcv"
    findings = manifest["review"]["findings"]
    external = next(item for item in findings if item["check"] == "external_data_unverified")
    assert external["severity"] == "info"
    assert external["detail"]["sources"] == ["mock/get_ohlcv"]
