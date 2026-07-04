import json
from types import SimpleNamespace


def _response_with_usage(content: str, *, prompt_tokens=100, completion_tokens=50):
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    message = SimpleNamespace(role="assistant", content=content, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


class FakeUsageLLMClient:
    """Like tests/_fakes.py's FakeLLMClient, but its responses carry a
    `.usage` attribute (litellm/OpenAI-style) - used to exercise the usage-
    recording path that FakeLLMClient's bare SimpleNamespace responses
    deliberately don't have."""

    model = "fake/usage-model"

    def __init__(self, contents: list[str]):
        self.contents = list(contents)

    def chat(self, messages, tools=None):
        return _response_with_usage(self.contents.pop(0))


class FakeUsageScriptedLLMClient:
    """Same script format as tests/_fakes.py's FakeLLMClient (("text", ...) /
    ("tools", [...])  turns), but every response carries `.usage` - lets a
    full Coordinator.run() drive real tool calls while still exercising
    the manifest's llm_usage accounting end to end."""

    model = "fake/usage-model"

    def __init__(self, script):
        self.script = list(script)

    def chat(self, messages, tools=None):
        kind, payload = self.script.pop(0)
        if kind == "text":
            message = SimpleNamespace(role="assistant", content=payload, tool_calls=None)
        else:
            tool_calls = [
                SimpleNamespace(
                    id=f"call_{i}",
                    function=SimpleNamespace(name=name, arguments=json.dumps(args)),
                )
                for i, (name, args) in enumerate(payload)
            ]
            message = SimpleNamespace(role="assistant", content=None, tool_calls=tool_calls)
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def test_record_llm_usage_appends_record_with_token_counts(monkeypatch):
    from quantbench.agent.llm import record_llm_usage

    monkeypatch.setattr("litellm.completion_cost", lambda completion_response, model: 0.0021)
    response = _response_with_usage("hello")
    sink: list[dict] = []

    record_llm_usage(response, "deepseek/deepseek-chat", sink, step="coordinator")

    assert len(sink) == 1
    record = sink[0]
    assert record["model"] == "deepseek/deepseek-chat"
    assert record["prompt_tokens"] == 100
    assert record["completion_tokens"] == 50
    assert record["total_tokens"] == 150
    assert record["cost_usd"] == 0.0021
    assert record["step"] == "coordinator"


def test_record_llm_usage_is_a_noop_when_response_has_no_usage_attribute():
    from quantbench.agent.llm import record_llm_usage

    bare_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="x", tool_calls=None))])
    sink: list[dict] = []

    record_llm_usage(bare_response, "deepseek/deepseek-chat", sink, step="coordinator")

    assert sink == []


def test_record_llm_usage_is_a_noop_when_sink_is_none():
    from quantbench.agent.llm import record_llm_usage

    # Must not raise even though there's nowhere to put the record.
    record_llm_usage(_response_with_usage("hello"), "deepseek/deepseek-chat", None, step="coordinator")


def test_record_llm_usage_survives_completion_cost_failure(monkeypatch):
    from quantbench.agent.llm import record_llm_usage

    def _boom(completion_response, model):
        raise ValueError("model not in litellm's pricing table")

    monkeypatch.setattr("litellm.completion_cost", _boom)
    sink: list[dict] = []

    record_llm_usage(_response_with_usage("hello"), "some/unpriced-model", sink, step="coordinator")

    assert len(sink) == 1
    assert sink[0]["cost_usd"] is None
    assert sink[0]["total_tokens"] == 150


def test_run_subagent_records_usage_into_sink(monkeypatch):
    from quantbench.agent.subagent import SubAgent, run_subagent
    from quantbench.skills.registry import SkillRegistry

    monkeypatch.setattr("litellm.completion_cost", lambda completion_response, model: 0.001)
    llm = FakeUsageLLMClient([json.dumps({"answer": 42})])
    agent = SubAgent(name="test_agent", system_prompt="be terse", registry=SkillRegistry(), max_turns=1, output_schema={})
    sink: list[dict] = []

    result = run_subagent(llm, agent, {"question": "?"}, usage_sink=sink)

    assert result == {"answer": 42}
    assert len(sink) == 1
    assert sink[0]["step"] == "subagent:test_agent"
    assert sink[0]["model"] == "fake/usage-model"


def test_run_subagent_without_usage_sink_does_not_raise():
    from quantbench.agent.subagent import SubAgent, run_subagent
    from quantbench.skills.registry import SkillRegistry

    llm = FakeUsageLLMClient([json.dumps({"answer": 1})])
    agent = SubAgent(name="test_agent", system_prompt="be terse", registry=SkillRegistry(), max_turns=1, output_schema={})

    assert run_subagent(llm, agent, {"question": "?"}) == {"answer": 1}


def test_screen_factors_summary_includes_pre_flight_cost_estimate(tmp_path, monkeypatch):
    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore
    from test_phase8_factor_screening import JsonCriticLLM, _panel, _patch_universe_and_panel
    from _fakes import FakeLLMClient

    _patch_universe_and_panel(monkeypatch, _panel())
    candidates = [
        {"name": "good", "code": "def compute(df):\n    return df['close'].pct_change(1).fillna(0.0)\n"},
    ]
    script = [
        ("tools", [("build_universe", {"universe_name": "sp500", "as_of_date": "2024-01-01", "limit": 3})]),
        (
            "tools",
            [
                (
                    "screen_factors",
                    {"candidates": candidates, "start": "2024-01-01", "end": "2024-01-08", "n_groups": 3, "cost_bps": 0},
                )
            ],
        ),
        ("text", "screen done"),
    ]

    result = Coordinator(
        run_store=ArtifactStore(tmp_path / "runs"),
        llm=FakeLLMClient(script),
        critic_llm=JsonCriticLLM(),
    ).run("批量筛选一个截面因子，检查成本预估")

    summary = json.loads((result.run_dir / "factor_screen_summary.json").read_text(encoding="utf-8"))
    assert summary["cost_estimate"]["kind"] == "screen"
    assert summary["cost_estimate"]["candidates"] == 1
    assert summary["cost_estimate"]["observations"] == len(_panel())
    assert summary["cost_estimate"]["estimated_critic_delegations"] == 1


def test_coordinator_run_writes_llm_usage_into_manifest(tmp_path, monkeypatch):
    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore

    monkeypatch.setattr("litellm.completion_cost", lambda completion_response, model: 0.0005)
    llm = FakeUsageScriptedLLMClient([("text", "a plain final answer, no tools needed")])
    coordinator = Coordinator(run_store=ArtifactStore(tmp_path / "runs"), llm=llm)

    result = coordinator.run("just say hello, no tools")

    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["llm_usage"]) == 1
    assert manifest["llm_usage"][0]["total_tokens"] == 15
    assert manifest["llm_usage"][0]["step"] == "coordinator"
