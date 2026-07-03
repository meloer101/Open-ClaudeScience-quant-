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


class NewRunRequest(BaseModel):
    request: str


class NewRunResponse(BaseModel):
    run_id: str
    status: str


class StatusResponse(BaseModel):
    status: str


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


class ForkRequest(BaseModel):
    modification: str
