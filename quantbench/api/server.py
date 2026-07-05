from __future__ import annotations

import json
from dataclasses import asdict
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse

from quantbench.api import run_reader
from quantbench.api.llm_key import active_model, llm_key_configured, provider_key_env, store_llm_config
from quantbench.api.run_manager import RunManager
from quantbench.api.security import allowed_origins, require_api_token
from quantbench.api.schemas import (
    ArtifactInfo,
    AskPaperRequest,
    AskPaperResponse,
    ConfigStatus,
    CostEstimateRequest,
    CostEstimateResponse,
    ExperimentRecordSchema,
    ForkRequest,
    IngestPaperRequest,
    LlmKeyRequest,
    NewSessionResponse,
    NewRunRequest,
    NewRunResponse,
    PaperDetail,
    PaperSummary,
    ReproducePaperRequest,
    RunDetail,
    RunSummary,
    SessionSchema,
    SessionTurnRequest,
    StagingConfirmRequest,
    StatusResponse,
)
from quantbench.api.session import SessionStore, build_session_context
from quantbench.costing import estimate_request_cost
from quantbench.library.aggregate import summarize
from quantbench.library.compare import compare_runs, compute_returns_correlation
from quantbench.library.index import ExperimentIndex, parse_csv_set
from quantbench.library.lineage import lineage
from quantbench.platform import assert_supported_platform

_manager = RunManager()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    assert_supported_platform()
    yield
    # Without this, Ctrl-C/reload leaves ThreadPoolExecutor worker threads
    # mid-LLM-call; the process can't exit until they finish (up to
    # MAX_STEPS), and the run stays stuck in "running" status forever since
    # neither manifest.json nor error.json ever gets written. Read _manager
    # via the module (not the closed-over variable) so tests that swap it
    # out on server_mod._manager still get the right instance cancelled.
    import quantbench.api.server as _self

    _self._manager.cancel_all()


app = FastAPI(title="QuantBench API", lifespan=_lifespan, dependencies=[Depends(require_api_token)])

# Local single-user tool; the frontend dev server runs on a different port.
# Origins and methods are restricted to configured localhost origins;
# the API token is checked separately on each protected route.
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-QuantBench-Token"],
)


def _session_store() -> SessionStore:
    return SessionStore(run_reader.RUNS_DIR)


@app.get("/api/config/status", response_model=ConfigStatus)
def get_config_status() -> ConfigStatus:
    model = active_model()
    return ConfigStatus(llm_key_configured=llm_key_configured(), model=model, key_env=provider_key_env(model))


@app.post("/api/config/llm-key", response_model=StatusResponse)
def post_llm_key(body: LlmKeyRequest) -> StatusResponse:
    try:
        store_llm_config(body.model, body.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StatusResponse(status="ok")


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


@app.post("/api/sessions", response_model=NewSessionResponse)
def create_session() -> NewSessionResponse:
    session = _session_store().create()
    return NewSessionResponse(session_id=session.session_id, created_at=session.created_at)


@app.get("/api/sessions/{session_id}", response_model=SessionSchema)
def get_session(session_id: str) -> SessionSchema:
    try:
        session = _session_store().get(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="session not found") from None
    return SessionSchema(**asdict(session))


@app.post("/api/sessions/{session_id}/turns", response_model=NewRunResponse)
def create_session_turn(session_id: str, payload: SessionTurnRequest) -> NewRunResponse:
    if not payload.user_message.strip():
        raise HTTPException(status_code=400, detail="user_message must not be empty")
    store = _session_store()
    try:
        session = store.get(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="session not found") from None
    session_context = build_session_context(session)
    turn_index = len(session.turns)
    run_id = _manager.submit_session_turn(session_id, payload.user_message, session_context, turn_index)
    store.append_turn(session_id, payload.user_message, run_id, {})
    return NewRunResponse(run_id=run_id, status="running")


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
                monitoring_status=(manifest.get("live_monitoring") or {}).get("status"),
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
        staging=run_reader.read_staging(run_id),
    )


@app.get("/api/runs/{run_id}/status", response_model=StatusResponse)
def get_run_status(run_id: str) -> StatusResponse:
    try:
        return StatusResponse(status=run_reader.get_status(run_id))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="run not found") from None


@app.post("/api/runs/{run_id}/staging/confirm", response_model=StatusResponse)
def confirm_staging(run_id: str, payload: StagingConfirmRequest) -> StatusResponse:
    try:
        status = run_reader.get_status(run_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="run not found") from None
    if status != "awaiting_confirmation":
        return StatusResponse(status=status)
    if not _manager.confirm_staging(run_id, payload.overrides):
        raise HTTPException(status_code=409, detail="run is not waiting for confirmation in this process")
    return StatusResponse(status="running")


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


@app.get("/api/runs/{run_id}/portfolio")
def get_portfolio_summary(run_id: str):
    """portfolio_summary.json for an optimize_portfolio run: method comparison
    table (in-sample vs out-of-sample Sharpe per method), weights, correlation
    matrix, diversification ratio. 404s for any run that isn't a portfolio run,
    same convention as /backtest-result."""
    summary = run_reader.read_portfolio_summary(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="portfolio summary not found")
    return summary


@app.get("/api/runs/{run_id}/monitoring")
def get_monitoring_report(run_id: str):
    """Full decay-check history for a run (see quantbench/monitor/). 404s if
    the run has never been checked, same convention as /portfolio."""
    history = run_reader.read_monitoring_report(run_id)
    if history is None:
        raise HTTPException(status_code=404, detail="no monitoring history for this run")
    return {"run_id": run_id, "history": history}


@app.post("/api/runs/{run_id}/monitoring/check")
def trigger_monitoring_check(run_id: str):
    """Runs a decay check synchronously and returns its result - lets the
    frontend offer a "check now" button without needing `quantbench monitor
    watch` running in the background."""
    from quantbench.monitor.pipeline import check_run_decay

    try:
        run_reader.get_status(run_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="run not found") from None
    return check_run_decay(run_id)


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
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="invalid filename")

    run_dir = run_reader.run_dir_for(run_id).resolve()
    path = (run_dir / filename).resolve()
    try:
        path.relative_to(run_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid filename") from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")

    if path.suffix == ".png":
        return FileResponse(path, media_type="image/png")
    if path.suffix == ".parquet":
        return FileResponse(path, media_type="application/octet-stream", filename=filename)

    return PlainTextResponse(path.read_text(encoding="utf-8", errors="replace"))


@app.get("/api/runs/{run_id}/artifacts/{filename}/preview")
def get_artifact_preview(run_id: str, filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
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


@app.post("/api/runs/estimate-cost", response_model=CostEstimateResponse)
def estimate_run_cost(payload: CostEstimateRequest) -> CostEstimateResponse:
    if not payload.request.strip():
        raise HTTPException(status_code=400, detail="request must not be empty")
    return CostEstimateResponse(**estimate_request_cost(payload.request))


def _mark_orphaned_run_cancelled(run_id: str) -> None:
    payload = {"run_id": run_id, "reason": "cancelled after API restart"}
    (run_reader.run_dir_for(run_id) / "cancelled.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@app.post("/api/runs/{run_id}/cancel", response_model=StatusResponse)
def cancel_run(run_id: str) -> StatusResponse:
    try:
        status = run_reader.get_status(run_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="run not found") from None
    if status != "running":
        return StatusResponse(status=status)
    if _manager.cancel(run_id):
        return StatusResponse(status="running")

    # The process restarted or the in-memory worker is gone. Filesystem status
    # alone would otherwise keep this historical run stuck as "running".
    status = run_reader.get_status(run_id)
    if status == "running":
        _mark_orphaned_run_cancelled(run_id)
        return StatusResponse(status="cancelled")
    return StatusResponse(status=status)


@app.post("/api/runs/{run_id}/fork", response_model=NewRunResponse)
def fork_run(run_id: str, payload: ForkRequest) -> NewRunResponse:
    if not payload.modification.strip():
        raise HTTPException(status_code=400, detail="modification must not be empty")
    try:
        forked_run_id = _manager.fork(run_id, payload.modification)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="run not found") from None
    return NewRunResponse(run_id=forked_run_id, status="running")


# --- Literature (GAP 4.3) -----------------------------------------------------


def _paper_store():
    from quantbench.literature.store import PaperStore

    return PaperStore()


@app.get("/api/literature", response_model=list[PaperSummary])
def list_papers() -> list[PaperSummary]:
    return [PaperSummary(**meta) for meta in _paper_store().list_papers()]


@app.post("/api/literature/ingest", response_model=PaperSummary)
def ingest_paper(payload: IngestPaperRequest) -> PaperSummary:
    if not payload.source.strip():
        raise HTTPException(status_code=400, detail="source must not be empty")
    from quantbench.literature.ingest import is_arxiv_reference, ingest_arxiv_with_bytes

    source = payload.source.strip()
    if not is_arxiv_reference(source):
        raise HTTPException(status_code=400, detail="Local PDFs must be imported with the upload endpoint.")
    try:
        paper, pdf_bytes = ingest_arxiv_with_bytes(source)
        _paper_store().save(paper, pdf_bytes=pdf_bytes)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return PaperSummary(**paper.metadata_dict())


@app.post("/api/literature/ingest/upload", response_model=PaperSummary)
async def upload_paper(file: UploadFile = File(...)) -> PaperSummary:
    from quantbench.literature.ingest import ingest_upload_with_bytes

    pdf_bytes = await file.read()
    try:
        paper, raw_pdf = ingest_upload_with_bytes(file.filename or "upload.pdf", pdf_bytes)
        _paper_store().save(paper, pdf_bytes=raw_pdf)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return PaperSummary(**paper.metadata_dict())


@app.get("/api/literature/{paper_id}", response_model=PaperDetail)
def get_paper(paper_id: str) -> PaperDetail:
    try:
        paper = _paper_store().load(paper_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="paper not found") from None
    return PaperDetail(
        **paper.metadata_dict(),
        pages=[{"page_number": p.page_number, "text": p.text} for p in paper.pages],
    )


@app.get("/api/literature/{paper_id}/pdf")
def get_paper_pdf(paper_id: str):
    path = _paper_store().pdf_path(paper_id)
    if path is None:
        raise HTTPException(status_code=404, detail="pdf not found for this paper")
    return FileResponse(path, media_type="application/pdf", filename=f"{paper_id}.pdf")


@app.post("/api/literature/{paper_id}/ask", response_model=AskPaperResponse)
def ask_paper(paper_id: str, payload: AskPaperRequest) -> AskPaperResponse:
    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")
    try:
        paper = _paper_store().load(paper_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="paper not found") from None

    from quantbench.agent.llm import LLMClient
    from quantbench.config import DEFAULT_MODEL
    from quantbench.literature.qa import answer_selection_question

    result = answer_selection_question(
        LLMClient(DEFAULT_MODEL),
        paper,
        selection=payload.selection or "",
        page=payload.page,
        question=payload.question,
    )
    return AskPaperResponse(answer=result["answer"], grounded_page=result["grounded_page"])


@app.post("/api/literature/{paper_id}/reproduce", response_model=NewRunResponse)
def reproduce_paper(paper_id: str, payload: ReproducePaperRequest) -> NewRunResponse:
    if not _paper_store().exists(paper_id):
        raise HTTPException(status_code=404, detail="paper not found")
    # A highlighted selection becomes the extraction 'focus'; an explicit request
    # (or the selection text) becomes the run's human-readable request.
    focus = payload.selection.strip() if payload.selection else None
    request = payload.request.strip() if payload.request else None
    run_id = _manager.submit_reproduce_paper(paper_id, request, focus)
    return NewRunResponse(run_id=run_id, status="running")
