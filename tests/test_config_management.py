import json

import pytest


@pytest.fixture
def scoped_config(tmp_path, monkeypatch):
    """Redirect every MCP/skill/settings path to tmp_path for isolated round-trip tests."""
    user_mcp = tmp_path / "mcp.json"
    project_mcp = tmp_path / ".mcp.json"
    legacy_mcp = tmp_path / "legacy.json"
    user_skills = tmp_path / "skills"
    user_settings = tmp_path / "user_settings.json"
    project_settings = tmp_path / "project_settings.json"
    monkeypatch.setattr("quantbench.config_management.USER_MCP_CONFIG", user_mcp)
    monkeypatch.setattr("quantbench.config_management.PROJECT_MCP_CONFIG", project_mcp)
    monkeypatch.setattr("quantbench.config_management.USER_SKILL_DOCS_DIR", user_skills)
    monkeypatch.setattr("quantbench.skills.mcp_adapter.USER_MCP_CONFIG", user_mcp)
    monkeypatch.setattr("quantbench.skills.mcp_adapter.PROJECT_MCP_CONFIG", project_mcp)
    monkeypatch.setattr("quantbench.skills.mcp_adapter.MCP_SERVERS_CONFIG", legacy_mcp)
    monkeypatch.setattr("quantbench.settings.USER_SETTINGS_FILE", user_settings)
    monkeypatch.setattr("quantbench.settings.PROJECT_SETTINGS_FILE", project_settings)
    monkeypatch.setattr("quantbench.settings.SETTINGS_FILES", [user_settings, project_settings])
    return {
        "user_mcp": user_mcp,
        "project_mcp": project_mcp,
        "user_skills": user_skills,
    }


def test_save_mcp_server_writes_claude_format_and_lists_enabled(scoped_config):
    from quantbench.config_management import list_mcp_server_records, save_mcp_server

    save_mcp_server("fs", {"command": "npx", "args": ["-y", "server-fs"]}, scope="user")

    stored = json.loads(scoped_config["user_mcp"].read_text(encoding="utf-8"))
    assert stored["mcpServers"]["fs"] == {"command": "npx", "args": ["-y", "server-fs"]}

    records = list_mcp_server_records()
    assert [r["name"] for r in records] == ["fs"]
    assert records[0]["enabled"] is True
    assert records[0]["scope"] == "user"


def test_save_mcp_server_rejects_allow_write(scoped_config):
    from quantbench.config_management import save_mcp_server

    with pytest.raises(ValueError, match="allowWrite"):
        save_mcp_server("w", {"command": "x", "quantbench": {"allowWrite": True}}, scope="user")


def test_import_and_remove_mcp_servers(scoped_config):
    from quantbench.config_management import import_mcp_servers, list_mcp_server_records, remove_mcp_server

    imported = import_mcp_servers(
        {"mcpServers": {"a": {"command": "a"}, "b": {"type": "http", "url": "https://x/mcp"}}},
        scope="project",
    )
    assert {s.name for s in imported} == {"a", "b"}
    assert {r["name"] for r in list_mcp_server_records()} == {"a", "b"}

    assert remove_mcp_server("a", scope="project") is True
    assert remove_mcp_server("a", scope="project") is False  # already gone
    assert {r["name"] for r in list_mcp_server_records()} == {"b"}


def test_toggle_disabled_server_hides_from_enabled_only_listing(scoped_config):
    from quantbench.config_management import (
        list_mcp_server_records,
        save_mcp_server,
        set_mcp_server_enabled,
    )

    save_mcp_server("fs", {"command": "npx"}, scope="user")
    set_mcp_server_enabled("fs", False, scope="user")

    # include_disabled default still lists it, but flags enabled=False...
    all_records = list_mcp_server_records()
    assert all_records[0]["enabled"] is False
    # ...and the enabled-only view drops it, proving the disable filter is applied.
    assert list_mcp_server_records(include_disabled=False) == []


def test_import_skill_from_text_and_remove(scoped_config):
    from quantbench.config_management import import_skill_from_text, remove_user_skill

    skill_md = (
        "---\n"
        "name: my-skill\n"
        "description: A test workflow skill.\n"
        "---\n\n"
        "Body of the skill.\n"
    )
    record = import_skill_from_text(skill_md)

    assert record["name"] == "my-skill"
    assert record["scope"] == "user"
    written = scoped_config["user_skills"] / "my-skill" / "SKILL.md"
    assert written.exists()

    assert remove_user_skill("my-skill") is True
    assert remove_user_skill("my-skill") is False
    assert not (scoped_config["user_skills"] / "my-skill").exists()


def test_probe_reports_not_found_for_unknown_server(scoped_config):
    from quantbench.config_management import probe_mcp_server

    assert probe_mcp_server("ghost") == {"status": "not-found", "tools": [], "error": "server not found"}


def test_probe_classifies_auth_challenge_as_needs_authorization(scoped_config, monkeypatch):
    from quantbench.config_management import probe_mcp_server, save_mcp_server

    save_mcp_server("remote", {"type": "http", "url": "https://mcp.example.com/mcp"}, scope="user")

    class _FakeManager:
        def __init__(self, servers, ctx, call_timeout_s=5.0):
            self._server = servers[0]

        def connect_or_error(self, server):
            return None, "HTTPStatusError: 401 Unauthorized"

        def close(self):
            pass

    monkeypatch.setattr("quantbench.config_management.MCPClientManager", _FakeManager)

    result = probe_mcp_server("remote")
    assert result["status"] == "needs-authorization"
    assert "authoriz" in result["error"].lower()


def test_probe_reports_generic_error_for_non_auth_failure(scoped_config, monkeypatch):
    from quantbench.config_management import probe_mcp_server, save_mcp_server

    save_mcp_server("remote", {"type": "http", "url": "https://mcp.example.com/mcp"}, scope="user")

    class _FakeManager:
        def __init__(self, servers, ctx, call_timeout_s=5.0):
            pass

        def connect_or_error(self, server):
            return None, "ConnectionError: name resolution failed"

        def close(self):
            pass

    monkeypatch.setattr("quantbench.config_management.MCPClientManager", _FakeManager)

    result = probe_mcp_server("remote")
    assert result["status"] == "error"
    assert "name resolution failed" in result["error"]
