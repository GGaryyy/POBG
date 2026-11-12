import hashlib
import io
import json
import os
import time
import zipfile
from pathlib import Path

import pytest
import requests

from src.tools import pob_update as pu
from src.tools.pob_update import UpdateError

MANIFEST = '<?xml version="1.0"?><PoBVersion><Version number="{v}" platform="win32" branch="master" /></PoBVersion>'
CHARM_SHA = "86198db8ad707e000d19a4ba19a93720566747f0"
POB_URL = "https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/releases/download/v0.23.1/pob.zip"
NEW_CHARM = "PoeCharm2-20260728-pob0.23.1"


def zip_bytes(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


POB_ZIP = zip_bytes({"manifest.xml": MANIFEST.format(v="0.23.1"), "Path of Building-PoE2.exe": "exe",
                     "TreeData/0_5/tree.json": "{}"})
CHARM_ZIP = zip_bytes({f"PoeCharm2-{CHARM_SHA}/PoeCharm3.exe": "charm", f"PoeCharm2-{CHARM_SHA}/Data/Settings.conf":
                       "[PathOfBuilding]\nTranslateTL=zh-rCN\n", f"PoeCharm2-{CHARM_SHA}/README.md": "# PoeCharm2"})


class FakeHttp:
    def __init__(self, pob_zip=POB_ZIP, digest=None, tag="v0.23.1", charm_zip=CHARM_ZIP, fail_download=False,
                 asset=None, commit=None, size=None):
        self.pob_zip, self.charm_zip, self.fail_download = pob_zip, charm_zip, fail_download
        self.digest = digest if digest is not None else "sha256:" + hashlib.sha256(pob_zip).hexdigest()
        self.tag, self.asset, self.size = tag, asset, size
        self.commit = commit or {"sha": CHARM_SHA, "commit": {"committer": {"date": "2026-07-28T01:34:45Z"}}}
        self.calls: list[str] = []

    def get_json(self, url):
        self.calls.append(url)
        if url == pu.POB_RELEASE_URL:
            asset = {"name": pu.POB_ASSET, "size": self.size if self.size is not None else len(self.pob_zip),
                     "browser_download_url": POB_URL}
            if self.digest:
                asset["digest"] = self.digest
            return {"tag_name": self.tag, "assets": [{"name": "Setup.exe"}, self.asset if self.asset is not None else asset]}
        if url == pu.CHARM_COMMIT_URL:
            return [self.commit]
        raise AssertionError(url)

    def download(self, url, dest, on_chunk):
        self.calls.append(url)
        if self.fail_download:
            raise requests.ConnectionError("offline")
        data = self.pob_zip if url == POB_URL else self.charm_zip
        on_chunk(data)
        dest.write_bytes(data)


def make_pob(folder: Path, version="0.11.2") -> Path:
    folder.mkdir(parents=True)
    (folder / "manifest.xml").write_text(MANIFEST.format(v=version), encoding="utf-8")
    (folder / "Settings.xml").write_text("<Accounts lastToken='secret'/>", encoding="utf-8")
    (folder / "Builds" / "Sub").mkdir(parents=True)
    (folder / "Builds" / "Ice.xml").write_text("<PathOfBuilding2/>", encoding="utf-8")
    (folder / "Builds" / "Sub" / "Fire.xml").write_text("<PathOfBuilding2/>", encoding="utf-8")
    return folder


def make_charm(folder: Path, version="0.11.2") -> Path:
    folder.mkdir(parents=True)
    (folder / "PoeCharm3.exe").write_text("old charm", encoding="utf-8")
    (folder / "Data").mkdir()
    (folder / "Data" / "Settings.conf").write_text("[PathOfBuilding]\nTranslateTL=zh-rTW\n", encoding="utf-8")
    make_pob(folder / pu.POB_DIR, version)
    return folder


def snapshot(root: Path) -> dict:
    """Every file's bytes and every folder, so a new empty folder shows up too."""
    return {p.relative_to(root): p.read_bytes() if p.is_file() else "dir" for p in root.rglob("*")}


# -- reading an install --------------------------------------------------------------------------------

def test_find_install_kinds_and_versions(tmp_path):
    pob = pu.find_install(make_pob(tmp_path / "pob"))
    assert (pob.kind, pob.version, pob.pob_dir) == ("pob", "0.11.2", tmp_path / "pob")
    charm = pu.find_install(make_charm(tmp_path / "charm", "0.20.0"))
    assert (charm.kind, charm.version, charm.pob_dir) == ("poecharm", "0.20.0", tmp_path / "charm" / pu.POB_DIR)
    assert charm.charm_sha is None


def test_find_install_refuses_other_folders(tmp_path):
    with pytest.raises(UpdateError, match="is not a folder"):
        pu.find_install(tmp_path / "missing")
    (tmp_path / "empty").mkdir()
    with pytest.raises(UpdateError, match="holds neither manifest.xml"):
        pu.find_install(tmp_path / "empty")


def test_read_version_of_missing_or_broken_manifest(tmp_path):
    assert pu.read_version(tmp_path / "none.xml") is None
    (tmp_path / "bad.xml").write_text("<not closed", encoding="utf-8")
    assert pu.read_version(tmp_path / "bad.xml") is None
    (tmp_path / "other.xml").write_text("<PoBVersion/>", encoding="utf-8")
    assert pu.read_version(tmp_path / "other.xml") is None


@pytest.mark.parametrize("a, b", [("0.9.0", "0.23.1"), ("0.23.0", "0.23.1"), ("v0.11.2", "0.23.1"), ("junk", "0.1")])
def test_versions_compare_as_numbers(a, b):
    assert pu._version_key(a) < pu._version_key(b)


# -- the latest release ----------------------------------------------------------------------------------

def test_latest_reads_the_release_and_the_poecharm_commit():
    http = FakeHttp()
    found = pu.latest(http, "poecharm")
    assert (found.version, found.asset_url, found.charm_sha, found.charm_date) == (
        "0.23.1", POB_URL, CHARM_SHA, "2026-07-28")
    assert found.sha256 == hashlib.sha256(POB_ZIP).hexdigest()
    assert http.calls == [pu.POB_RELEASE_URL, pu.CHARM_COMMIT_URL]
    assert pu.latest(FakeHttp(), "pob").charm_sha is None


@pytest.mark.parametrize("http, message", [
    (FakeHttp(digest=""), "publishes no SHA-256"),
    (FakeHttp(digest="md5:abc"), "publishes no SHA-256"),
    (FakeHttp(tag="nightly"), "has no PathOfBuildingCommunity-PoE2-Portable.zip"),
])
def test_latest_refuses_what_cannot_be_checked(http, message):
    with pytest.raises(UpdateError, match=message):
        pu.latest(http, "pob")


def test_latest_without_a_poecharm_commit():
    http = FakeHttp()
    http.get_json = lambda url: [] if url == pu.CHARM_COMMIT_URL else FakeHttp().get_json(url)
    with pytest.raises(UpdateError, match="no usable PoeCharm2 commit"):
        pu.latest(http, "poecharm")


@pytest.mark.parametrize("http", [
    FakeHttp(asset={"name": pu.POB_ASSET, "size": 10, "digest": "sha256:" + "a" * 64}),            # no link
    FakeHttp(asset={"name": pu.POB_ASSET, "size": "big", "browser_download_url": POB_URL,
                    "digest": "sha256:" + "a" * 64}),
    FakeHttp(asset={"name": pu.POB_ASSET, "size": 10, "browser_download_url": "https://evil.example/pob.zip",
                    "digest": "sha256:" + "a" * 64}),
    FakeHttp(size=0),
])
def test_latest_refuses_an_unusable_release_file_record(http):
    with pytest.raises(UpdateError, match="no usable download link or size"):
        pu.latest(http, "pob")


@pytest.mark.parametrize("http, message", [
    (FakeHttp(asset="not a dict"), "has no PathOfBuildingCommunity"),
    (FakeHttp(digest="sha256:short"), "publishes no SHA-256"),
])
def test_latest_refuses_odd_shapes(http, message):
    with pytest.raises(UpdateError, match=message):
        pu.latest(http, "pob")


def test_latest_refuses_assets_that_are_not_a_list():
    http = FakeHttp()
    http.get_json = lambda url: {"tag_name": "v0.23.1", "assets": {"name": pu.POB_ASSET}}
    with pytest.raises(UpdateError, match="has no PathOfBuildingCommunity"):
        pu.latest(http, "pob")


@pytest.mark.parametrize("commit", [
    {"sha": "../../x", "commit": {"committer": {"date": "2026-07-28T00:00:00Z"}}},
    {"sha": CHARM_SHA, "commit": {"committer": {"date": "/../../ev"}}},
    {"sha": CHARM_SHA, "commit": "not a dict"},
    {"sha": CHARM_SHA},
])
def test_latest_refuses_an_odd_poecharm_commit(commit):
    with pytest.raises(UpdateError, match="no usable PoeCharm2 commit"):
        pu.latest(FakeHttp(commit=commit), "poecharm")


# -- check -----------------------------------------------------------------------------------------------------

def test_check_reports_versions_and_writes_nothing(tmp_path):
    folder = make_charm(tmp_path / "PoeCharm2-old")
    before = snapshot(tmp_path)
    result = pu.check(folder, FakeHttp())
    assert snapshot(tmp_path) == before
    assert (result["installed"], result["latest"], result["up_to_date"]) == ("0.11.2", "0.23.1", False)
    assert result["poecharm_latest"] == CHARM_SHA and "unknown" in result["note"]


def test_check_current_installs(tmp_path):
    assert pu.check(make_pob(tmp_path / "pob", "0.23.1"), FakeHttp())["up_to_date"] is True
    charm = make_charm(tmp_path / "charm", "0.23.1")
    assert pu.check(charm, FakeHttp())["up_to_date"] is True                    # PoeCharm2 version unknown
    (charm / pu.MARKER).write_text(json.dumps({"charm_sha": "older"}), encoding="utf-8")
    assert pu.check(charm, FakeHttp())["up_to_date"] is False                   # a newer PoeCharm2 commit


# -- update -----------------------------------------------------------------------------------------------------

def test_update_pob_into_a_new_folder(tmp_path):
    old = make_pob(tmp_path / "PathOfBuildingCommunity-PoE2-Portable")
    before = snapshot(old)
    result = pu.update(old, FakeHttp())
    new = tmp_path / "PathOfBuildingCommunity-PoE2-Portable-0.23.1"
    assert result["updated"] is True and result["new_folder"] == str(new) and result["builds_copied"] == 2
    assert pu.read_version(new / "manifest.xml") == "0.23.1" and (new / "Path of Building-PoE2.exe").is_file()
    assert (new / "Builds" / "Ice.xml").is_file() and (new / "Builds" / "Sub" / "Fire.xml").is_file()
    assert not (new / "Settings.xml").exists()                                  # account login stays behind
    assert json.loads((new / pu.MARKER).read_text(encoding="utf-8"))["pob_version"] == "0.23.1"
    assert snapshot(old) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["PathOfBuildingCommunity-PoE2-Portable",
                                                          "PathOfBuildingCommunity-PoE2-Portable-0.23.1"]


def test_update_poecharm_installs_both(tmp_path):
    old = make_charm(tmp_path / "PoeCharm2-20250410")
    before = snapshot(old)
    result = pu.update(old, FakeHttp())
    new = tmp_path / NEW_CHARM
    assert result["new_folder"] == str(new) and result["language_copied"] is True
    assert not (new / pu.POB_DIR / "Settings.xml").exists()
    assert (new / "PoeCharm3.exe").read_text(encoding="utf-8") == "charm"
    assert pu.read_version(new / pu.POB_DIR / "manifest.xml") == "0.23.1"
    assert "zh-rTW" in (new / "Data" / "Settings.conf").read_text(encoding="utf-8")   # the user's language kept
    assert (new / pu.POB_DIR / "Builds" / "Ice.xml").is_file()
    assert json.loads((new / pu.MARKER).read_text(encoding="utf-8"))["charm_sha"] == CHARM_SHA
    assert "no published checksum" in result["checksum"]
    assert snapshot(old) == before


def test_update_when_current_downloads_nothing(tmp_path):
    http = FakeHttp()
    result = pu.update(make_pob(tmp_path / "pob", "0.23.1"), http)
    assert result["updated"] is False and http.calls == [pu.POB_RELEASE_URL]


def assert_nothing_left(tmp_path, old, before):
    assert [p.name for p in tmp_path.iterdir()] == [old.name]
    assert snapshot(old) == before


def test_checksum_mismatch_keeps_nothing(tmp_path):
    old = make_pob(tmp_path / "pob")
    before = snapshot(old)
    with pytest.raises(UpdateError, match="does not match GitHub's SHA-256.*old folder is unchanged"):
        pu.update(old, FakeHttp(digest="sha256:" + "0" * 64))
    assert_nothing_left(tmp_path, old, before)


def test_existing_target_stops_before_any_download(tmp_path):
    old = make_pob(tmp_path / "pob")
    (tmp_path / "PathOfBuildingCommunity-PoE2-Portable-0.23.1").mkdir()
    http = FakeHttp()
    with pytest.raises(UpdateError, match="already exists"):
        pu.update(old, http)
    assert http.calls == [pu.POB_RELEASE_URL]


def test_too_little_space_stops_before_any_download(tmp_path, monkeypatch):
    old = make_pob(tmp_path / "pob")
    monkeypatch.setattr(pu.shutil, "disk_usage", lambda _: type("U", (), {"free": 10})())
    http = FakeHttp()
    with pytest.raises(UpdateError, match="not enough free space"):
        pu.update(old, http)
    assert http.calls == [pu.POB_RELEASE_URL]


def test_failed_download_keeps_nothing(tmp_path):
    old = make_pob(tmp_path / "pob")
    before = snapshot(old)
    with pytest.raises(UpdateError, match=r"download failed \(ConnectionError\)"):
        pu.update(old, FakeHttp(fail_download=True))
    assert_nothing_left(tmp_path, old, before)


@pytest.mark.parametrize("member", ["../evil.txt", "/abs/evil.txt", "C:/evil.txt", "a/../../evil.txt",
                                    "..\\evil.txt", "C:evil.txt", "\\\\srv\\share\\evil.txt"])
def test_unsafe_archive_paths_are_refused(tmp_path, member):
    old = make_pob(tmp_path / "pob")
    before = snapshot(old)
    bad = zip_bytes({"manifest.xml": MANIFEST.format(v="0.23.1"), member: "x"})
    with pytest.raises(UpdateError, match="unsafe path"):
        pu.update(old, FakeHttp(pob_zip=bad))
    assert_nothing_left(tmp_path, old, before)
    assert not (tmp_path.parent / "evil.txt").exists()


def test_archive_that_unpacks_too_large_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(pu, "MAX_UNPACKED", 10)
    old = make_pob(tmp_path / "pob")
    with pytest.raises(UpdateError, match="unpacks past"):
        pu.update(old, FakeHttp())


def test_release_without_manifest_or_charm_without_exe(tmp_path):
    old = make_pob(tmp_path / "pob")
    with pytest.raises(UpdateError, match="has no manifest.xml"):
        pu.update(old, FakeHttp(pob_zip=zip_bytes({"readme.txt": "x"})))
    charm = make_charm(tmp_path / "charm")
    with pytest.raises(UpdateError, match="has no PoeCharm3.exe"):
        pu.update(charm, FakeHttp(charm_zip=zip_bytes({"top/readme.txt": "x"})))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["charm", "pob"]


# -- command line --------------------------------------------------------------------------------------------

def test_main_check_prints_json(tmp_path, capsys):
    folder = make_pob(tmp_path / "pob")
    assert pu.main(["--dir", str(folder), "--check"], http=FakeHttp()) == 0
    assert json.loads(capsys.readouterr().out)["latest"] == "0.23.1"


def test_main_errors_exit_1_with_json(tmp_path, capsys):
    assert pu.main(["--dir", str(tmp_path / "missing"), "--check"], http=FakeHttp()) == 1
    assert "is not a folder" in json.loads(capsys.readouterr().out)["error"]
    http = FakeHttp()
    http.get_json = lambda url: (_ for _ in ()).throw(requests.ConnectionError("down"))
    assert pu.main(["--dir", str(make_pob(tmp_path / "pob")), "--check"], http=http) == 1
    assert "could not be reached" in json.loads(capsys.readouterr().out)["error"]


# -- review follow-ups -------------------------------------------------------------------------------

def test_relative_folder_lands_next_to_it_not_inside(tmp_path, monkeypatch):
    old = make_pob(tmp_path / "pob")
    before = snapshot(old)
    monkeypatch.chdir(old)
    result = pu.update(Path("."), FakeHttp())
    assert result["new_folder"] == str(tmp_path / "PathOfBuildingCommunity-PoE2-Portable-0.23.1")
    assert snapshot(old) == before


def test_drive_root_and_the_pob_inside_poecharm_are_refused(tmp_path):
    with pytest.raises(UpdateError, match="drive root"):
        pu.find_install(Path("/"))
    charm = make_charm(tmp_path / "charm")
    with pytest.raises(UpdateError, match="give the PoeCharm2 folder instead"):
        pu.find_install(charm / pu.POB_DIR)


def test_a_new_pob_release_does_not_collide_with_the_folder_it_updates(tmp_path):
    old = make_charm(tmp_path / "PoeCharm2-20260728", "0.23.0")
    (old / pu.MARKER).write_text(json.dumps({"charm_sha": CHARM_SHA}), encoding="utf-8")
    result = pu.update(old, FakeHttp())
    assert result["new_folder"] == str(tmp_path / NEW_CHARM)


def test_update_when_current_with_unknown_poecharm_says_so(tmp_path):
    result = pu.update(make_charm(tmp_path / "charm", "0.23.1"), FakeHttp())
    assert result["updated"] is False and "PoeCharm2 version is unknown" in result["note"]


def test_download_larger_than_published_is_stopped(tmp_path):
    old = make_pob(tmp_path / "pob")
    before = snapshot(old)
    with pytest.raises(UpdateError, match="larger than expected"):
        pu.update(old, FakeHttp(size=len(POB_ZIP) - 1))
    assert_nothing_left(tmp_path, old, before)


@pytest.mark.parametrize("charm_zip", [b"not a zip at all", None])
def test_a_download_that_cannot_be_unpacked_keeps_nothing(tmp_path, charm_zip):
    if charm_zip is None:   # a real zip whose compressed data is damaged
        raw = bytearray(zip_bytes_deflated({"top/PoeCharm3.exe": "x" * 5000}))
        raw[60:80] = b"\x00" * 20
        charm_zip = bytes(raw)
    old = make_charm(tmp_path / "charm")
    before = snapshot(old)
    with pytest.raises(UpdateError, match="old folder is unchanged"):
        pu.update(old, FakeHttp(charm_zip=charm_zip))
    assert_nothing_left(tmp_path, old, before)


def test_failure_after_unpacking_keeps_nothing(tmp_path, monkeypatch):
    old = make_pob(tmp_path / "pob")
    before = snapshot(old)
    monkeypatch.setattr(pu, "_carry_over", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(UpdateError, match="OSError while writing the new folder"):
        pu.update(old, FakeHttp())
    assert_nothing_left(tmp_path, old, before)


def test_rename_retries_while_windows_holds_a_file(tmp_path, monkeypatch):
    monkeypatch.setattr(pu.time, "sleep", lambda _: None)
    real, tries = Path.rename, []

    def flaky(self, target):
        tries.append(1)
        if len(tries) < 3:
            raise PermissionError("in use")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", flaky)
    (tmp_path / "a").mkdir()
    pu._rename(tmp_path / "a", tmp_path / "b")
    assert (tmp_path / "b").is_dir() and len(tries) == 3
    monkeypatch.setattr(Path, "rename", lambda self, target: (_ for _ in ()).throw(PermissionError("in use")))
    with pytest.raises(PermissionError):
        pu._rename(tmp_path / "b", tmp_path / "c")


def test_old_work_folders_are_swept_and_fresh_ones_kept(tmp_path):
    old = make_pob(tmp_path / "pob", "0.23.1")
    stale, fresh = tmp_path / (pu.WORK_PREFIX + "old"), tmp_path / (pu.WORK_PREFIX + "new")
    stale.mkdir()
    fresh.mkdir()
    hour_ago = time.time() - pu.STALE_WORK_SECONDS - 10
    os.utime(stale, (hour_ago, hour_ago))
    result = pu.update(old, FakeHttp())
    assert result["stale_work_folders_removed"] == 1 and not stale.exists() and fresh.exists()


def test_progress_goes_to_stderr_and_the_result_to_stdout(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(pu, "PROGRESS_EVERY", 1)
    assert pu.main(["--dir", str(make_pob(tmp_path / "pob"))], http=FakeHttp()) == 0
    out = capsys.readouterr()
    assert json.loads(out.out)["updated"] is True
    assert "Path of Building: downloading" in out.err and "MB" in out.err


def zip_bytes_deflated(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


def test_a_path_with_dot_dot_still_lands_next_to_the_folder(tmp_path):
    old = make_charm(tmp_path / "charm")
    (old / "sub").mkdir()
    before = snapshot(old)
    result = pu.update(old / "sub" / "..", FakeHttp())
    assert result["new_folder"] == str(tmp_path / NEW_CHARM) and snapshot(old) == before


def test_a_parent_that_cannot_be_written_gives_a_json_error(tmp_path, capsys, monkeypatch):
    old = make_pob(tmp_path / "pob")
    monkeypatch.setattr(pu.tempfile, "mkdtemp", lambda **kw: (_ for _ in ()).throw(PermissionError("read-only")))
    assert pu.main(["--dir", str(old)], http=FakeHttp()) == 1
    error = json.loads(capsys.readouterr().out)["error"]
    assert "(PermissionError)" in error and "Nothing was changed" in error
