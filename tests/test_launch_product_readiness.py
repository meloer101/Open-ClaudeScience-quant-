import json

from fastapi.testclient import TestClient


def test_devserver_plan_binds_localhost_and_sets_tokens():
    from quantbench.devserver import build_devserver_plan

    plan = build_devserver_plan(api_port=8765, web_port=8766, token="token")

    assert "--host" in plan.api_cmd
    assert "127.0.0.1" in plan.api_cmd
    assert plan.web_url == "http://127.0.0.1:8766"
    assert plan.env["QUANTBENCH_API_TOKEN"] == "token"
    assert plan.env["VITE_QUANTBENCH_API_TOKEN"] == "token"


class _FakeProc:
    def wait(self, timeout=None):
        return 0

    def terminate(self):
        pass

    def kill(self):
        pass


def test_missing_tools_flags_absent_binaries(monkeypatch):
    from quantbench import devserver

    present = {"uv", "npm"}
    monkeypatch.setattr(devserver.shutil, "which", lambda name: "/usr/bin/x" if name in present else None)

    assert devserver.missing_tools() == ["node"]


def test_run_devserver_aborts_with_readable_hint_when_tool_missing(tmp_path, monkeypatch, capsys):
    from quantbench import devserver

    monkeypatch.setattr(devserver, "missing_tools", lambda tools=None: ["npm"])
    started: list = []
    monkeypatch.setattr(devserver.subprocess, "Popen", lambda *a, **k: started.append(a))

    code = devserver.run_devserver(devserver.build_devserver_plan(token="t"), cwd=tmp_path)

    assert code == 1
    assert started == []  # bail out before spawning anything
    out = capsys.readouterr().out
    assert "npm" in out and "nodejs.org" in out


def test_run_devserver_auto_installs_web_deps_on_first_run(tmp_path, monkeypatch):
    from quantbench import devserver

    web_dir = tmp_path / "web"
    web_dir.mkdir()
    monkeypatch.setattr(devserver, "missing_tools", lambda tools=None: [])

    installs: list = []

    def fake_install(wd, env=None):
        (wd / "node_modules").mkdir()  # simulate a successful install
        installs.append(wd)
        return 0

    monkeypatch.setattr(devserver, "install_web_deps", fake_install)
    started: list = []
    monkeypatch.setattr(devserver.subprocess, "Popen", lambda *a, **k: (started.append(a), _FakeProc())[1])

    code = devserver.run_devserver(devserver.build_devserver_plan(token="t"), cwd=tmp_path)

    assert installs == [web_dir]
    assert len(started) == 2  # api + web both spawned after install
    assert code == 0


def test_run_devserver_skips_install_when_deps_present(tmp_path, monkeypatch):
    from quantbench import devserver

    (tmp_path / "web" / "node_modules").mkdir(parents=True)
    monkeypatch.setattr(devserver, "missing_tools", lambda tools=None: [])

    def _fail_install(*_a, **_k):
        raise AssertionError("install_web_deps should not run when node_modules exists")

    monkeypatch.setattr(devserver, "install_web_deps", _fail_install)
    monkeypatch.setattr(devserver.subprocess, "Popen", lambda *a, **k: _FakeProc())

    code = devserver.run_devserver(devserver.build_devserver_plan(token="t"), cwd=tmp_path)

    assert code == 0


def test_seed_example_runs_writes_browsable_artifacts(tmp_path):
    from quantbench.examples import EXAMPLE_RUN_ID, seed_example_runs

    result = seed_example_runs(tmp_path)
    run_dir = tmp_path / EXAMPLE_RUN_ID

    assert result["created"] == 1
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "review_report.json").exists()
    assert "not investment advice" in (run_dir / "research_note.md").read_text(encoding="utf-8").lower()


def test_cost_estimate_is_deterministic_and_positive():
    from quantbench.costing import estimate_request_cost

    estimate = estimate_request_cost("在标普500里测试20日动量截面因子")

    assert estimate["estimated_tokens"] >= 1200
    assert estimate["estimated_usd"] > 0
    assert estimate["coordinator_calls"] >= 1


def test_cost_estimate_api(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTBENCH_API_TOKEN", "test-token")
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path)
    from quantbench.api.server import app

    client = TestClient(app, headers={"X-QuantBench-Token": "test-token"})
    response = client.post("/api/runs/estimate-cost", json={"request": "test a crypto momentum strategy"})

    assert response.status_code == 200
    assert response.json()["estimated_tokens"] >= 1200


def test_release_docs_exist_and_contain_required_checks():
    release = __import__("pathlib").Path("docs/RELEASE.md").read_text(encoding="utf-8")
    changelog = __import__("pathlib").Path("CHANGELOG.md").read_text(encoding="utf-8")

    assert "Run backend tests" in release
    assert "Run frontend lint/unit/build" in release
    assert "0.1.0-alpha" in changelog


def test_root_internal_docs_moved_to_docs_dev():
    from pathlib import Path

    root_docs = [path.name for path in Path(".").glob("PHASE*.md")]

    # Phase implementation logs and status snapshots were pruned entirely
    # ahead of V0 (superseded by shipped code/tests and LAUNCH_READINESS.md),
    # not just relocated - so docs/dev/ should have neither PHASE*.md nor
    # PROJECT_STATUS.md, and root should never regain any PHASE*.md either.
    assert root_docs == []
    assert list(Path("docs/dev").glob("PHASE*.md")) == []
    assert not Path("docs/dev/PROJECT_STATUS.md").exists()
    assert Path("docs/dev/VISION.md").exists()
    assert Path("docs/dev/GAP_ANALYSIS.md").exists()
