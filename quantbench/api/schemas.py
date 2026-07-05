from pydantic import BaseModel


class ArtifactInfo(BaseModel):
    filename: str
    kind: str
    size_bytes: int


class RunSummary(BaseModel):
    run_id: str
    user_request: str
    created_at: str
    status: str
    warnings_count: int
    sharpe: float | None = None
    monitoring_status: str | None = None


class RunDetail(BaseModel):
    run_id: str
    user_request: str
    created_at: str
    status: str
    summary: str
    metrics: dict
    warnings: list[str]
    artifacts: list[ArtifactInfo]
    error: str | None = None
    staging: dict | None = None


class NewRunRequest(BaseModel):
    request: str


class CostEstimateRequest(BaseModel):
    request: str


class CostEstimateResponse(BaseModel):
    estimated_tokens: int
    estimated_usd: float
    coordinator_calls: int
    critic_calls: int
    note: str


class NewRunResponse(BaseModel):
    run_id: str
    status: str


class NewSessionResponse(BaseModel):
    session_id: str
    created_at: str


class SessionTurnRequest(BaseModel):
    user_message: str


class SessionTurnSchema(BaseModel):
    turn_index: int
    user_message: str
    run_id: str | None = None
    summary: dict = {}


class SessionSchema(BaseModel):
    session_id: str
    created_at: str
    turns: list[SessionTurnSchema]


class StatusResponse(BaseModel):
    status: str


class ConfigStatus(BaseModel):
    llm_key_configured: bool
    model: str
    key_env: str


class LlmKeyRequest(BaseModel):
    model: str
    api_key: str


class StagingConfirmRequest(BaseModel):
    overrides: dict = {}


class ExperimentRecordSchema(BaseModel):
    run_id: str
    hypothesis: str
    created_at: str
    status: str
    asset_class: str
    factor_family: str
    cross_sectional: bool
    sharpe: float | None = None
    annual_return: float | None = None
    max_drawdown: float | None = None
    turnover_annual: float | None = None
    ic_mean: float | None = None
    oos_sharpe: float | None = None
    verdict: str | None = None
    critic_verdict: str | None = None
    critic_agrees: bool | None = None
    critical_count: int
    warning_count: int
    parent_run_id: str | None = None
    error_summary: str | None = None
    literature_paper_id: str | None = None
    literature_title: str | None = None


class ForkRequest(BaseModel):
    modification: str


class PaperSummary(BaseModel):
    paper_id: str
    title: str
    authors: list[str] = []
    source: str
    source_kind: str
    arxiv_id: str | None = None
    n_pages: int


class PaperDetail(PaperSummary):
    pages: list[dict]


class IngestPaperRequest(BaseModel):
    source: str  # local PDF path or arXiv URL/id


class AskPaperRequest(BaseModel):
    selection: str
    question: str
    page: int | None = None


class AskPaperResponse(BaseModel):
    answer: str
    grounded_page: int | None = None


class ReproducePaperRequest(BaseModel):
    request: str | None = None
    selection: str | None = None
    page: int | None = None
