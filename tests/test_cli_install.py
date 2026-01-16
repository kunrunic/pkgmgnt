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
config = import_module("pkgmgr.config")
release = import_module("pkgmgr.release")
snapshot = import_module("pkgmgr.snapshot")
reload(cli)
reload(config)
reload(release)
reload(snapshot)


def _setup_paths(monkeypatch, base):
    monkeypatch.setattr(config, "BASE_DIR", str(base))
    state_dir = os.path.join(str(base), "local", "state")
    monkeypatch.setattr(config, "DEFAULT_STATE_DIR", state_dir)
    monkeypatch.setattr(snapshot, "STATE_DIR", state_dir)
    return state_dir


def test_install_aborts_when_readme_exists(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _setup_paths(monkeypatch, base)
        readme = base / "README.txt"
        readme.write_text("existing")

        calls = {"env": 0, "baseline": 0}
        monkeypatch.setattr(config, "load_main", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(release, "ensure_environment", lambda: calls.__setitem__("env", 1))
        monkeypatch.setattr(snapshot, "create_baseline", lambda *_a, **_k: calls.__setitem__("baseline", 1))

        rc = cli._handle_install(SimpleNamespace(config=None))

        assert rc == 1
        assert calls["env"] == 0
        assert calls["baseline"] == 0


def test_install_aborts_when_baseline_exists(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        state_dir = _setup_paths(monkeypatch, base)
        Path(state_dir).mkdir(parents=True, exist_ok=True)
        baseline = Path(state_dir) / "baseline.json"
        baseline.write_text("{}")

        calls = {"env": 0, "baseline": 0}
        monkeypatch.setattr(config, "load_main", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(release, "ensure_environment", lambda: calls.__setitem__("env", 1))
        monkeypatch.setattr(snapshot, "create_baseline", lambda *_a, **_k: calls.__setitem__("baseline", 1))

        rc = cli._handle_install(SimpleNamespace(config=None))

        assert rc == 1
        assert calls["env"] == 0
        assert calls["baseline"] == 0
