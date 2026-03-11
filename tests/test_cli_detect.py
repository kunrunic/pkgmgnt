import os
import sys
import tempfile
from importlib import import_module, reload
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

cli = import_module("pkgmgr.cli")
reload(cli)


def test_handle_detect_saves_report_and_backup_on_change(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "detect.txt"
        cfg = {
            "detection": {
                "enabled": True,
                "report_file": str(report),
                "fail_on": [],
                "warn_on": [],
                "ignore": [],
            }
        }
        outputs = ["run1\n", "run2\n"]

        def _fake_run(_cfg):
            print(outputs.pop(0), end="")
            return {"exit_code": 0}

        monkeypatch.setattr(cli.config, "load_main", lambda *_a, **_k: cfg)
        monkeypatch.setattr(cli.detection, "run", _fake_run)

        rc1 = cli._handle_detect(SimpleNamespace(config=None))
        assert rc1 == 0
        assert report.read_text() == "run1\n"
        backups = sorted(report.parent.glob("detect.txt.bak_*"))
        assert len(backups) == 0

        rc2 = cli._handle_detect(SimpleNamespace(config=None))
        assert rc2 == 0
        assert report.read_text() == "run2\n"
        backups = sorted(report.parent.glob("detect.txt.bak_*"))
        assert len(backups) == 1
        assert backups[0].read_text() == "run1\n"


def test_handle_detect_skips_backup_when_same_content(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "detect.txt"
        cfg = {
            "detection": {
                "enabled": True,
                "report_file": str(report),
                "fail_on": [],
                "warn_on": [],
                "ignore": [],
            }
        }

        def _fake_run(_cfg):
            print("same\n", end="")
            return {"exit_code": 0}

        monkeypatch.setattr(cli.config, "load_main", lambda *_a, **_k: cfg)
        monkeypatch.setattr(cli.detection, "run", _fake_run)

        rc1 = cli._handle_detect(SimpleNamespace(config=None))
        rc2 = cli._handle_detect(SimpleNamespace(config=None))
        assert rc1 == 0 and rc2 == 0
        backups = sorted(report.parent.glob("detect.txt.bak_*"))
        assert len(backups) == 0
        assert report.read_text() == "same\n"
