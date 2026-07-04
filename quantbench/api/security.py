from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import Header, HTTPException, Request

from quantbench.config import QUANTBENCH_HOME


TOKEN_ENV = "QUANTBENCH_API_TOKEN"
TOKEN_FILE = QUANTBENCH_HOME / "api_token"


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


def configured_api_token() -> str | None:
    token = os.environ.get(TOKEN_ENV)
    if token:
        return token
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text(encoding="utf-8").strip() or None
    return None


def require_local_api_token(
    request: Request,
    x_quantbench_token: str | None = Header(default=None),
) -> None:
    expected = configured_api_token()
    if not expected:
        return
    supplied = x_quantbench_token or request.query_params.get("token")
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid QuantBench API token")
