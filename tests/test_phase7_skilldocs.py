import json

from _fakes import FakeLLMClient


def test_parse_skill_doc_frontmatter_and_body(tmp_path):
    from quantbench.skilldocs.doc import parse_skill_md

    path = tmp_path / "crypto-cross-sectional-workflow.md"
    path.write_text(
        "---\n"
        "name: crypto-cross-sectional-workflow\n"
        "description: Crypto cross-sectional universe workflow\n"
        "triggers:\n"
        "  - crypto 截面\n"
        "  - USDT 永续\n"
        "---\n"
        "Build universe first.\n",
        encoding="utf-8",
    )

    doc = parse_skill_md(path)

    assert doc.name == "crypto-cross-sectional-workflow"
    assert doc.triggers == ["crypto 截面", "USDT 永续"]
    assert doc.body == "Build universe first."


def test_registry_matches_crypto_cross_sectional_request_but_not_equity_single_symbol(tmp_path):
    from quantbench.skilldocs.registry import SkillRegistryDocs

    (tmp_path / "crypto-cross-sectional-workflow.md").write_text(
        "---\n"
        "name: crypto-cross-sectional-workflow\n"
        "description: Crypto cross-sectional universe workflow\n"
        "triggers:\n"
        "  - crypto 截面\n"
        "  - USDT 永续\n"
        "---\n"
        "Use build_universe before cross-sectional backtest.\n",
        encoding="utf-8",
    )

    registry = SkillRegistryDocs(tmp_path)

    assert [doc.name for doc in registry.match("构建 top 30 crypto 截面 universe，测试动量因子")] == [
        "crypto-cross-sectional-workflow"
    ]
    assert registry.match("测试 AAPL 单标的均线动量") == []


def test_augmented_prompt_appends_skill_body_without_replacing_base():
    from quantbench.skilldocs.doc import SkillDoc
    from quantbench.skilldocs.inject import build_augmented_system_prompt

    prompt = build_augmented_system_prompt(
        "BASE RULES",
        [SkillDoc("causal-factor-authoring", "desc", ["causal"], "Never use shift(-1).", "/tmp/skill.md")],
    )

    assert prompt.startswith("BASE RULES")
    assert "Skill: causal-factor-authoring" in prompt
    assert "Never use shift(-1)." in prompt


def test_coordinator_records_auto_injected_skills_in_manifest(tmp_path, monkeypatch):
    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore

    skill_dir = tmp_path / "skills_docs"
    skill_dir.mkdir()
    (skill_dir / "crypto-cross-sectional-workflow.md").write_text(
        "---\n"
        "name: crypto-cross-sectional-workflow\n"
        "description: Crypto cross-sectional universe workflow\n"
        "triggers:\n"
        "  - crypto 截面\n"
        "---\n"
        "Use a crypto-safe n_groups choice.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("quantbench.agent.coordinator.DEFAULT_SKILL_DOCS_DIR", skill_dir)

    llm = FakeLLMClient([("text", "No backtest needed for this test.")])
    coordinator = Coordinator(run_store=ArtifactStore(tmp_path / "runs"), llm=llm)

    result = coordinator.run("构建 top 30 crypto 截面 universe，测试动量因子")

    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    config = (result.run_dir / "config.yaml").read_text(encoding="utf-8")
    first_system_prompt = llm.calls[0][0][0]["content"]

    assert manifest["injected_skills"] == ["crypto-cross-sectional-workflow"]
    assert "injected_skills:" in config
    assert "Use a crypto-safe n_groups choice." in first_system_prompt


def test_skill_cli_list_and_show(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from quantbench.cli import main

    skill_dir = tmp_path / "skills_docs"
    skill_dir.mkdir()
    (skill_dir / "reviewer-weak-triage.md").write_text(
        "---\n"
        "name: reviewer-weak-triage\n"
        "description: Triage weak reviewer verdicts\n"
        "triggers:\n"
        "  - WEAK\n"
        "---\n"
        "Check warnings first.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("quantbench.cli.DEFAULT_SKILL_DOCS_DIR", skill_dir)

    runner = CliRunner()
    listed = runner.invoke(main, ["skill", "list"])
    shown = runner.invoke(main, ["skill", "show", "reviewer-weak-triage"])

    assert listed.exit_code == 0, listed.output
    assert "reviewer-weak-triage" in listed.output
    assert "Triage weak reviewer verdicts" in listed.output
    assert "Check warnings first." in shown.output


def test_coordinator_forced_skill_injects_without_auto_match(tmp_path, monkeypatch):
    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore

    skill_dir = tmp_path / "skills_docs"
    skill_dir.mkdir()
    (skill_dir / "reviewer-weak-triage.md").write_text(
        "---\n"
        "name: reviewer-weak-triage\n"
        "description: Triage weak reviewer verdicts\n"
        "triggers:\n"
        "  - WEAK\n"
        "---\n"
        "Check warnings first.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("quantbench.agent.coordinator.DEFAULT_SKILL_DOCS_DIR", skill_dir)

    llm = FakeLLMClient([("text", "forced skill")])
    coordinator = Coordinator(run_store=ArtifactStore(tmp_path / "runs"), llm=llm)
    result = coordinator.run("plain AAPL request", skill_names=["reviewer-weak-triage"])

    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["injected_skills"] == ["reviewer-weak-triage"]
