import importlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("QUANTBENCH_API_TOKEN", raising=False)
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path)
    from quantbench.api.server import app

    return TestClient(app)


def test_runtime_dirs_default_to_quantbench_home(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTBENCH_HOME", str(tmp_path / "qb-home"))
    import quantbench.config as config

    reloaded = importlib.reload(config)

    assert reloaded.DATA_CACHE_DIR == tmp_path / "qb-home" / "data_cache"
    assert reloaded.RUNS_DIR == tmp_path / "qb-home" / "runs"
    assert reloaded.FACTORS_DIR == tmp_path / "qb-home" / "factors"
    assert reloaded.LITERATURE_DIR == tmp_path / "qb-home" / "literature"
    assert reloaded.PROJECT_ROOT not in reloaded.RUNS_DIR.parents


def test_dotenv_can_load_from_quantbench_home(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTBENCH_HOME", str(tmp_path))
    monkeypatch.delenv("QUANTBENCH_CRITIC_MODEL", raising=False)
    (tmp_path / ".env").write_text("QUANTBENCH_CRITIC_MODEL=deepseek/test\n", encoding="utf-8")
    import quantbench.config as config

    reloaded = importlib.reload(config)

    assert os.environ["QUANTBENCH_CRITIC_MODEL"] == "deepseek/test"
    assert reloaded.CRITIC_MODEL == "deepseek/test"


def test_platform_guard_rejects_unsupported_system():
    from quantbench.platform import unsupported_platform_message

    message = unsupported_platform_message("Windows")

    assert message is not None
    assert "macOS and Linux" in message


def test_api_token_required_when_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTBENCH_API_TOKEN", "secret-token")
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path)
    from quantbench.api.server import app

    client = TestClient(app)

    assert client.get("/api/runs").status_code == 401
    assert client.get("/api/runs", headers={"X-QuantBench-Token": "secret-token"}).status_code == 200


def test_generated_api_token_is_persisted(tmp_path):
    from quantbench.api.security import get_or_create_api_token

    token_file = tmp_path / "api_token"
    first = get_or_create_api_token(token_file)
    second = get_or_create_api_token(token_file)

    assert first == second
    assert len(first) >= 32


def test_artifact_rejects_nested_path_segments(tmp_path, client):
    run_id = "run_20260701_000000_aaaa"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text("{}", encoding="utf-8")
    nested = run_dir / "nested"
    nested.mkdir()
    (nested / "secret.md").write_text("nope", encoding="utf-8")

    response = client.get(f"/api/runs/{run_id}/artifacts/nested%2Fsecret.md")

    assert response.status_code in (400, 404)
