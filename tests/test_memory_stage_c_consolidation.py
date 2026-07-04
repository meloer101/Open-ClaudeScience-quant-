import json

from _fakes import FakeLLMClient


def _session(session_id, run_id):
    from quantbench.api.session import Session, SessionTurn

    return Session(
        session_id=session_id,
        created_at="2026-07-04T00:00:00+00:00",
        turns=[
            SessionTurn(
                turn_index=0,
                user_message="Use 10 bps costs.",
                run_id=run_id,
                summary={"run_id": run_id, "hypothesis": "cost preference", "key_metrics": {}, "verdict": "PROMISING"},
            )
        ],
    )


def _candidate_payload(cost_bps=10):
    return {
        "candidates": [
            {
                "type": "default_preference",
                "description": f"Use {cost_bps} bps transaction costs by default.",
                "fields": {"cost_bps": cost_bps},
                "statement": f"Default transaction cost is {cost_bps} bps.",
                "confidence": 0.7,
            }
        ]
    }


def test_single_session_candidate_is_recorded_but_not_promoted(tmp_path):
    from quantbench.memory.consolidation import consolidate_session
    from quantbench.memory.store import UserMemoryStore

    store = UserMemoryStore(tmp_path / "memory" / "user")
    llm = FakeLLMClient([("text", json.dumps(_candidate_payload(10)))])

    result = consolidate_session(_session("session_a", "run_a"), memory_store=store, llm=llm, promotion_threshold=2)

    assert store.read_all() == []
    assert result.visible_messages == []
    events = store.read_events()
    assert len(events) == 1
    assert events[0]["action"] == "candidate"
    assert events[0]["provenance"]["session_id"] == "session_a"


def test_repeated_candidate_across_sessions_promotes_memory_and_visible_event(tmp_path):
    from quantbench.memory.consolidation import consolidate_session
    from quantbench.memory.store import UserMemoryStore

    store = UserMemoryStore(tmp_path / "memory" / "user")
    consolidate_session(
        _session("session_a", "run_a"),
        memory_store=store,
        llm=FakeLLMClient([("text", json.dumps(_candidate_payload(10)))]),
        promotion_threshold=2,
    )
    result = consolidate_session(
        _session("session_b", "run_b"),
        memory_store=store,
        llm=FakeLLMClient([("text", json.dumps(_candidate_payload(10)))]),
        promotion_threshold=2,
    )

    facts = store.read_all()
    assert len(facts) == 1
    assert facts[0].fields == {"cost_bps": 10}
    assert facts[0].provenance["sessions"] == ["session_a", "session_b"]
    assert result.visible_messages == ["已写入记忆: Use 10 bps transaction costs by default."]
    assert any(event["action"] == "write" for event in result.memory_events)
    assert result.delegations[0]["name"] == "memory_consolidator"


def test_conflicting_promoted_default_updates_existing_fact_instead_of_appending(tmp_path):
    from quantbench.memory.consolidation import consolidate_session
    from quantbench.memory.store import UserMemoryStore

    store = UserMemoryStore(tmp_path / "memory" / "user")
    store.write(
        {
            "type": "default_preference",
            "description": "Use 5 bps transaction costs by default.",
            "provenance": {"sessions": ["session_old"]},
            "confidence": 0.6,
            "fields": {"cost_bps": 5},
            "statement": "Default transaction cost is 5 bps.",
        }
    )

    consolidate_session(
        _session("session_a", "run_a"),
        memory_store=store,
        llm=FakeLLMClient([("text", json.dumps(_candidate_payload(10)))]),
        promotion_threshold=2,
    )
    result = consolidate_session(
        _session("session_b", "run_b"),
        memory_store=store,
        llm=FakeLLMClient([("text", json.dumps(_candidate_payload(10)))]),
        promotion_threshold=2,
    )

    facts = store.read_all()
    assert len(facts) == 1
    assert facts[0].fields == {"cost_bps": 10}
    assert any(event["action"] == "update" for event in result.memory_events)


def test_run_manifest_can_record_memory_events_and_consolidation_delegation(tmp_path):
    from quantbench.artifact.store import ArtifactStore

    run = ArtifactStore(tmp_path).create_run("request")
    run.finalize(
        data_hash="sha256:none",
        code_hash="sha256:none",
        memory_events=[{"action": "write", "fact_id": "fact_a"}],
        delegations=[{"name": "memory_consolidator", "turns_used": 1, "output_hash": "sha256:test"}],
    )

    manifest = json.loads((tmp_path / run.run_id / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["memory_events"] == [{"action": "write", "fact_id": "fact_a"}]
    assert manifest["delegations"][0]["name"] == "memory_consolidator"
