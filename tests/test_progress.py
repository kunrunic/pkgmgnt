import sys
from importlib import import_module, reload

snapshot = import_module("pkgmgr.snapshot")
reload(snapshot)


def test_progress_reporter_tty_outputs_single_line(capsys, monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    reporter = snapshot.ProgressReporter("scan")

    reporter.start("source /tmp", 3)
    reporter.advance()
    reporter.advance()
    reporter.finish()

    out = capsys.readouterr().out
    assert "\r[scan]" in out
    assert "source /tmp" in out
    assert out.endswith("\n")


def test_progress_reporter_non_tty_is_silent(capsys, monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    reporter = snapshot.ProgressReporter("scan")

    reporter.start("source /tmp", 3)
    reporter.advance()
    reporter.finish()

    out = capsys.readouterr().out
    assert out == ""
