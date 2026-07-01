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
