import sys
import tempfile
from importlib import import_module, reload
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

snapshot = import_module("pkgmgr.snapshot")
reload(snapshot)


def test_create_baseline_raises_on_duplicate_install_non_tty(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp)
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "baseline.json").write_text("{}")

        monkeypatch.setattr(snapshot, "STATE_DIR", str(state_dir))
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

        try:
            snapshot.create_baseline({"sources": []}, prompt_overwrite=True)
        except snapshot.DuplicateBaselineError as e:
            assert "existing baseline" in str(e)
        else:
            raise AssertionError("Expected DuplicateBaselineError for duplicate install")
