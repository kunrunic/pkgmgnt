import sys
from importlib import import_module, reload
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

cli = import_module("pkgmgr.cli")
reload(cli)


def test_handle_telegram_poll_calls_watch(monkeypatch):
    cfg = {"watch": {"telegram": {"enabled": True}}}
    called = {}
    monkeypatch.setattr(cli.config, "load_main", lambda *_a, **_k: cfg)
    monkeypatch.setattr(
        cli.watch,
        "telegram_poll",
        lambda _cfg, run_once=False: called.update({"run_once": run_once}) or 0,
    )
    rc = cli._handle_telegram_poll(SimpleNamespace(config=None, once=True))
    assert rc == 0
    assert called["run_once"] is True


def test_handle_telegram_approve_calls_watch(monkeypatch):
    cfg = {"watch": {"telegram": {"enabled": True}}}
    called = {}
    monkeypatch.setattr(cli.config, "load_main", lambda *_a, **_k: cfg)
    monkeypatch.setattr(
        cli.watch,
        "telegram_approve",
        lambda _cfg, chat_id: called.update({"chat_id": chat_id}) or 0,
    )
    rc = cli._handle_telegram_approve(SimpleNamespace(config=None, chat_id="123"))
    assert rc == 0
    assert called["chat_id"] == "123"
