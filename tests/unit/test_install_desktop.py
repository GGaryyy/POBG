"""Tests for src/tools/install_desktop.py: the Claude Desktop config is edited in temporary folders only."""

import json
import os
import stat
from pathlib import Path

import pytest

from src.tools import install_desktop as inst

OTHER = {"command": "node", "args": ["server.js"], "env": {"API_KEY": "sk-secret-value"}}
EXISTING = {"mcpServers": {"other": OTHER}, "preferences": {"theme": "dark"}, "coworkUserFilesPath": "C:\\Users\\x"}


@pytest.fixture
def setup(tmp_path):
    """A Claude folder, a fake uv and a project folder whose names hold spaces."""
    claude = tmp_path / "App Data" / "Claude"
    claude.mkdir(parents=True)
    uv = tmp_path / "bin dir" / "uv.exe"
    uv.parent.mkdir()
    uv.write_text("")
    root = tmp_path / "My Games" / "POBG"
    root.mkdir(parents=True)
    return {"config": claude / "claude_desktop_config.json", "uv": uv, "root": root,
            "env": {"APPDATA": str(claude.parent), "UV": str(uv)}}


def run(setup, capsys, *argv, env=None):
    code = inst.main(list(argv), env=setup["env"] if env is None else env, platform="win32",
                     home=setup["root"], root=setup["root"])
    return code, json.loads(capsys.readouterr().out)


def entry(setup):
    return {"command": str(setup["uv"].absolute()),
            "args": ["run", "--frozen", "--no-dev", "--directory", str(setup["root"]), "python", "-m",
                     "src.tools.mcp_server"]}


def backups(setup):
    return sorted(p for p in setup["config"].parent.iterdir() if ".pobg-backup-" in p.name)


# --- install ---------------------------------------------------------------------------------

def test_a_new_config_holds_only_the_pobg_server(setup, capsys):
    code, out = run(setup, capsys)
    assert code == 0 and out["action"] == "installed" and out["backup"] is None
    assert out["config"] == str(setup["config"]) and out["next"].startswith("Start Claude Desktop again")
    assert json.loads(setup["config"].read_text(encoding="utf-8")) == {"mcpServers": {"pobg": entry(setup)}}
    assert backups(setup) == []


def test_other_servers_and_settings_are_kept_and_the_old_file_is_backed_up(setup, capsys):
    original = json.dumps(EXISTING, indent=2)
    setup["config"].write_text(original, encoding="utf-8")
    code, out = run(setup, capsys)
    assert code == 0 and out["action"] == "installed"
    doc = json.loads(setup["config"].read_text(encoding="utf-8"))
    assert doc == {**EXISTING, "mcpServers": {"other": OTHER, "pobg": entry(setup)}}
    assert list(doc) == list(EXISTING)                                  # key order is kept too
    saved = backups(setup)
    assert [str(p) for p in saved] == [out["backup"]] and saved[0].read_text(encoding="utf-8") == original


def test_the_output_never_shows_another_server(setup, capsys):
    setup["config"].write_text(json.dumps(EXISTING), encoding="utf-8")
    inst.main([], env=setup["env"], platform="win32", home=setup["root"], root=setup["root"])
    printed = capsys.readouterr().out
    assert "sk-secret-value" not in printed and "server.js" not in printed and "other" not in json.loads(printed)


def test_a_second_run_changes_nothing_and_makes_no_backup(setup, capsys):
    run(setup, capsys)
    before = setup["config"].read_bytes()
    code, out = run(setup, capsys)
    assert code == 0 and out["action"] == "unchanged" and "backup" not in out
    assert setup["config"].read_bytes() == before and backups(setup) == []


def test_a_different_pobg_entry_is_replaced_and_reported_without_its_environment(setup, capsys):
    old = {"command": "C:\\old\\uv.exe", "args": ["run", "--directory", "C:\\old\\POBG"], "env": {"TOKEN": "hidden"}}
    setup["config"].write_text(json.dumps({"mcpServers": {"pobg": old, "other": OTHER}}), encoding="utf-8")
    code, out = run(setup, capsys)
    assert code == 0 and out["action"] == "updated"
    assert out["previous"] == {"command": "C:\\old\\uv.exe", "args": ["run", "--directory", "C:\\old\\POBG"]}
    servers = json.loads(setup["config"].read_text(encoding="utf-8"))["mcpServers"]
    assert servers == {"pobg": {**entry(setup), "env": {"TOKEN": "hidden"}}, "other": OTHER}
    assert list(servers["pobg"]) == ["command", "args", "env"] and list(servers) == ["pobg", "other"]
    assert len(backups(setup)) == 1 and "hidden" not in json.dumps(out)


@pytest.mark.parametrize("odd", ["text", None, 5, ["x"]])
def test_a_pobg_entry_that_is_not_an_object_is_replaced_or_removed(setup, capsys, odd):
    setup["config"].write_text(json.dumps({"mcpServers": {"pobg": odd, "other": OTHER}}), encoding="utf-8")
    code, out = run(setup, capsys)
    assert code == 0 and out["action"] == ("installed" if odd is None else "updated")     # null: nothing there
    assert out.get("previous") is None
    assert json.loads(setup["config"].read_text(encoding="utf-8"))["mcpServers"] == {"pobg": entry(setup), "other": OTHER}
    setup["config"].write_text(json.dumps({"mcpServers": {"pobg": odd, "other": OTHER}}), encoding="utf-8")
    code, out = run(setup, capsys, "--remove")
    assert code == 0 and out["action"] == "removed"
    assert json.loads(setup["config"].read_text(encoding="utf-8"))["mcpServers"] == {"other": OTHER}


def test_mcp_servers_null_counts_as_none_registered(setup, capsys):
    setup["config"].write_text('{"mcpServers": null, "preferences": {}}', encoding="utf-8")
    assert run(setup, capsys, "--remove")[1]["action"] == "unchanged"
    assert run(setup, capsys)[1]["action"] == "installed"
    assert json.loads(setup["config"].read_text(encoding="utf-8")) == {"mcpServers": {"pobg": entry(setup)}, "preferences": {}}


def test_an_env_the_user_added_is_kept_and_does_not_count_as_a_change(setup, capsys):
    mine = {**entry(setup), "env": {"UV_PROJECT_ENVIRONMENT": "C:\\venvs\\pobg"}}
    setup["config"].write_text(json.dumps({"mcpServers": {"pobg": mine}}), encoding="utf-8")
    before = setup["config"].read_bytes()
    code, out = run(setup, capsys)
    assert code == 0 and out["action"] == "unchanged" and "UV_PROJECT_ENVIRONMENT" not in json.dumps(out)
    assert setup["config"].read_bytes() == before and backups(setup) == []


def test_check_writes_nothing(setup, capsys):
    code, out = run(setup, capsys, "--check")
    assert code == 0 and out["action"] == "would be installed" and not setup["config"].exists()
    setup["config"].write_text(json.dumps(EXISTING), encoding="utf-8")
    before = setup["config"].read_bytes()
    code, out = run(setup, capsys, "--check")
    assert out["action"] == "would be installed" and out["note"] == "Nothing was written (--check)."
    assert setup["config"].read_bytes() == before and backups(setup) == []


def test_paths_with_spaces_and_backslashes_survive_the_json(setup, capsys):
    run(setup, capsys)
    written = json.loads(setup["config"].read_text(encoding="utf-8"))["mcpServers"]["pobg"]
    assert written["command"] == str(setup["uv"].absolute()) and " " in written["command"]
    assert written["args"][4] == str(setup["root"]) and " " in written["args"][4]


def test_a_config_with_a_byte_order_mark_or_no_content_is_read(setup, capsys):
    setup["config"].write_bytes(b"\xef\xbb\xbf" + json.dumps(EXISTING).encode("utf-8"))
    assert run(setup, capsys)[1]["action"] == "installed"
    assert json.loads(setup["config"].read_text(encoding="utf-8"))["mcpServers"]["other"] == OTHER
    setup["config"].write_text("  \n", encoding="utf-8")
    assert run(setup, capsys)[1]["action"] == "installed"


# --- remove ----------------------------------------------------------------------------------

def test_remove_takes_out_only_pobg(setup, capsys):
    setup["config"].write_text(json.dumps(EXISTING), encoding="utf-8")
    run(setup, capsys)
    code, out = run(setup, capsys, "--remove")
    assert code == 0 and out["action"] == "removed" and out["previous"] == entry(setup)
    assert json.loads(setup["config"].read_text(encoding="utf-8")) == EXISTING
    assert len(backups(setup)) == 2                                     # one per change


def test_remove_without_a_registration_writes_nothing(setup, capsys):
    setup["config"].write_text(json.dumps(EXISTING), encoding="utf-8")
    before = setup["config"].read_bytes()
    code, out = run(setup, capsys, "--remove")
    assert code == 0 and out["action"] == "unchanged" and "not registered" in out["note"]
    assert setup["config"].read_bytes() == before and backups(setup) == []
    setup["config"].unlink()
    assert run(setup, capsys, "--remove")[1]["action"] == "unchanged" and not setup["config"].exists()


def test_remove_check_writes_nothing(setup, capsys):
    run(setup, capsys)
    before = setup["config"].read_bytes()
    code, out = run(setup, capsys, "--remove", "--check")
    assert code == 0 and out["action"] == "would be removed"
    assert setup["config"].read_bytes() == before and backups(setup) == []


def test_remove_never_prints_the_entrys_environment(setup, capsys):
    mine = {**entry(setup), "env": {"TOKEN": "sk-secret-value"}}
    setup["config"].write_text(json.dumps({"mcpServers": {"pobg": mine}}), encoding="utf-8")
    for argv in (["--remove", "--check"], ["--remove"]):
        inst.main(argv, env=setup["env"], platform="win32", home=setup["root"], root=setup["root"])
        assert "sk-secret-value" not in capsys.readouterr().out


# --- refusals --------------------------------------------------------------------------------

@pytest.mark.parametrize("content, message", [
    ('{"mcpServers": {', "is not valid JSON"),
    ("[1, 2]", "does not have the expected shape"),
    ('{"mcpServers": ["x"]}', "does not have the expected shape"),
    ('"text"', "does not have the expected shape"),
    ('{"x": 1e400, "mcpServers": {}}'.replace("1e400", "Infinity"), "is not valid JSON"),
    ('{"x": NaN}', "is not valid JSON"),
    ('{"n": ' + "9" * 5000 + "}", "is not valid JSON"),
    ("[" * 100000, "is not valid JSON"),
    ('{"s": "\\ud800"}', "cannot be written back"),
])
def test_a_config_that_cannot_be_understood_is_left_alone(setup, capsys, content, message):
    setup["config"].write_text(content, encoding="utf-8")
    setup["config"].write_text(content.replace('{"s"', '{"mcpServers": {"pobg": 1}, "s"'), encoding="utf-8")
    before = setup["config"].read_bytes()
    for argv in ([], ["--remove"]):
        code, out = run(setup, capsys, *argv)
        assert code == 1 and message in out["error"] and "left unchanged" in out["error"]
    assert setup["config"].read_bytes() == before
    assert sorted(p.name for p in setup["config"].parent.iterdir()) == [setup["config"].name]   # no backup, no .tmp


def test_no_claude_folder_is_an_error_and_creates_nothing(setup, capsys, tmp_path):
    empty = tmp_path / "nowhere"
    code, out = run(setup, capsys, env={"APPDATA": str(empty), "UV": str(setup["uv"])})
    assert code == 1 and "was not found" in out["error"] and "--config" in out["error"]
    assert not empty.exists()
    code, out = run(setup, capsys, env={"UV": str(setup["uv"])})                      # no location known at all
    assert code == 1 and "no known location" in out["error"]


def test_uv_missing_is_an_error_before_anything_is_written(setup, capsys):
    code, out = run(setup, capsys, env={"APPDATA": setup["env"]["APPDATA"], "PATH": ""})
    assert code == 1 and "uv was not found" in out["error"] and inst.UV_INSTALL_URL in out["error"]
    assert not setup["config"].exists()


def test_uv_is_taken_from_path_when_uv_run_did_not_name_it(setup, capsys):
    uv = setup["uv"].with_name("uv")
    uv.write_text("#!/bin/sh\n")
    uv.chmod(0o755)
    env = {"APPDATA": setup["env"]["APPDATA"], "PATH": str(uv.parent), "UV": str(setup["root"] / "gone")}
    code, out = run(setup, capsys, env=env)
    assert code == 0 and out["server"]["command"] == str(uv.absolute())


def test_uv_keeps_the_stable_link_and_not_the_versioned_file_behind_it(setup, capsys, tmp_path):
    versioned = tmp_path / "Cellar" / "uv" / "0.13.7" / "uv"
    versioned.parent.mkdir(parents=True)
    versioned.write_text("#!/bin/sh\n")
    versioned.chmod(0o755)
    stable = tmp_path / "homebrew bin" / "uv"
    stable.parent.mkdir()
    stable.symlink_to(versioned)
    appdata = setup["env"]["APPDATA"]
    code, out = run(setup, capsys, env={"APPDATA": appdata, "PATH": str(stable.parent), "UV": str(versioned)})
    assert code == 0 and out["server"]["command"] == str(stable)        # uv run named the file; PATH has the link
    setup["config"].unlink()
    code, out = run(setup, capsys, env={"APPDATA": appdata, "PATH": "", "UV": str(stable)})
    assert out["server"]["command"] == str(stable) and "0.13.7" not in out["server"]["command"]


def test_the_same_path_in_another_letter_case_keeps_the_spelling_uv_gave(setup, capsys, monkeypatch):
    shouted = str(setup["uv"]).replace("uv.exe", "uv.EXE")                # what Windows returns from PATH
    monkeypatch.setattr(inst.shutil, "which", lambda name, path=None: shouted)
    monkeypatch.setattr(inst.os.path, "normcase", str.lower)
    code, out = run(setup, capsys)
    assert code == 0 and out["server"]["command"] == str(setup["uv"].absolute())


def test_an_injected_environment_without_path_does_not_fall_back_to_the_real_one(setup, capsys):
    code, out = run(setup, capsys, env={"APPDATA": setup["env"]["APPDATA"], "UV": str(setup["root"] / "gone")})
    assert code == 1 and "uv was not found" in out["error"]


def test_a_write_failure_leaves_the_file_and_no_temporary_file(setup, capsys, monkeypatch):
    setup["config"].write_text(json.dumps(EXISTING), encoding="utf-8")
    before = setup["config"].read_bytes()

    def refuse(src, dst):
        raise PermissionError("locked")
    monkeypatch.setattr(inst.os, "replace", refuse)
    code, out = run(setup, capsys)
    assert code == 1 and "could not be read or written (PermissionError)" in out["error"]
    assert setup["config"].read_bytes() == before
    assert sorted(p.name for p in setup["config"].parent.iterdir()) == [setup["config"].name]   # backup taken back


def test_a_config_changed_meanwhile_is_not_overwritten(setup, capsys, monkeypatch):
    setup["config"].write_text(json.dumps(EXISTING), encoding="utf-8")
    real_read = inst.read_config

    def read_then_the_app_writes(config):
        doc = real_read(config)
        config.write_text(json.dumps({**EXISTING, "preferences": {"theme": "light", "more": True}}), encoding="utf-8")
        return doc
    monkeypatch.setattr(inst, "read_config", read_then_the_app_writes)
    code, out = run(setup, capsys)
    assert code == 1 and "changed while this was running" in out["error"] and "Quit Claude Desktop" in out["error"]
    assert json.loads(setup["config"].read_text(encoding="utf-8"))["preferences"] == {"theme": "light", "more": True}
    assert sorted(p.name for p in setup["config"].parent.iterdir()) == [setup["config"].name]


def test_a_linked_config_keeps_its_link_and_the_target_is_updated(setup, capsys, tmp_path):
    target = tmp_path / "dotfiles" / "claude.json"
    target.parent.mkdir()
    target.write_text(json.dumps(EXISTING), encoding="utf-8")
    target.chmod(0o640)
    setup["config"].symlink_to(target)
    code, out = run(setup, capsys)
    assert code == 0 and setup["config"].is_symlink()
    assert json.loads(target.read_text(encoding="utf-8"))["mcpServers"]["pobg"] == entry(setup)
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o640
    assert Path(out["backup"]).parent == target.parent and json.loads(Path(out["backup"]).read_text()) == EXISTING


def test_two_changes_in_one_second_get_two_backups(setup, monkeypatch):
    setup["config"].write_text(json.dumps(EXISTING), encoding="utf-8")
    first = inst.install(setup["config"], entry(setup), False, "20261113-120000")
    second = inst.remove(setup["config"], False, "20261113-120000")
    assert first["backup"].endswith(".pobg-backup-20261113-120000")
    assert second["backup"].endswith(".pobg-backup-20261113-120000-2")
    assert json.loads(Path(first["backup"]).read_text()) == EXISTING and "pobg" in Path(second["backup"]).read_text()


# --- where the config is ---------------------------------------------------------------------

def test_config_option_names_the_file(setup, capsys, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    code, out = run(setup, capsys, "--config", str(elsewhere / "claude_desktop_config.json"))
    assert code == 0 and out["config"] == str(elsewhere / "claude_desktop_config.json")
    assert (elsewhere / "claude_desktop_config.json").exists() and not setup["config"].exists()
    code, out = run(setup, capsys, "--config", str(tmp_path / "missing" / "x.json"))
    assert code == 1 and "does not exist" in out["error"]


def test_config_option_takes_a_folder_and_a_relative_path(setup, capsys, tmp_path, monkeypatch):
    elsewhere = tmp_path / "given folder"
    elsewhere.mkdir()
    code, out = run(setup, capsys, "--config", str(elsewhere))
    assert code == 0 and out["config"] == str(elsewhere / "claude_desktop_config.json")
    monkeypatch.chdir(elsewhere)
    code, out = run(setup, capsys, "--config", "other.json", "--check")
    assert code == 0 and out["config"] == str(elsewhere / "other.json")           # printed in full


def test_config_locations_per_system(tmp_path):
    home = tmp_path / "home"
    name = "claude_desktop_config.json"
    assert inst.config_candidates("darwin", {}, home) == [home / "Library" / "Application Support" / "Claude" / name]
    assert inst.config_candidates("linux", {}, home) == [home / ".config" / "Claude" / name]
    assert inst.config_candidates("linux", {"XDG_CONFIG_HOME": str(tmp_path / "xdg")}, home) == [
        tmp_path / "xdg" / "Claude" / name]
    roaming, local = tmp_path / "Roaming", tmp_path / "Local"
    store = local / "Packages" / "Claude_abc123" / "LocalCache" / "Roaming" / "Claude"
    store.mkdir(parents=True)
    (local / "Packages" / "SomethingElse").mkdir()
    found = inst.config_candidates("win32", {"APPDATA": str(roaming), "LOCALAPPDATA": str(local)}, home)
    assert found == [roaming / "Claude" / name, store / name]
    assert inst.config_candidates("win32", {}, home) == []


def test_the_place_that_holds_a_config_wins_and_two_configs_need_a_choice(setup, capsys, tmp_path):
    local = tmp_path / "Local"
    store = local / "Packages" / "Claude_abc123" / "LocalCache" / "Roaming" / "Claude"
    store.mkdir(parents=True)
    (store / "claude_desktop_config.json").write_text(json.dumps(EXISTING), encoding="utf-8")
    env = {**setup["env"], "LOCALAPPDATA": str(local)}                  # %APPDATA%\\Claude exists but is empty
    code, out = run(setup, capsys, env=env, )
    assert code == 0 and Path(out["config"]) == store / "claude_desktop_config.json" and not setup["config"].exists()
    setup["config"].write_text("{}", encoding="utf-8")
    code, out = run(setup, capsys, env=env)
    assert code == 1 and "more than one place" in out["error"] and "--config" in out["error"]
    assert setup["config"].read_text(encoding="utf-8") == "{}"


def test_the_store_build_is_used_when_the_usual_folder_is_missing(setup, capsys, tmp_path):
    local = tmp_path / "Local"
    store = local / "Packages" / "Claude_abc123" / "LocalCache" / "Roaming" / "Claude"
    store.mkdir(parents=True)
    env = {"APPDATA": str(tmp_path / "no roaming"), "LOCALAPPDATA": str(local), "UV": str(setup["uv"])}
    code, out = run(setup, capsys, env=env)
    assert code == 0 and Path(out["config"]) == store / "claude_desktop_config.json"


def test_the_entry_starts_the_server_module_from_this_repo():
    made = inst.server_entry("uv", inst.ROOT)
    assert made["args"][-3:] == ["python", "-m", "src.tools.mcp_server"] and made["args"][4] == str(inst.ROOT)
    assert (inst.ROOT / "src" / "tools" / "mcp_server.py").is_file() and (inst.ROOT / "pyproject.toml").is_file()
