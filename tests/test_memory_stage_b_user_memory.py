import json

import pandas as pd


def test_user_memory_store_writes_one_fact_per_file_and_renders_index(tmp_path):
    from quantbench.memory.store import UserMemoryStore

    store = UserMemoryStore(tmp_path / "memory" / "user")
    fact = store.write(
        {
            "type": "default_preference",
            "description": "Use 10 bps transaction costs by default.",
            "provenance": {"session_id": "session_a", "run_id": "run_a"},
            "confidence": 0.8,
            "fields": {"cost_bps": 10},
            "statement": "Default transaction cost is 10 bps.",
        }
    )

    facts = store.read_all()
    assert len(facts) == 1
    assert facts[0].fact_id == fact.fact_id
    assert facts[0].fields == {"cost_bps": 10}
    assert (tmp_path / "memory" / "user" / f"{fact.fact_id}.md").exists()

    index = store.render_index()
    assert fact.fact_id in index
    assert "Use 10 bps transaction costs by default." in index
    assert (tmp_path / "memory" / "user" / "INDEX.md").read_text(encoding="utf-8") == index


def test_user_memory_store_updates_conflicting_default_instead_of_appending(tmp_path):
    from quantbench.memory.store import UserMemoryStore

    store = UserMemoryStore(tmp_path / "memory" / "user")
    first = store.write(
        {
            "type": "default_preference",
            "description": "Use 5 bps costs.",
            "provenance": {"session_id": "session_a"},
            "confidence": 0.6,
            "fields": {"cost_bps": 5},
            "statement": "Default transaction cost is 5 bps.",
        }
    )
    second = store.write(
        {
            "type": "default_preference",
            "description": "Use 10 bps costs.",
            "provenance": {"session_id": "session_b"},
            "confidence": 0.8,
            "fields": {"cost_bps": 10},
            "statement": "Default transaction cost is 10 bps.",
        }
    )

    facts = store.read_all()
    assert len(facts) == 1
    assert second.fact_id == first.fact_id
    assert facts[0].fields == {"cost_bps": 10}


def test_memory_defaults_are_visible_in_staging_and_user_override_wins(tmp_path):
    from quantbench.agent.staging import CostEstimate, StagingGate, StagingPolicy
    from quantbench.memory.defaults import apply_memory_defaults
    from quantbench.memory.store import UserMemoryStore

    store = UserMemoryStore(tmp_path / "memory" / "user")
    fact = store.write(
        {
            "type": "default_preference",
            "description": "Use 10 bps transaction costs by default.",
            "provenance": {"session_id": "session_a"},
            "confidence": 0.9,
            "fields": {"cost_bps": 10},
            "statement": "Default transaction cost is 10 bps.",
        }
    )
    config, applied = apply_memory_defaults({"cost_bps": 5, "execution": None}, store.default_facts())
    seen_configs = []

    def confirm(_run_id, _artifact, staged_config):
        seen_configs.append(staged_config)
        return {"config": {"cost_bps": 5}}

    result = StagingGate(
        run_id="run_a",
        run_dir=tmp_path,
        policy=StagingPolicy(force_stage=bool(applied)),
        confirm_callback=confirm,
    ).review(
        code="def compute(df):\n    return df['close'].pct_change().fillna(0)\n",
        factor_values=pd.Series([0.0, 0.1, 0.2]),
        config=config,
        cost=CostEstimate(kind="single", observations=3),
        available_columns=["close"],
    )

    assert seen_configs[0]["cost_bps"] == 10
    assert result.config["cost_bps"] == 5
    assert applied == [{"fact_id": fact.fact_id, "field": "cost_bps", "value": 10}]


def test_memory_index_is_injected_into_coordinator_system_prompt(tmp_path):
    from _fakes import FakeLLMClient
    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore
    from quantbench.memory.store import UserMemoryStore

    memory_store = UserMemoryStore(tmp_path / "memory" / "user")
    memory_store.write(
        {
            "type": "default_preference",
            "description": "Use 10 bps transaction costs by default.",
            "provenance": {"session_id": "session_a"},
            "confidence": 0.9,
            "fields": {"cost_bps": 10},
            "statement": "Default transaction cost is 10 bps.",
        }
    )
    llm = FakeLLMClient([("text", "done")])
    run_store = ArtifactStore(tmp_path / "runs")
    run = run_store.create_run("Summarize the setup")

    Coordinator(run_store=run_store, llm=llm, critic_llm=FakeLLMClient([]), memory_store=memory_store).execute(
        run,
        "Summarize the setup",
    )

    system_prompt = llm.calls[0][0][0]["content"]
    assert "## User Long-Term Memory" in system_prompt
    assert "Use 10 bps transaction costs by default." in system_prompt

    manifest = json.loads((tmp_path / "runs" / run.run_id / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["applied_memory_defaults"] == []
