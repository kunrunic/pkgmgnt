import json
import tarfile
import os
import sys
import tempfile
import shlex
from importlib import import_module, reload
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

config = import_module("pkgmgr.config")
release = import_module("pkgmgr.release")
snapshot = import_module("pkgmgr.snapshot")
reload(config)
reload(release)
reload(snapshot)


def _setup_state_dir(monkeypatch, base_dir):
    state_dir = Path(base_dir) / "state"
    monkeypatch.setattr(config, "DEFAULT_STATE_DIR", str(state_dir))
    monkeypatch.setattr(snapshot, "STATE_DIR", str(state_dir))
    return state_dir


def _write_pkg_yaml(pkg_dir, pkg_id, include_releases):
    config.write_pkg_template(
        os.path.join(pkg_dir, "pkg.yaml"),
        pkg_id=pkg_id,
        pkg_root=pkg_dir,
        include_releases=include_releases,
        git_cfg={"keywords": []},
        collectors_enabled=["checksums"],
    )


def test_create_pkg_existing_dir_keeps_files_and_writes_pkg_yaml(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _setup_state_dir(monkeypatch, base)
        pkg_root = base / "pkgs"
        pkg_id = "20240101"
        pkg_dir = pkg_root / pkg_id
        pkg_dir.mkdir(parents=True)
        keep_file = pkg_dir / "keep.txt"
        keep_file.write_text("keep")

        cfg = {"pkg_release_root": str(pkg_root)}
        release.create_pkg(cfg, pkg_id)

        assert keep_file.exists()
        assert keep_file.read_text() == "keep"
        assert (pkg_dir / "pkg.yaml").exists()


def test_create_pkg_missing_dir_creates_dir_and_pkg_yaml(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _setup_state_dir(monkeypatch, base)
        pkg_root = base / "pkgs"
        pkg_id = "20240102"
        pkg_dir = pkg_root / pkg_id

        cfg = {"pkg_release_root": str(pkg_root)}
        release.create_pkg(cfg, pkg_id)

        assert pkg_dir.exists()
        assert (pkg_dir / "pkg.yaml").exists()


def test_update_pkg_first_release_includes_all_files(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _setup_state_dir(monkeypatch, base)
        pkg_root = base / "pkgs"
        pkg_id = "20240103"
        pkg_dir = pkg_root / pkg_id
        pkg_dir.mkdir(parents=True)

        src_dir = pkg_dir / "src"
        src_dir.mkdir()
        (src_dir / "a.txt").write_text("alpha")
        (src_dir / "b.txt").write_text("bravo")

        _write_pkg_yaml(str(pkg_dir), pkg_id, ["src"])
        cfg = {"pkg_release_root": str(pkg_root)}

        out_path = release.update_pkg(cfg, pkg_id)
        data = json.loads(Path(out_path).read_text())

        bundles = data["release"]
        assert len(bundles) == 1
        bundle = bundles[0]
        assert set(bundle["copied"]) == {"a.txt", "b.txt"}
        release_dir = Path(bundle["release_dir"])
        assert (release_dir / "a.txt").exists()
        assert (release_dir / "b.txt").exists()


def test_update_pkg_skips_release_when_no_changes(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _setup_state_dir(monkeypatch, base)
        pkg_root = base / "pkgs"
        pkg_id = "20240104"
        pkg_dir = pkg_root / pkg_id
        pkg_dir.mkdir(parents=True)

        src_dir = pkg_dir / "src"
        src_dir.mkdir()
        (src_dir / "a.txt").write_text("alpha")

        _write_pkg_yaml(str(pkg_dir), pkg_id, ["src"])
        cfg = {"pkg_release_root": str(pkg_root)}

        release.update_pkg(cfg, pkg_id)
        out_path = release.update_pkg(cfg, pkg_id)
        data = json.loads(Path(out_path).read_text())

        assert data["release"] == []
        release_root = pkg_dir / "release" / "src"
        versions = sorted(p.name for p in release_root.iterdir() if p.is_dir())
        assert versions == ["release.v0.0.1"]


def test_update_pkg_includes_new_and_modified_files(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _setup_state_dir(monkeypatch, base)
        pkg_root = base / "pkgs"
        pkg_id = "20240105"
        pkg_dir = pkg_root / pkg_id
        pkg_dir.mkdir(parents=True)

        src_dir = pkg_dir / "src"
        src_dir.mkdir()
        (src_dir / "a.txt").write_text("alpha")
        (src_dir / "b.txt").write_text("bravo")

        _write_pkg_yaml(str(pkg_dir), pkg_id, ["src"])
        cfg = {"pkg_release_root": str(pkg_root)}

        release.update_pkg(cfg, pkg_id)

        (src_dir / "a.txt").write_text("alpha2")
        (src_dir / "c.txt").write_text("charlie")

        out_path = release.update_pkg(cfg, pkg_id)
        data = json.loads(Path(out_path).read_text())

        bundles = data["release"]
        assert len(bundles) == 1
        bundle = bundles[0]
        assert set(bundle["copied"]) == {"a.txt", "c.txt"}
        assert bundle["skipped"] == []
        release_dir = Path(bundle["release_dir"])
        assert (release_dir / "a.txt").exists()
        assert (release_dir / "c.txt").exists()
        assert (release_dir / "b.txt").exists()


def test_update_pkg_reuse_active_keeps_unchanged_files(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _setup_state_dir(monkeypatch, base)
        pkg_root = base / "pkgs"
        pkg_id = "20240110"
        pkg_dir = pkg_root / pkg_id
        pkg_dir.mkdir(parents=True)

        src_dir = pkg_dir / "src"
        src_dir.mkdir()
        (src_dir / "a.txt").write_text("alpha")
        (src_dir / "b.txt").write_text("bravo")

        _write_pkg_yaml(str(pkg_dir), pkg_id, ["src"])
        cfg = {"pkg_release_root": str(pkg_root)}

        release.update_pkg(cfg, pkg_id)

        (src_dir / "a.txt").write_text("alpha2")
        (src_dir / "c.txt").write_text("charlie")
        release.update_pkg(cfg, pkg_id)

        release_root = pkg_dir / "release" / "src"
        release_dir = release_root / "release.v0.0.1"
        assert (release_dir / "a.txt").exists()
        assert (release_dir / "b.txt").exists()
        assert (release_dir / "c.txt").exists()

        out_path = release.update_pkg(cfg, pkg_id)
        data = json.loads(Path(out_path).read_text())
        assert data["release"] == []
        assert (release_dir / "a.txt").exists()
        assert (release_dir / "b.txt").exists()
        assert (release_dir / "c.txt").exists()


def test_update_pkg_remove_only_keeps_other_files(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _setup_state_dir(monkeypatch, base)
        pkg_root = base / "pkgs"
        pkg_id = "20240111"
        pkg_dir = pkg_root / pkg_id
        pkg_dir.mkdir(parents=True)

        src_dir = pkg_dir / "src"
        src_dir.mkdir()
        (src_dir / "a.txt").write_text("alpha")
        (src_dir / "b.txt").write_text("bravo")
        (src_dir / "c.txt").write_text("charlie")

        _write_pkg_yaml(str(pkg_dir), pkg_id, ["src"])
        cfg = {"pkg_release_root": str(pkg_root)}

        release.update_pkg(cfg, pkg_id)


def test_run_actions_exports_pkgmgr_config_env(tmp_path):
    capture_path = tmp_path / "capture.txt"
    code = (
        "import os, pathlib; "
        "pathlib.Path(r'%s').write_text(os.getenv('PKGMGR_CONFIG', ''))"
        % capture_path
    )
    cmd = "%s -c %s" % (sys.executable, shlex.quote(code))
    cfg = {"actions": {"capture": [{"cmd": cmd}]}}

    release.run_actions(cfg, ["capture"], config_path="/tmp/pkgmgr.yaml")

    assert capture_path.read_text() == "/tmp/pkgmgr.yaml"

        (src_dir / "b.txt").unlink()
        out_path = release.update_pkg(cfg, pkg_id)
        data = json.loads(Path(out_path).read_text())

        assert len(data["release"]) == 1
        bundle = data["release"][0]
        assert bundle["copied"] == []
        assert bundle["updated"] == []
        assert bundle["removed"] == ["b.txt"]

        release_root = pkg_dir / "release" / "src"
        release_dir = release_root / "release.v0.0.1"
        assert (release_dir / "a.txt").exists()
        assert not (release_dir / "b.txt").exists()
        assert (release_dir / "c.txt").exists()


def test_update_pkg_remove_only_then_no_changes(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _setup_state_dir(monkeypatch, base)
        pkg_root = base / "pkgs"
        pkg_id = "20240112"
        pkg_dir = pkg_root / pkg_id
        pkg_dir.mkdir(parents=True)

        src_dir = pkg_dir / "src"
        src_dir.mkdir()
        (src_dir / "a.txt").write_text("alpha")
        (src_dir / "b.txt").write_text("bravo")

        _write_pkg_yaml(str(pkg_dir), pkg_id, ["src"])
        cfg = {"pkg_release_root": str(pkg_root)}

        release.update_pkg(cfg, pkg_id)

        (src_dir / "b.txt").unlink()
        release.update_pkg(cfg, pkg_id)

        out_path = release.update_pkg(cfg, pkg_id)
        data = json.loads(Path(out_path).read_text())
        assert data["release"] == []

        release_root = pkg_dir / "release" / "src"
        release_dir = release_root / "release.v0.0.1"
        assert (release_dir / "a.txt").exists()
        assert not (release_dir / "b.txt").exists()

def test_update_pkg_writes_note_once_and_updates_list(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _setup_state_dir(monkeypatch, base)
        pkg_root = base / "pkgs"
        pkg_id = "20240106"
        pkg_dir = pkg_root / pkg_id
        pkg_dir.mkdir(parents=True)

        src_dir = pkg_dir / "src"
        src_dir.mkdir()
        (src_dir / "a.txt").write_text("alpha")

        _write_pkg_yaml(str(pkg_dir), pkg_id, ["src"])
        cfg = {"pkg_release_root": str(pkg_root)}

        release.update_pkg(cfg, pkg_id)

        release_root = pkg_dir / "release" / "src"
        release_dir = release_root / "release.v0.0.1"
        note_path = release_dir / "PKG_NOTE"
        list_path = release_dir / "PKG_LIST"
        assert note_path.exists()
        assert list_path.exists()

        note_path.write_text("user note")
        (src_dir / "b.txt").write_text("bravo")

        release.update_pkg(cfg, pkg_id)

        assert note_path.read_text() == "user note"
        list_text = list_path.read_text()
        assert "b.txt" in list_text


def test_update_pkg_reuses_active_release_version(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _setup_state_dir(monkeypatch, base)
        pkg_root = base / "pkgs"
        pkg_id = "20240108"
        pkg_dir = pkg_root / pkg_id
        pkg_dir.mkdir(parents=True)

        src_dir = pkg_dir / "src"
        src_dir.mkdir()
        (src_dir / "a.txt").write_text("alpha")

        _write_pkg_yaml(str(pkg_dir), pkg_id, ["src"])
        cfg = {"pkg_release_root": str(pkg_root)}

        release.update_pkg(cfg, pkg_id)

        (src_dir / "a.txt").write_text("alpha2")
        out_path = release.update_pkg(cfg, pkg_id)
        data = json.loads(Path(out_path).read_text())
        release_dir = Path(data["release"][0]["release_dir"])
        assert release_dir.name == "release.v0.0.1"
        release_root = pkg_dir / "release" / "src"
        versions = sorted(p.name for p in release_root.iterdir() if p.is_dir())
        assert versions == ["release.v0.0.1"]


def test_update_pkg_removes_deleted_files(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _setup_state_dir(monkeypatch, base)
        pkg_root = base / "pkgs"
        pkg_id = "20240109"
        pkg_dir = pkg_root / pkg_id
        pkg_dir.mkdir(parents=True)

        src_dir = pkg_dir / "src"
        src_dir.mkdir()
        (src_dir / "a.txt").write_text("alpha")
        (src_dir / "b.txt").write_text("bravo")

        _write_pkg_yaml(str(pkg_dir), pkg_id, ["src"])
        cfg = {"pkg_release_root": str(pkg_root)}

        release.update_pkg(cfg, pkg_id)

        (src_dir / "b.txt").unlink()
        release.update_pkg(cfg, pkg_id)

        release_root = pkg_dir / "release" / "src"
        release_dir = release_root / "release.v0.0.1"
        assert not (release_dir / "b.txt").exists()
        assert (release_dir / "a.txt").exists()


def test_update_pkg_release_finalizes_and_advances_version(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _setup_state_dir(monkeypatch, base)
        pkg_root = base / "pkgs"
        pkg_id = "20240107"
        pkg_dir = pkg_root / pkg_id
        pkg_dir.mkdir(parents=True)

        src_dir = pkg_dir / "src"
        src_dir.mkdir()
        (src_dir / "a.txt").write_text("alpha")

        _write_pkg_yaml(str(pkg_dir), pkg_id, ["src"])
        cfg = {"pkg_release_root": str(pkg_root)}

        release.update_pkg(cfg, pkg_id)

        release_root = pkg_dir / "release" / "src"
        v001_dir = release_root / "release.v0.0.1"
        assert v001_dir.exists()

        release.finalize_pkg_release(cfg, pkg_id)

        history_dir = release_root / "HISTORY" / "release.v0.0.1"
        tar_path = release_root / "release.v0.0.1.tar"
        assert history_dir.exists()
        assert tar_path.exists()
        assert not v001_dir.exists()
        assert (history_dir / "PKG_NOTE").exists()
        assert (history_dir / "PKG_LIST").exists()
        assert (release_root / "HISTORY" / "BASELINE").exists()
        with tarfile.open(tar_path, "r") as tar:
            names = tar.getnames()
        assert "release.v0.0.1/PKG_NOTE" in names
        assert "release.v0.0.1/PKG_LIST" in names

        (src_dir / "b.txt").write_text("bravo")
        out_path = release.update_pkg(cfg, pkg_id)
        data = json.loads(Path(out_path).read_text())
        release_dir = Path(data["release"][0]["release_dir"])
        assert release_dir.name == "release.v0.0.2"
