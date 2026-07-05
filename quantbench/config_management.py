from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from quantbench.config import PROJECT_MCP_CONFIG, USER_MCP_CONFIG, USER_SKILL_DOCS_DIR
from quantbench.settings import is_server_enabled, is_skill_enabled, set_server_enabled, set_skill_enabled
from quantbench.skilldocs.doc import parse_skill_md
from quantbench.skilldocs.registry import SkillRegistryDocs
from quantbench.skills.mcp_adapter import (
    MCPClientManager,
    MCPServerConfig,
    authorization_required_hint,
    load_merged_mcp_config,
    mcp_server_to_config_dict,
    parse_mcp_server_config,
)


def list_mcp_server_records(*, include_disabled: bool = True) -> list[dict[str, Any]]:
    servers = load_merged_mcp_config(include_disabled=include_disabled)
    return [_server_record(server) for server in servers]


def save_mcp_server(name: str, config: dict[str, Any], *, scope: str = "user") -> MCPServerConfig:
    server = parse_mcp_server_config(name, config)
    _reject_unsupported_write(server)
    path = _mcp_file_for_scope(scope)
    payload = _read_json_object(path)
    mcp_servers = payload.setdefault("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        raise ValueError("mcpServers must be an object")
    mcp_servers[name] = mcp_server_to_config_dict(server)
    _write_json(path, payload)
    return server


def import_mcp_servers(payload: dict[str, Any], *, scope: str = "user") -> list[MCPServerConfig]:
    servers = payload.get("mcpServers", payload)
    if not isinstance(servers, dict):
        raise ValueError("mcpServers must be an object")
    parsed: list[MCPServerConfig] = []
    for name, config in servers.items():
        if not isinstance(name, str) or not isinstance(config, dict):
            raise ValueError("each mcpServers entry must be an object keyed by name")
        server = parse_mcp_server_config(name, config)
        _reject_unsupported_write(server)
        parsed.append(server)

    path = _mcp_file_for_scope(scope)
    payload = _read_json_object(path)
    mcp_servers = payload.setdefault("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        raise ValueError("mcpServers must be an object")
    for server in parsed:
        mcp_servers[server.name] = mcp_server_to_config_dict(server)
    _write_json(path, payload)
    return parsed


def remove_mcp_server(name: str, *, scope: str = "user") -> bool:
    path = _mcp_file_for_scope(scope)
    payload = _read_json_object(path)
    mcp_servers = payload.get("mcpServers", {})
    if not isinstance(mcp_servers, dict) or name not in mcp_servers:
        return False
    del mcp_servers[name]
    payload["mcpServers"] = mcp_servers
    _write_json(path, payload)
    return True


def set_mcp_server_enabled(name: str, enabled: bool, *, scope: str = "user") -> None:
    set_server_enabled(name, enabled, scope=scope)


def probe_mcp_server(name: str, *, timeout_s: float = 5.0) -> dict[str, Any]:
    """Connect to a configured MCP server once and report its status.

    Shared by the `/api/config/mcp-servers/{name}/test` endpoint and the `quantbench mcp test` CLI so
    both surface the same states: `ok` (with discovered tools), `needs-authorization` (remote auth
    challenge), `error`, or `not-found`.
    """

    server = next((item for item in load_merged_mcp_config(include_disabled=True) if item.name == name), None)
    if server is None:
        return {"status": "not-found", "tools": [], "error": "server not found"}
    if server.allow_write:
        return {"status": "error", "tools": [], "error": "allowWrite=true is not supported yet"}

    from quantbench.agent.run_context import _RunContext

    manager = MCPClientManager([server], _RunContext(), call_timeout_s=timeout_s)
    try:
        connection, error = manager.connect_or_error(server)
        if error is not None:
            hint = authorization_required_hint(error)
            if hint is not None:
                return {"status": "needs-authorization", "tools": [], "error": hint}
            return {"status": "error", "tools": [], "error": error}
        tools = [str(getattr(tool, "name", "")) for tool in connection.tools]
        return {"status": "ok", "tools": tools, "error": None}
    finally:
        manager.close()


def list_skill_records(*, include_disabled: bool = True) -> list[dict[str, Any]]:
    registry = SkillRegistryDocs(include_disabled=include_disabled)
    records = []
    for doc in registry.load_all():
        records.append(
            {
                "name": doc.name,
                "description": doc.description,
                "triggers": doc.triggers,
                "path": doc.path,
                "scope": doc.scope,
                "enabled": is_skill_enabled(doc.name),
                "attachments": doc.attachments or [],
            }
        )
    return records


def set_skill_doc_enabled(name: str, enabled: bool, *, scope: str = "user") -> None:
    set_skill_enabled(name, enabled, scope=scope)


def import_skill_from_text(skill_md: str) -> dict[str, Any]:
    USER_SKILL_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    temp = USER_SKILL_DOCS_DIR / ".importing.SKILL.md"
    temp.write_text(skill_md, encoding="utf-8")
    try:
        doc = parse_skill_md(temp)
        skill_dir = USER_SKILL_DOCS_DIR / _safe_name(doc.name)
        skill_dir.mkdir(parents=True, exist_ok=True)
        target = skill_dir / "SKILL.md"
        target.write_text(skill_md, encoding="utf-8")
        return {
            "name": doc.name,
            "description": doc.description,
            "triggers": doc.triggers,
            "path": str(target),
            "scope": "user",
            "enabled": is_skill_enabled(doc.name),
            "attachments": [],
        }
    finally:
        temp.unlink(missing_ok=True)


def import_skill_from_path(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    if not source.exists():
        raise FileNotFoundError(str(source))
    if source.is_file():
        return import_skill_from_text(source.read_text(encoding="utf-8"))
    skill_md = source / "SKILL.md"
    if not skill_md.is_file():
        raise ValueError("skill directory must contain SKILL.md")
    doc = parse_skill_md(skill_md)
    target = USER_SKILL_DOCS_DIR / _safe_name(doc.name)
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    return {
        "name": doc.name,
        "description": doc.description,
        "triggers": doc.triggers,
        "path": str(target / "SKILL.md"),
        "scope": "user",
        "enabled": is_skill_enabled(doc.name),
        "attachments": [str(item.relative_to(target)) for item in target.rglob("*") if item.is_file() and item.name != "SKILL.md"],
    }


def remove_user_skill(name: str) -> bool:
    target = USER_SKILL_DOCS_DIR / _safe_name(name)
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True


def _server_record(server: MCPServerConfig) -> dict[str, Any]:
    transport = server.transport
    return {
        "name": server.name,
        "type": transport.type,
        "command": transport.command,
        "args": transport.args,
        "env": transport.env,
        "url": transport.url,
        "enabledTools": server.enabled_tools,
        "allowWrite": server.allow_write,
        "scope": server.scope,
        "source": server.source,
        "enabled": is_server_enabled(server.name),
        "status": "writes-not-supported" if server.allow_write else "configured",
        "tools": [],
    }


def _reject_unsupported_write(server: MCPServerConfig) -> None:
    if server.allow_write:
        raise ValueError("allowWrite=true is not supported yet; write-capable MCP tools remain disabled")


def _mcp_file_for_scope(scope: str) -> Path:
    if scope == "user":
        return USER_MCP_CONFIG
    if scope == "project":
        return PROJECT_MCP_CONFIG
    raise ValueError("scope must be user or project")


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} root must be an object")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _safe_name(name: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in name).strip(".-")
    if not cleaned:
        raise ValueError("name is empty after sanitization")
    if cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        raise ValueError("invalid name")
    return cleaned
