from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import Header, HTTPException, Request

from quantbench.config import QUANTBENCH_HOME


TOKEN_ENV = "QUANTBENCH_API_TOKEN"
ORIGINS_ENV = "QUANTBENCH_ALLOWED_ORIGINS"
DEFAULT_ALLOWED_ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")
TOKEN_FILE = QUANTBENCH_HOME / "api_token"


def allowed_origins() -> list[str]:
    raw = os.environ.get(ORIGINS_ENV)
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return list(DEFAULT_ALLOWED_ORIGINS)


def get_or_create_api_token(token_file: Path = TOKEN_FILE) -> str:
    env_token = os.environ.get(TOKEN_ENV)
    if env_token:
        return env_token
    token_file.parent.mkdir(parents=True, exist_ok=True)
    if token_file.exists():
        token = token_file.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    token_file.write_text(token + "\n", encoding="utf-8")
    try:
        token_file.chmod(0o600)
    except OSError:
        pass
    return token


def configured_token() -> str:
    token = os.environ.get(TOKEN_ENV)
    if token:
        return token
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token
    raise HTTPException(status_code=500, detail=f"{TOKEN_ENV} is required before starting the API")


def require_api_token(
    request: Request,
    x_quantbench_token: str | None = Header(default=None),
) -> None:
    expected = configured_token()
    supplied = x_quantbench_token or request.query_params.get("token")
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="missing or invalid QuantBench API token")
