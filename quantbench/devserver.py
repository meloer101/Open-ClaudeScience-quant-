from __future__ import annotations

import os
import secrets
import shutil
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


# Tools `serve` shells out to, with a one-line install hint shown when one is missing. Keeping the
# hint next to the check means a first-time user gets an actionable message instead of a cryptic
# "command not found" from a crashed child process.
REQUIRED_TOOLS: dict[str, str] = {
    "uv": "https://docs.astral.sh/uv/getting-started/installation/",
    "node": "https://nodejs.org (Node.js 22+)",
    "npm": "ships with Node.js — https://nodejs.org",
}


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


def missing_tools(tools: dict[str, str] | None = None) -> list[str]:
    """Return the names of required tools that are not on PATH."""
    return [name for name in (tools or REQUIRED_TOOLS) if shutil.which(name) is None]


def web_deps_installed(web_dir: Path) -> bool:
    return (web_dir / "node_modules").is_dir()


def install_web_deps(web_dir: Path, *, env: dict[str, str] | None = None) -> int:
    """Run `npm install` in web_dir (the first-run dependency install). Returns its exit code."""
    print("Installing web dependencies (first run only, this can take a minute)...")
    completed = subprocess.run(["npm", "install"], cwd=web_dir, env=env)
    return completed.returncode


def run_devserver(plan: DevServerPlan, *, cwd: Path) -> int:
    env = {**os.environ, **plan.env}
    web_dir = cwd / "web"

    absent = missing_tools()
    if absent:
        print("Cannot start QuantBench — the following tools are required but not found on PATH:")
        for name in absent:
            print(f"  - {name}: install from {REQUIRED_TOOLS[name]}")
        return 1

    if not web_deps_installed(web_dir):
        code = install_web_deps(web_dir, env=env)
        if code != 0 or not web_deps_installed(web_dir):
            print("Web dependency install failed. Run `cd web && npm install` manually to see the error.")
            return code or 1

    api = subprocess.Popen(plan.api_cmd, cwd=cwd, env=env)
    web = subprocess.Popen(plan.web_cmd, cwd=web_dir, env=env)
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
