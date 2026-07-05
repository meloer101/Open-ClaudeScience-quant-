from __future__ import annotations

from fastapi import APIRouter, HTTPException

from quantbench.api.schemas import (
    EnabledRequest,
    McpServerRecord,
    McpServerTestResponse,
    McpServerUpsertRequest,
    McpServersImportRequest,
    SkillImportRequest,
    SkillRecord,
    StatusResponse,
)
from quantbench.config_management import (
    import_mcp_servers,
    import_skill_from_text,
    list_mcp_server_records,
    list_skill_records,
    probe_mcp_server,
    remove_mcp_server,
    remove_user_skill,
    save_mcp_server,
    set_mcp_server_enabled,
    set_skill_doc_enabled,
)

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/mcp-servers", response_model=list[McpServerRecord])
def list_mcp_servers() -> list[McpServerRecord]:
    return [McpServerRecord(**record) for record in list_mcp_server_records()]


@router.post("/mcp-servers", response_model=McpServerRecord)
def post_mcp_server(body: McpServerUpsertRequest) -> McpServerRecord:
    try:
        config = _mcp_body_to_config(body)
        save_mcp_server(body.name, config, scope=body.scope)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record = next(item for item in list_mcp_server_records() if item["name"] == body.name)
    return McpServerRecord(**record)


@router.post("/mcp-servers/import", response_model=list[McpServerRecord])
def post_mcp_servers_import(body: McpServersImportRequest) -> list[McpServerRecord]:
    try:
        imported = import_mcp_servers(body.payload, scope=body.scope)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    names = {server.name for server in imported}
    return [McpServerRecord(**record) for record in list_mcp_server_records() if record["name"] in names]


@router.delete("/mcp-servers/{name}", response_model=StatusResponse)
def delete_mcp_server(name: str, scope: str = "user") -> StatusResponse:
    try:
        removed = remove_mcp_server(name, scope=scope)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="server not found")
    return StatusResponse(status="ok")


@router.patch("/mcp-servers/{name}", response_model=StatusResponse)
def patch_mcp_server(name: str, body: EnabledRequest) -> StatusResponse:
    try:
        set_mcp_server_enabled(name, body.enabled, scope=body.scope)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StatusResponse(status="ok")


@router.post("/mcp-servers/{name}/test", response_model=McpServerTestResponse)
def test_mcp_server(name: str) -> McpServerTestResponse:
    result = probe_mcp_server(name)
    if result["status"] == "not-found":
        raise HTTPException(status_code=404, detail="server not found")
    return McpServerTestResponse(status=result["status"], tools=result["tools"], error=result["error"])


@router.get("/skills", response_model=list[SkillRecord])
def list_skills() -> list[SkillRecord]:
    return [SkillRecord(**record) for record in list_skill_records()]


@router.patch("/skills/{name}", response_model=StatusResponse)
def patch_skill(name: str, body: EnabledRequest) -> StatusResponse:
    try:
        set_skill_doc_enabled(name, body.enabled, scope=body.scope)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StatusResponse(status="ok")


@router.post("/skills/import", response_model=SkillRecord)
def post_skill_import(body: SkillImportRequest) -> SkillRecord:
    try:
        return SkillRecord(**import_skill_from_text(body.skill_md))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/skills/{name}", response_model=StatusResponse)
def delete_skill(name: str) -> StatusResponse:
    if not remove_user_skill(name):
        raise HTTPException(status_code=404, detail="user skill not found")
    return StatusResponse(status="ok")


def _mcp_body_to_config(body: McpServerUpsertRequest) -> dict:
    if body.type == "stdio":
        return {
            "command": body.command or "",
            "args": body.args,
            "env": body.env,
            "quantbench": {"enabledTools": body.enabledTools, "allowWrite": body.allowWrite},
        }
    return {
        "type": body.type,
        "url": body.url or "",
        "quantbench": {"enabledTools": body.enabledTools, "allowWrite": body.allowWrite},
    }
