import json

from fastapi.testclient import TestClient


def _write_completed_run(runs_dir, run_id, *, request="raw transcript should not leak"):
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": run_id,
        "user_request": request,
        "created_at": "2026-07-04T00:00:00+00:00",
        "summary": "Long free-form assistant transcript should not be copied into session context.",
        "metrics": {"sharpe": 1.23, "max_drawdown": -0.08},
        "review": {"verdict": "PROMISING"},
        "warnings": [],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "request.txt").write_text(request, encoding="utf-8")


def test_session_store_persists_turns_and_context_uses_structured_run_summary(tmp_path, monkeypatch):
    from quantbench.api import run_reader
    from quantbench.api.session import SessionStore, build_session_context, summarize_run

    monkeypatch.setattr(run_reader, "RUNS_DIR", tmp_path)
    _write_completed_run(tmp_path, "run_20260704_000000_abcd", request="测试动量因子")

    store = SessionStore(tmp_path)
    session = store.create()
    summary = summarize_run("run_20260704_000000_abcd")
    store.append_turn(session.session_id, "第一轮：测试动量因子", "run_20260704_000000_abcd", summary)

    reloaded = store.get(session.session_id)
    assert reloaded.session_id == session.session_id
    assert reloaded.turns[0].turn_index == 0
    assert reloaded.turns[0].summary == {
        "hypothesis": "测试动量因子",
        "verdict": "PROMISING",
        "key_metrics": {"max_drawdown": -0.08, "sharpe": 1.23},
        "run_id": "run_20260704_000000_abcd",
    }

    context = build_session_context(reloaded)
    assert "run_20260704_000000_abcd" in context
    assert "测试动量因子" in context
    assert "PROMISING" in context
    assert "sharpe=1.23" in context
    assert "Long free-form assistant transcript" not in context
    assert "raw transcript" not in context


def test_coordinator_session_context_is_injected_and_metadata_is_written(tmp_path):
    from _fakes import FakeLLMClient
    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore

    llm = FakeLLMClient([("text", "done")])
    store = ArtifactStore(tmp_path)
    run = store.create_run("继续追问：手续费改成 10bps")
    coordinator = Coordinator(run_store=store, llm=llm, critic_llm=FakeLLMClient([]))

    coordinator.execute(
        run,
        "继续追问：手续费改成 10bps",
        session_context="本 session 已有 run 摘要如下：\n- run_old: momentum verdict=PROMISING",
        session_id="session_20260704_abcd",
        turn_index=1,
    )

    messages = llm.calls[0][0]
    assert messages[1]["role"] == "user"
    assert messages[1]["content"].startswith("本 session 已有 run 摘要如下")
    assert "继续追问：手续费改成 10bps" in messages[1]["content"]

    manifest = json.loads((tmp_path / run.run_id / "manifest.json").read_text(encoding="utf-8"))
    config = (tmp_path / run.run_id / "config.yaml").read_text(encoding="utf-8")
    assert manifest["session_id"] == "session_20260704_abcd"
    assert manifest["turn_index"] == 1
    assert "session_id: session_20260704_abcd" in config
    assert "turn_index: 1" in config


def test_fork_previous_run_skill_returns_a_new_run_id(monkeypatch):
    from quantbench.agent.coordinator import build_fork_previous_run_skill

    calls = []

    def fake_execute_fork(run_id, modification):
        calls.append((run_id, modification))
        return "run_child"

    skill = build_fork_previous_run_skill(fake_execute_fork)
    result = skill.fn("run_parent", "把手续费改成 10bps")

    assert result == {"run_id": "run_child", "parent_run_id": "run_parent"}
    assert calls == [("run_parent", "把手续费改成 10bps")]


def test_session_api_creates_session_runs_turn_and_returns_thread(tmp_path, monkeypatch):
    from quantbench.api import run_reader
    from quantbench.api import server as server_mod

    monkeypatch.setattr(run_reader, "RUNS_DIR", tmp_path)

    class FakeManager:
        def submit_session_turn(self, session_id, user_message, session_context, turn_index):
            assert session_id.startswith("session_")
            assert user_message == "第一轮：测试动量因子"
            assert session_context == ""
            assert turn_index == 0
            return "run_20260704_000000_abcd"

    server_mod._manager = FakeManager()
    client = TestClient(server_mod.app)

    created = client.post("/api/sessions").json()
    session_id = created["session_id"]
    turn = client.post(f"/api/sessions/{session_id}/turns", json={"user_message": "第一轮：测试动量因子"})

    assert turn.status_code == 200
    assert turn.json() == {"run_id": "run_20260704_000000_abcd", "status": "running"}

    thread = client.get(f"/api/sessions/{session_id}").json()
    assert thread["session_id"] == session_id
    assert thread["turns"][0]["user_message"] == "第一轮：测试动量因子"
    assert thread["turns"][0]["run_id"] == "run_20260704_000000_abcd"
