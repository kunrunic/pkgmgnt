import os
import sys
import tempfile
from importlib import import_module, reload
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Ensure we load the in-repo module even if an older pkg is installed.
config = import_module("pkgmgr.config")
reload(config)


def test_discover_main_configs_supports_base_and_legacy():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        legacy_dir = base / "config"
        legacy_dir.mkdir()
        main1 = base / "pkgmgr.yaml"
        main2 = legacy_dir / "pkgmgr-alt.yml"
        main1.write_text("a: 1\n")
        main2.write_text("b: 2\n")

        found = config.discover_main_configs(base_dir=base)

        assert set(found) == {str(main1.resolve()), str(main2.resolve())}


def test_resolve_main_config_uses_single_found():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        cfg = base / "pkgmgr.yaml"
        cfg.write_text("foo: bar\n")

        resolved = config.resolve_main_config(base_dir=base, allow_interactive=False)

        # normalize to realpath to avoid /var vs /private/var differences
        assert resolved == os.path.realpath(str(cfg.resolve()))


def test_resolve_main_config_raises_on_multiple_without_interactive():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / "pkgmgr.yaml").write_text("a: 1\n")
        (base / "pkgmgr-alt.yaml").write_text("b: 2\n")

        try:
            config.resolve_main_config(base_dir=base, allow_interactive=False)
        except RuntimeError as e:
            assert "multiple pkgmgr configs found" in str(e)
        else:
            raise AssertionError("Expected RuntimeError for multiple configs")


def test_load_main_reads_yaml():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "pkgmgr.yaml"
        cfg_path.write_text("pkg_release_root: /tmp/release\nsources: []\n")

        data = config.load_main(path=cfg_path, allow_interactive=False)

        assert data["pkg_release_root"] == "/tmp/release"


def test_write_template_respects_overridden_default_path(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "pkgmgr.yaml"
        monkeypatch.setattr(config, "DEFAULT_MAIN_CONFIG", str(target))

        config.write_template()

        assert target.exists()
        content = target.read_text()
    assert "pkg_release_root" in content


def test_write_template_skips_when_existing(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "pkgmgr.yaml"
        target.write_text("keep: true\n")
        monkeypatch.setattr(config, "DEFAULT_MAIN_CONFIG", str(target))

        wrote = config.write_template()

        assert wrote is False
        assert target.read_text() == "keep: true\n"


def test_load_main_applies_defaults_and_validation():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "pkgmgr.yaml"
        cfg_path.write_text(
            "\n".join(
                [
                    "pkg_release_root: /tmp/release",
                    "sources: /src/main",
                    "watch:",
                    "  interval_sec: -5",
                ]
            )
            + "\n"
        )

        data = config.load_main(path=cfg_path, allow_interactive=False)

        assert data["sources"] == ["/src/main"]
        assert data["watch"]["interval_sec"] == 60  # reset to default on invalid
        assert data["collectors"]["enabled"] == ["checksums"]
        assert data["actions"] == {}


def test_load_main_requires_pkg_release_root():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "pkgmgr.yaml"
        cfg_path.write_text("sources: []\n")

        try:
            config.load_main(path=cfg_path, allow_interactive=False)
        except RuntimeError as e:
            assert "pkg_release_root" in str(e)
        else:
            raise AssertionError("expected validation error for missing pkg_release_root")
