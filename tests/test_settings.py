import json

import pytest


@pytest.fixture
def scoped_settings(tmp_path, monkeypatch):
    """Point the user/project settings files at tmp_path so tests never touch real config."""
    user = tmp_path / "user_settings.json"
    project = tmp_path / "project_settings.json"
    monkeypatch.setattr("quantbench.settings.USER_SETTINGS_FILE", user)
    monkeypatch.setattr("quantbench.settings.PROJECT_SETTINGS_FILE", project)
    monkeypatch.setattr("quantbench.settings.SETTINGS_FILES", [user, project])
    return user, project


def test_load_settings_deep_merges_project_over_user(scoped_settings):
    from quantbench.settings import load_settings

    user, project = scoped_settings
    user.write_text(
        json.dumps({"mcp": {"disabledServers": ["a"]}, "skills": {"disabledSkills": ["s1"]}}),
        encoding="utf-8",
    )
    project.write_text(json.dumps({"mcp": {"disabledServers": ["b"]}}), encoding="utf-8")

    merged = load_settings()

    # project overrides the mcp block wholesale, but the user-only skills block survives the merge.
    assert merged["mcp"]["disabledServers"] == ["b"]
    assert merged["skills"]["disabledSkills"] == ["s1"]


def test_is_server_and_skill_enabled_read_disabled_lists(scoped_settings):
    from quantbench.settings import is_server_enabled, is_skill_enabled

    settings = {"mcp": {"disabledServers": ["off"]}, "skills": {"disabledSkills": ["muted"]}}

    assert is_server_enabled("on", settings) is True
    assert is_server_enabled("off", settings) is False
    assert is_skill_enabled("active", settings) is True
    assert is_skill_enabled("muted", settings) is False


def test_default_is_enabled_when_no_settings(scoped_settings):
    from quantbench.settings import is_server_enabled, is_skill_enabled

    # No settings files exist yet: everything defaults to enabled (disable-list semantics).
    assert is_server_enabled("anything") is True
    assert is_skill_enabled("anything") is True


def test_set_server_enabled_toggles_scoped_file_and_round_trips(scoped_settings):
    from quantbench.settings import is_server_enabled, load_settings, set_server_enabled

    user, project = scoped_settings

    set_server_enabled("remote", False, scope="user")
    assert not is_server_enabled("remote", load_settings())
    assert json.loads(user.read_text(encoding="utf-8"))["mcp"]["disabledServers"] == ["remote"]
    assert not project.exists()  # user scope must not write the project file

    set_server_enabled("remote", True, scope="user")
    assert is_server_enabled("remote", load_settings())
    assert json.loads(user.read_text(encoding="utf-8"))["mcp"]["disabledServers"] == []


def test_set_skill_enabled_writes_project_scope(scoped_settings):
    from quantbench.settings import set_skill_enabled

    user, project = scoped_settings

    set_skill_enabled("triage", False, scope="project")

    assert json.loads(project.read_text(encoding="utf-8"))["skills"]["disabledSkills"] == ["triage"]
    assert not user.exists()


def test_set_enabled_rejects_unknown_scope(scoped_settings):
    from quantbench.settings import set_server_enabled

    with pytest.raises(ValueError):
        set_server_enabled("x", False, scope="global")


def test_load_settings_skips_corrupt_file_with_warning(scoped_settings):
    from quantbench.settings import load_settings

    user, project = scoped_settings
    user.write_text("{not valid json", encoding="utf-8")
    project.write_text(json.dumps({"mcp": {"disabledServers": ["b"]}}), encoding="utf-8")

    with pytest.warns(UserWarning, match="Skipping settings file"):
        merged = load_settings()

    # The corrupt user file is skipped, but the valid project file still loads.
    assert merged["mcp"]["disabledServers"] == ["b"]


def test_load_settings_skips_non_object_root_with_warning(scoped_settings):
    from quantbench.settings import load_settings

    user, _ = scoped_settings
    user.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    with pytest.warns(UserWarning, match="root must be an object"):
        assert load_settings() == {}
