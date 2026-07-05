from __future__ import annotations

import atexit
import asyncio
import hashlib
import json
import threading
import time
import warnings
from concurrent.futures import TimeoutError
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quantbench.config import MCP_SERVERS_CONFIG, PROJECT_MCP_CONFIG, USER_MCP_CONFIG
from quantbench.settings import is_server_enabled, load_settings
from quantbench.skills.registry import Skill


@dataclass(frozen=True)
class StdioTransportConfig:
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    type: str = "stdio"
    url: str = ""


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    transport: StdioTransportConfig
    enabled_tools: list[str] = field(default_factory=list)
    allow_write: bool = False
    scope: str = "unknown"
    source: str = ""


@dataclass
class _ServerConnection:
    session: Any
    tools: list[Any]
    stack: AsyncExitStack


# Substrings that mark a remote MCP connection failure as "not authenticated" rather than
# a generic transport/config error. Remote (sse/http) servers commonly answer an unauthenticated
# connect with HTTP 401/403 or a WWW-Authenticate/OAuth challenge; we surface those as a distinct
# `needs-authorization` state so the UI/CLI can tell the user to authorize instead of showing a
# generic "connection failed". QuantBench does not yet drive the OAuth authorization-code flow.
AUTHORIZATION_ERROR_TOKENS = (
    "401",
    "403",
    "unauthorized",
    "forbidden",
    "www-authenticate",
    "authorization required",
    "authorization_required",
    "invalid_token",
    "oauth",
)


def authorization_required_hint(error: BaseException | str) -> str | None:
    """Return a human-readable hint when a connection error looks like a missing-auth challenge.

    Returns None for errors that are not recognizably authorization failures, so callers can fall
    back to reporting the raw error.
    """

    text = str(error).lower()
    if not any(token in text for token in AUTHORIZATION_ERROR_TOKENS):
        return None
    return (
        "This remote MCP server requires authorization. Provide credentials (for example an auth "
        "token via env/headers) or complete the server's OAuth flow. QuantBench does not yet run "
        "the OAuth authorization-code flow automatically."
    )


SIDE_EFFECT_TOKENS = (
    "create",
    "delete",
    "write",
    "order",
    "send",
    "execute",
    "update",
    "insert",
    "remove",
    "patch",
    "post",
    "put",
    "trade",
    "buy",
    "sell",
)


def load_mcp_config(path: str | Path, *, scope: str = "unknown") -> list[MCPServerConfig]:
    config_path = Path(path)
    if not config_path.exists():
        return []
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.warn(f"Skipping MCP config {config_path}: {type(exc).__name__}: {exc}", stacklevel=2)
        return []

    parsed: list[MCPServerConfig] = []
    seen: set[str] = set()
    for index, raw in enumerate(_server_entries(payload)):
        try:
            server = _parse_server_config(raw)
        except ValueError as exc:
            label = raw.get("name", f"#{index}") if isinstance(raw, dict) else f"#{index}"
            warnings.warn(f"Skipping MCP server {label}: {exc}", stacklevel=2)
            continue
        if server.name in seen:
            warnings.warn(f"Skipping MCP server {server.name}: duplicate name.", stacklevel=2)
            continue
        seen.add(server.name)
        parsed.append(
            MCPServerConfig(
                name=server.name,
                transport=server.transport,
                enabled_tools=server.enabled_tools,
                allow_write=server.allow_write,
                scope=scope,
                source=str(config_path),
            )
        )
    return parsed


def load_merged_mcp_config(
    paths: list[tuple[str, Path]] | None = None,
    *,
    include_disabled: bool = False,
    settings: dict[str, Any] | None = None,
) -> list[MCPServerConfig]:
    config_paths = paths or [
        ("legacy", MCP_SERVERS_CONFIG),
        ("user", USER_MCP_CONFIG),
        ("project", PROJECT_MCP_CONFIG),
    ]
    merged: dict[str, MCPServerConfig] = {}
    for scope, path in config_paths:
        for server in load_mcp_config(path, scope=scope):
            merged[server.name] = server
    effective_settings = settings if settings is not None else load_settings()
    servers = list(merged.values())
    if not include_disabled:
        servers = [server for server in servers if is_server_enabled(server.name, effective_settings)]
    return servers


def mcp_server_to_config_dict(server: MCPServerConfig, *, include_name: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if include_name:
        payload["name"] = server.name
    if server.transport.type == "stdio":
        payload.update(
            {
                "command": server.transport.command,
                "args": list(server.transport.args),
            }
        )
        if server.transport.env:
            payload["env"] = dict(server.transport.env)
    else:
        payload["type"] = server.transport.type
        payload["url"] = server.transport.url
    quantbench: dict[str, Any] = {}
    if server.enabled_tools:
        quantbench["enabledTools"] = list(server.enabled_tools)
    if server.allow_write:
        quantbench["allowWrite"] = True
    if quantbench:
        payload["quantbench"] = quantbench
    return payload


def parse_mcp_server_config(name: str, payload: dict[str, Any]) -> MCPServerConfig:
    return _parse_server_config({"name": name, **payload})


def is_readonly_tool(tool: Any) -> bool:
    name = str(getattr(tool, "name", "") or "").lower()
    description = str(getattr(tool, "description", "") or "").lower()
    haystack = f"{name} {description}"
    return not any(token in haystack for token in SIDE_EFFECT_TOKENS)


class MCPClientManager:
    def __init__(
        self,
        servers: list[MCPServerConfig],
        ctx: Any,
        *,
        call_timeout_s: float = 30.0,
    ) -> None:
        self.servers = servers
        self.ctx = ctx
        self.call_timeout_s = call_timeout_s
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._closed = False
        self._connections: dict[str, _ServerConnection] = {}
        self._thread = threading.Thread(target=self._run_loop, name="quantbench-mcp-client", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)
        atexit.register(self.close)

    @classmethod
    def from_config_path(cls, path: str | Path, ctx: Any, *, call_timeout_s: float = 30.0) -> "MCPClientManager":
        return cls(load_mcp_config(path), ctx, call_timeout_s=call_timeout_s)

    def build_skills(self) -> list[Skill]:
        skills: list[Skill] = []
        for server in self.servers:
            if server.allow_write:
                warnings.warn(
                    f"Skipping MCP server {server.name}: allow_write=true is not supported in this phase.",
                    stacklevel=2,
                )
                continue
            connection = self._connect(server)
            if connection is None:
                continue
            enabled = set(server.enabled_tools)
            for tool in connection.tools:
                tool_name = str(getattr(tool, "name", ""))
                if enabled and tool_name not in enabled:
                    continue
                if not is_readonly_tool(tool):
                    warnings.warn(
                        f"Skipping MCP tool {server.name}/{tool_name}: name or description indicates side effects.",
                        stacklevel=2,
                    )
                    continue
                skills.append(self._skill_for_tool(server, tool))
        return skills

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            future = asyncio.run_coroutine_threadsafe(self._close_async(), self._loop)
            future.result(timeout=5.0)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5.0)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()
        self._loop.close()

    def _connect(self, server: MCPServerConfig) -> _ServerConnection | None:
        connection, error = self.connect_or_error(server)
        if error is not None:
            warnings.warn(f"Skipping MCP server {server.name}: {error}", stacklevel=2)
            return None
        return connection

    def connect_or_error(self, server: MCPServerConfig) -> tuple[_ServerConnection | None, str | None]:
        """Connect once and return either the connection or a structured error string.

        Unlike `_connect`, this does not swallow the failure into a warning, so one-shot diagnostics
        (the config `test` endpoint / CLI) can classify the error (e.g. `needs-authorization`).
        """

        if server.name in self._connections:
            return self._connections[server.name], None
        try:
            future = asyncio.run_coroutine_threadsafe(self._connect_async(server), self._loop)
            connection = future.result(timeout=self.call_timeout_s)
        except Exception as exc:  # noqa: BLE001 - external server errors become diagnostics
            return None, f"{type(exc).__name__}: {exc}"
        self._connections[server.name] = connection
        return connection, None

    async def _connect_async(self, server: MCPServerConfig) -> _ServerConnection:
        from mcp import ClientSession, StdioServerParameters

        stack = AsyncExitStack()
        if server.transport.type == "stdio":
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(
                command=server.transport.command,
                args=server.transport.args,
                env=server.transport.env or None,
            )
            read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
        elif server.transport.type == "sse":
            from mcp.client.sse import sse_client

            read_stream, write_stream = await stack.enter_async_context(sse_client(server.transport.url))
        elif server.transport.type == "http":
            from mcp.client.streamable_http import streamablehttp_client

            read_stream, write_stream, _get_session_id = await stack.enter_async_context(
                streamablehttp_client(server.transport.url)
            )
        else:
            raise ValueError(f"{server.transport.type} transport is not supported")
        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()
        result = await session.list_tools()
        return _ServerConnection(session=session, tools=list(getattr(result, "tools", []) or []), stack=stack)

    def _skill_for_tool(self, server: MCPServerConfig, tool: Any) -> Skill:
        tool_name = str(getattr(tool, "name", ""))
        description = str(getattr(tool, "description", "") or "")
        parameters = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {"type": "object"}

        def _call_tool(**kwargs: Any) -> Any:
            started = time.perf_counter()
            error: str | None = None
            normalized: Any
            try:
                normalized = self.call_tool(server.name, tool_name, kwargs)
                if isinstance(normalized, dict) and "error" in normalized:
                    error = str(normalized["error"])
                return normalized
            except Exception as exc:  # noqa: BLE001 - external tool errors stay structured
                error = f"{type(exc).__name__}: {exc}"
                normalized = {"error": error}
                return normalized
            finally:
                duration = round(time.perf_counter() - started, 3)
                self._record_call(server.name, tool_name, kwargs, normalized, duration, error)

        return Skill(
            name=f"mcp_{server.name}_{tool_name}",
            description=f"[external:{server.name}] {description}".strip(),
            parameters=parameters,
            fn=_call_tool,
        )

    def call_tool(self, server_name: str, tool_name: str, args: dict[str, Any]) -> Any:
        if server_name not in self._connections:
            raise RuntimeError(f"MCP server is not connected: {server_name}")
        session = self._connections[server_name].session
        future = asyncio.run_coroutine_threadsafe(session.call_tool(tool_name, args), self._loop)
        try:
            result = future.result(timeout=self.call_timeout_s)
        except TimeoutError as exc:
            future.cancel()
            raise TimeoutError(f"MCP tool {server_name}/{tool_name} timed out after {self.call_timeout_s:.1f}s") from exc
        return _normalize_call_result(result)

    def _record_call(
        self,
        server: str,
        tool: str,
        args: dict[str, Any],
        result: Any,
        duration_s: float,
        error: str | None,
    ) -> None:
        payload = json.dumps(_jsonable(result), ensure_ascii=False, sort_keys=True)
        record = {
            "server": server,
            "tool": tool,
            "args": _jsonable(args),
            "result_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            "duration_s": duration_s,
        }
        if error:
            record["error"] = error
        self.ctx.mcp_calls.append(record)

    async def _close_async(self) -> None:
        for connection in list(self._connections.values()):
            await connection.stack.aclose()
        self._connections.clear()


def _server_entries(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    if "mcpServers" in payload:
        servers = payload.get("mcpServers")
        if not isinstance(servers, dict):
            warnings.warn("Skipping MCP config: `mcpServers` must be an object.", stacklevel=2)
            return []
        entries: list[dict[str, Any]] = []
        for name, config in servers.items():
            if isinstance(config, dict):
                entries.append({"name": name, **config})
            else:
                entries.append({"name": name, "_invalid": config})
        return entries
    servers = payload.get("servers", [])
    if not isinstance(servers, list):
        warnings.warn("Skipping MCP config: `servers` must be a list.", stacklevel=2)
        return []
    return list(servers)


def _parse_server_config(raw: Any) -> MCPServerConfig:
    if not isinstance(raw, dict):
        raise ValueError("server entry must be an object")
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("missing non-empty name")
    transport = raw.get("transport") if isinstance(raw.get("transport"), dict) else raw
    transport_type = transport.get("type", "stdio")
    if transport_type not in {"stdio", "sse", "http"}:
        raise ValueError("type must be stdio, sse, or http")
    command = transport.get("command", "")
    url = transport.get("url", "")
    if transport_type == "stdio" and (not isinstance(command, str) or not command):
        raise ValueError("transport.command must be non-empty")
    if transport_type in {"sse", "http"} and (not isinstance(url, str) or not url):
        raise ValueError("transport.url must be non-empty")
    args = transport.get("args", [])
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise ValueError("transport.args must be a list of strings")
    env = transport.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in env.items()):
        raise ValueError("transport.env must be an object of strings")
    quantbench = raw.get("quantbench", {})
    if quantbench is None:
        quantbench = {}
    if not isinstance(quantbench, dict):
        raise ValueError("quantbench must be an object")
    enabled_tools = raw.get("enabled_tools", quantbench.get("enabledTools", []))
    if not isinstance(enabled_tools, list) or not all(isinstance(item, str) for item in enabled_tools):
        raise ValueError("enabled_tools must be a list of strings")
    allow_write = raw.get("allow_write", quantbench.get("allowWrite", False))
    if not isinstance(allow_write, bool):
        raise ValueError("allow_write must be a boolean")
    return MCPServerConfig(
        name=name,
        transport=StdioTransportConfig(
            command=command,
            args=list(args),
            env=dict(env),
            type=str(transport_type),
            url=url if isinstance(url, str) else "",
        ),
        enabled_tools=list(enabled_tools),
        allow_write=allow_write,
    )


def _normalize_call_result(result: Any) -> Any:
    if bool(getattr(result, "isError", False)):
        return {"error": _content_to_text(getattr(result, "content", []) or [])}
    structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    if structured is not None:
        return _jsonable(structured)
    content = list(getattr(result, "content", []) or [])
    if not content:
        return None
    if not all(str(getattr(block, "type", "")) == "text" and hasattr(block, "text") for block in content):
        return {"error": "unsupported MCP result content type"}
    text = "\n".join(str(block.text) for block in content)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _content_to_text(content: list[Any]) -> str:
    parts = []
    for block in content:
        if hasattr(block, "text"):
            parts.append(str(block.text))
        else:
            parts.append(str(block))
    return "\n".join(parts)


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(key): _jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_jsonable(item) for item in value]
        return str(value)
