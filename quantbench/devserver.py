from __future__ import annotations

import os
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DevServerPlan:
    api_cmd: list[str]
    web_cmd: list[str]
    api_url: str
    web_url: str
    env: dict[str, str]


def build_devserver_plan(
    *,
    host: str = "127.0.0.1",
    api_port: int = 8000,
    web_port: int = 5173,
    token: str | None = None,
) -> DevServerPlan:
    token = token or secrets.token_urlsafe(32)
    api_url = f"http://{host}:{api_port}"
    web_url = f"http://{host}:{web_port}"
    env = {
        "QUANTBENCH_API_TOKEN": token,
        "VITE_QUANTBENCH_API_BASE": api_url + "/api",
        "VITE_QUANTBENCH_API_TOKEN": token,
    }
    return DevServerPlan(
        api_cmd=["uv", "run", "uvicorn", "quantbench.api.server:app", "--host", host, "--port", str(api_port), "--reload", "--reload-dir", "quantbench"],
        web_cmd=["npm", "run", "dev", "--", "--host", host, "--port", str(web_port)],
        api_url=api_url,
        web_url=web_url,
        env=env,
    )


def run_devserver(plan: DevServerPlan, *, cwd: Path) -> int:
    env = {**os.environ, **plan.env}
    api = subprocess.Popen(plan.api_cmd, cwd=cwd, env=env)
    web = subprocess.Popen(plan.web_cmd, cwd=cwd / "web", env=env)
    try:
        print(f"API: {plan.api_url}")
        print(f"Web: {plan.web_url}")
        print("Press Ctrl-C to stop.")
        return web.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        for proc in (web, api):
            proc.terminate()
        for proc in (web, api):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
