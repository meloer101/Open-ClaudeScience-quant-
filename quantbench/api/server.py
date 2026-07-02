from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse

from quantbench.api import run_reader
from quantbench.api.run_manager import RunManager
from quantbench.api.schemas import (
    ArtifactInfo,
    ExperimentRecordSchema,
    ForkRequest,
    NewRunRequest,
    NewRunResponse,
    RunDetail,
    RunSummary,
    StatusResponse,
)
from quantbench.library.aggregate import summarize
from quantbench.library.compare import compare_runs, compute_returns_correlation
from quantbench.library.index import ExperimentIndex, parse_csv_set
from quantbench.library.lineage import lineage

app = FastAPI(title="QuantBench API")

# Local single-user tool; the frontend dev server runs on a different port.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_manager = RunManager()


@app.get("/api/library", response_model=list[ExperimentRecordSchema])
def get_library(
    verdict: str | None = None,
    asset: str | None = None,
    factor_family: str | None = None,
    min_sharpe: float | None = None,
    sort: str = "created_at",
) -> list[ExperimentRecordSchema]:
    index = (
        ExperimentIndex.build()
        .filter(
            verdicts=parse_csv_set(verdict),
            asset_class=asset,
            factor_family=factor_family,
            min_sharpe=min_sharpe,
        )
        .sort(sort)
    )
    return [ExperimentRecordSchema(**record.to_dict()) for record in index.records]


@app.get("/api/library/summary")
def get_library_summary():
    return summarize(ExperimentIndex.build())


@app.get("/api/compare")
def get_compare(run_ids: str):
    ids = [run_id.strip() for run_id in run_ids.split(",") if run_id.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="run_ids must not be empty")
    table = compare_runs(ids)
    # A correlation matrix needs at least 2 runs to say anything; compute_runs_correlation()
    # already returns a diagonal-only shape for fewer, so gate it here to avoid a misleading
    # 1x1 "matrix" reaching the frontend.
    table["returns_correlation"] = compute_returns_correlation(ids) if len(ids) >= 2 else {}
    return table


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


@app.get("/api/runs/{run_id}/lineage")
def get_lineage(run_id: str):
    try:
        return lineage(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="run not found") from None


@app.get("/api/runs/{run_id}/backtest-result")
def get_backtest_result(run_id: str):
    """The ChartsPanel's one entry point for a run's backtest result JSON.
    Deliberately not a direct artifact-by-filename fetch: single-symbol runs
    write "backtest_result.json" but historical cross-sectional runs wrote
    "cross_sectional_backtest_result.json" before the two were unified onto
    one name - run_reader.read_backtest_result() resolves either, so the
    frontend never has to know or guess which filename a given run used."""
    result = run_reader.read_backtest_result(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="backtest result not found")
    return result


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


@app.get("/api/runs/{run_id}/artifacts/{filename}/preview")
def get_artifact_preview(run_id: str, filename: str):
    if ".." in filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    if not filename.endswith(".parquet"):
        raise HTTPException(status_code=400, detail="preview is only supported for .parquet artifacts")

    preview = run_reader.preview_parquet(run_id, filename)
    if preview is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    return preview


@app.post("/api/runs", response_model=NewRunResponse)
def create_run(payload: NewRunRequest) -> NewRunResponse:
    if not payload.request.strip():
        raise HTTPException(status_code=400, detail="request must not be empty")
    run_id = _manager.submit(payload.request)
    return NewRunResponse(run_id=run_id, status="running")


@app.post("/api/runs/{run_id}/fork", response_model=NewRunResponse)
def fork_run(run_id: str, payload: ForkRequest) -> NewRunResponse:
    if not payload.modification.strip():
        raise HTTPException(status_code=400, detail="modification must not be empty")
    try:
        forked_run_id = _manager.fork(run_id, payload.modification)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="run not found") from None
    return NewRunResponse(run_id=forked_run_id, status="running")
