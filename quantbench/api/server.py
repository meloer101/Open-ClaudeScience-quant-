from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse

from quantbench.api import run_reader
from quantbench.api.run_manager import RunManager
from quantbench.api.schemas import (
    ArtifactInfo,
    NewRunRequest,
    NewRunResponse,
    RunDetail,
    RunSummary,
    StatusResponse,
)

app = FastAPI(title="QuantBench API")

# Local single-user tool; the frontend dev server runs on a different port.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_manager = RunManager()


@app.get("/api/runs", response_model=list[RunSummary])
def list_runs() -> list[RunSummary]:
    summaries = []
    for run_id in run_reader.list_run_ids():
        manifest = run_reader.read_manifest(run_id) or {}
        created_at = manifest.get("created_at") or run_reader.created_at_from_run_id(run_id)
        user_request = manifest.get("user_request") or run_reader.read_user_request(run_id)
        summaries.append(
            RunSummary(
                run_id=run_id,
                user_request=user_request,
                created_at=created_at,
                status=run_reader.get_status(run_id),
                warnings_count=len(manifest.get("warnings", [])),
                sharpe=(manifest.get("metrics") or {}).get("sharpe"),
            )
        )
    return summaries


@app.get("/api/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: str) -> RunDetail:
    try:
        status = run_reader.get_status(run_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="run not found") from None

    manifest = run_reader.read_manifest(run_id) or {}
    created_at = manifest.get("created_at") or run_reader.created_at_from_run_id(run_id)
    user_request = manifest.get("user_request") or run_reader.read_user_request(run_id)
    return RunDetail(
        run_id=run_id,
        user_request=user_request,
        created_at=created_at,
        status=status,
        summary=manifest.get("summary", ""),
        metrics=manifest.get("metrics", {}),
        warnings=manifest.get("warnings", []),
        artifacts=[ArtifactInfo(**item) for item in run_reader.list_artifacts(run_id)],
        error=run_reader.read_error(run_id) if status == "failed" else None,
    )


@app.get("/api/runs/{run_id}/status", response_model=StatusResponse)
def get_run_status(run_id: str) -> StatusResponse:
    try:
        return StatusResponse(status=run_reader.get_status(run_id))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="run not found") from None


@app.get("/api/runs/{run_id}/events")
def stream_run_events(run_id: str):
    """Server-Sent Events stream of live tool-call progress for a run still
    executing in this process. If the run isn't being live-tracked (already
    finished, or the API restarted since it was submitted), the stream just
    ends immediately - the frontend falls back to polling /status either way."""

    def event_source():
        for event in _manager.stream_events(run_id):
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


@app.get("/api/runs/{run_id}/artifacts/{filename}")
def get_artifact(run_id: str, filename: str):
    if ".." in filename:
        raise HTTPException(status_code=400, detail="invalid filename")

    path = run_reader.run_dir_for(run_id) / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")

    if path.suffix == ".png":
        return FileResponse(path, media_type="image/png")
    if path.suffix == ".parquet":
        return FileResponse(path, media_type="application/octet-stream", filename=filename)

    return PlainTextResponse(path.read_text(encoding="utf-8", errors="replace"))


@app.post("/api/runs", response_model=NewRunResponse)
def create_run(payload: NewRunRequest) -> NewRunResponse:
    if not payload.request.strip():
        raise HTTPException(status_code=400, detail="request must not be empty")
    run_id = _manager.submit(payload.request)
    return NewRunResponse(run_id=run_id, status="running")
