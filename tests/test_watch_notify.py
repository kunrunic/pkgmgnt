import sys
from importlib import import_module, reload
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

watch = import_module("pkgmgr.watch")
reload(watch)


def test_should_notify_rules():
    diff = {"added": ["a"], "modified": [], "deleted": []}
    detect_result = {"fail_count": 1, "warn_count": 0}
    cfg = {"notify_on": ["fail"]}
    assert watch._should_notify(cfg, diff, detect_result) is True
    cfg = {"notify_on": ["warn"]}
    assert watch._should_notify(cfg, diff, detect_result) is False
    cfg = {"notify_on": ["changes"]}
    assert watch._should_notify(cfg, diff, detect_result) is True


def test_maybe_notify_telegram_dedup(monkeypatch):
    sent = {"count": 0}
    def _fake_send(*_a, **_k):
        sent["count"] += 1
        return True, ""
    monkeypatch.setattr(watch, "_send_telegram", _fake_send)
    monkeypatch.setattr(watch, "_watch_last_hash_path", lambda pkg_id=None: "/tmp/pkgmgr-watch-dedup-test.sha256")
    monkeypatch.setattr(watch, "_load_last_hash", lambda _p: "same")
    monkeypatch.setattr(watch, "_save_last_hash", lambda _p, _v: sent.__setitem__("saved", True))
    monkeypatch.setattr(watch.hashlib, "sha256", lambda _b: type("H", (), {"hexdigest": lambda self: "same"})())
    cfg = {
        "watch": {
            "telegram": {
                "enabled": True,
                "bot_token": "t",
                "chat_id": "c",
                "notify_on": ["all"],
                "dedup": True,
                "message_prefix": "[pkgmgr]",
            }
        }
    }
    watch._maybe_notify_telegram(cfg, diff={"added": ["x"], "modified": [], "deleted": []}, detect_result=None, pkg_id=None)
    assert sent["count"] == 0


def test_notify_lifecycle_event(monkeypatch):
    sent = {"count": 0}

    def _fake_send(*_a, **_k):
        sent["count"] += 1
        return True

    monkeypatch.setattr(watch, "_send_channel_notification", _fake_send)
    cfg = {
        "watch": {
            "telegram": {
                "enabled": True,
                "bot_token": "t",
                "chat_id": "c",
                "chat_ids": ["c2"],
                "channels": {
                    "lifecycle": {"enabled": True, "events": ["create_pkg", "close_pkg"]},
                },
            }
        }
    }
    assert watch.notify_lifecycle_event(cfg, "create_pkg", pkg_id="R1") is True
    assert watch.notify_lifecycle_event(cfg, "update_pkg", pkg_id="R1") is False
    assert sent["count"] == 1


def test_format_pkg_event_message_uses_pkg_header():
    text = watch._format_pkg_event_message("[pkgmgr]", "create_pkg", "R10000", {"user": "tester"})
    assert text.startswith("[pkgmgr] [PKG] ")
    assert "pkg 변경 이력이 발생했습니다." in text
    assert "event=create_pkg" in text
    assert "pkg=R10000" in text
    assert "user=tester" in text


def test_maybe_notify_git_commit(monkeypatch):
    calls = {"sent": 0, "saved": []}
    state = {}

    monkeypatch.setattr(watch, "_send_channel_notification", lambda *_a, **_k: calls.__setitem__("sent", calls["sent"] + 1) or True)
    monkeypatch.setattr(
        watch,
        "_channel_cfg",
        lambda _cfg, ch: {"enabled": True, "repo_root": "/repo", "branches": ["main"]} if ch == "git" else {"enabled": False},
    )
    monkeypatch.setattr(watch, "_watch_state_json_path", lambda c, k: "/tmp/%s-%s.json" % (c, k.replace("/", "_")))
    monkeypatch.setattr(watch, "_load_state_json", lambda p: state.get(p, {}))
    monkeypatch.setattr(watch, "_save_state_json", lambda p, v: (state.__setitem__(p, v), calls["saved"].append(v)))

    seq = [
        {"sha": "a1", "author": "u", "date": "d", "subject": "s1"},
        {"sha": "a2", "author": "u", "date": "d", "subject": "s2"},
    ]
    monkeypatch.setattr(watch, "_git_current_head", lambda *_a, **_k: seq.pop(0))
    cfg = {"watch": {"telegram": {"enabled": True, "bot_token": "t", "chat_id": "c", "chat_ids": ["c2"]}}}

    watch._maybe_notify_git_commit(cfg)
    watch._maybe_notify_git_commit(cfg)
    assert calls["sent"] == 1


def test_maybe_notify_file_watch(monkeypatch, tmp_path):
    sent = {"count": 0}
    monkeypatch.setattr(watch, "_send_channel_notification", lambda *_a, **_k: sent.__setitem__("count", sent["count"] + 1) or True)
    state = {}
    monkeypatch.setattr(watch, "_watch_state_json_path", lambda c, k: "/tmp/%s-%s.json" % (c, str(hash(k))))
    monkeypatch.setattr(watch, "_load_state_json", lambda p: state.get(p, {}))
    monkeypatch.setattr(watch, "_save_state_json", lambda p, v: state.__setitem__(p, v))
    monkeypatch.setattr(
        watch,
        "_channel_cfg",
        lambda _cfg, ch: {"enabled": True, "files": [{"path": str(tmp_path / "a.txt"), "encoding": "utf-8"}], "max_chars": 1000}
        if ch == "file_watch"
        else {"enabled": False},
    )
    f = tmp_path / "a.txt"
    f.write_text("hello")
    cfg = {"watch": {"telegram": {"enabled": True, "bot_token": "t", "chat_id": "c", "chat_ids": ["c2"]}}}
    watch._maybe_notify_file_watch(cfg)
    watch._maybe_notify_file_watch(cfg)
    f.write_text("hello2")
    watch._maybe_notify_file_watch(cfg)
    assert sent["count"] == 2


def test_maybe_notify_jenkins_first_seen(monkeypatch):
    sent = {"count": 0}
    state = {}
    monkeypatch.setattr(
        watch,
        "_channel_cfg",
        lambda _cfg, ch: (
            {
                "enabled": True,
                "notify_on_first_seen": True,
                "jobs": [{"name": "job1", "url": "http://jenkins/job1"}],
            }
            if ch == "jenkins"
            else {"enabled": False}
        ),
    )
    monkeypatch.setattr(
        watch,
        "_jenkins_build_info",
        lambda _job: {
            "name": "job1",
            "number": 10,
            "building": False,
            "result": "SUCCESS",
            "timestamp": 0,
            "url": "http://jenkins/job1/10",
        },
    )
    monkeypatch.setattr(watch, "_watch_state_json_path", lambda c, k: "/tmp/%s-%s.json" % (c, k))
    monkeypatch.setattr(watch, "_load_state_json", lambda p: state.get(p, {}))
    monkeypatch.setattr(watch, "_save_state_json", lambda p, v: state.__setitem__(p, v))
    monkeypatch.setattr(
        watch,
        "_send_channel_notification",
        lambda *_a, **_k: sent.__setitem__("count", sent["count"] + 1) or True,
    )
    cfg = {"watch": {"telegram": {"enabled": True, "bot_token": "t", "chat_id": "c"}}}
    watch._maybe_notify_jenkins(cfg)
    assert sent["count"] == 1


def test_format_jenkins_message_includes_title_and_desc():
    text = watch._format_jenkins_message(
        "[pkgmgr]",
        {
            "name": "sktin_pipelinescript",
            "display_name": "Build MVNO BAND PPS 서비스",
            "description": "R680 PKG 대상 테스트",
            "number": 260,
            "building": False,
            "result": "SUCCESS",
            "url": "http://192.168.1.74:9090/job/sktin_pipelinescript/260/",
        },
    )
    assert text.startswith("[pkgmgr] [JENKINS] ")
    assert "실행 이력이 발생했습니다." in text
    assert "Build MVNO BAND PPS 서비스" in text
    assert "R680 PKG 대상 테스트" in text
    assert "job=sktin_pipelinescript" in text
    assert "url=http://192.168.1.74:9090/job/sktin_pipelinescript/260/" in text


def test_format_telegram_message_uses_detect_message_file(tmp_path):
    msg = tmp_path / "detect_message.txt"
    msg.write_text("[detection] custom message\\nline2\\n")
    cfg = {
        "watch": {
            "telegram": {
                "message_prefix": "[pkgmgr]",
                "channels": {"detect": {"enabled": True, "message_file": str(msg)}},
            }
        }
    }
    text = watch._format_telegram_message(
        cfg,
        diff={"added": ["a"], "modified": [], "deleted": []},
        detect_result={"exit_code": 2, "fail_count": 1, "warn_count": 1, "by_reason": {"X": 1}},
        pkg_id=None,
    )
    assert text.startswith("[detection] custom message")


def test_format_telegram_message_truncates_detect_message_file(tmp_path):
    msg = tmp_path / "detect_message_big.txt"
    msg.write_text("A" * 120)
    cfg = {
        "watch": {
            "telegram": {
                "channels": {"detect": {"enabled": True, "message_file": str(msg), "max_chars": 50}},
            }
        }
    }
    text = watch._format_telegram_message(cfg, diff=None, detect_result=None, pkg_id=None)
    assert len(text) > 50
    assert "...(omitted " in text


def test_wrap_for_telegram_wraps_long_line():
    long_line = "reason: " + ("UNTRACKED_NOT_IN_PKG=1108, " * 8)
    out = watch._wrap_for_telegram(long_line, width=40)
    lines = out.splitlines()
    assert len(lines) >= 2
    assert all(len(line) <= 42 for line in lines)


def test_format_telegram_message_summary_contains_system_and_run_at():
    cfg = {
        "watch": {"telegram": {"message_prefix": "[pkgmgr]"}},
        "detection": {"system": "OCS2_DEV01"},
    }
    detect_result = {
        "run_at": "2026-03-09 14:00:00 KST",
        "system": "OCS2_DEV01",
        "exit_code": 2,
        "fail_count": 3,
        "warn_count": 1,
        "by_reason": {"UNTRACKED_NOT_IN_PKG": 3},
    }
    text = watch._format_telegram_message(cfg, diff=None, detect_result=detect_result, pkg_id=None)
    assert "[DETECT][SUMMARY]" in text
    assert "system=OCS2_DEV01" in text
    assert "run_at=2026-03-09 14:00:00 KST" in text
    assert "by_reason: UNTRACKED_NOT_IN_PKG=3" in text


def test_format_telegram_message_extracts_detection_sections_from_file(tmp_path):
    body = "\n".join(
        [
            "[detection] summary",
            "  run_at: 2026-03-09 17:32:35 KST",
            "  fail: 3",
            "",
            "[detection] managed_by_reason",
            "  CHANGED_NOT_UPDATED: 1",
            "",
            "[detection] managed_view",
            "  pkg=R1",
            "",
            "[detection] by_reason",
            "  CHANGED_NOT_UPDATED: 1",
            "",
            "[detection] git_by_reason",
            "  GIT_UNTRACKED: 2",
        ]
    )
    msg = tmp_path / "detect_message_sections.txt"
    msg.write_text(body)
    cfg = {
        "watch": {
            "telegram": {
                "message_prefix": "[pkgmgr]",
                "channels": {
                    "detect": {
                        "enabled": True,
                        "message_file": str(msg),
                        "message_file_max_lines": 50,
                        "max_chars": 3800,
                        "wrap_width": 120,
                    }
                },
            }
        }
    }
    detect_result = {"run_at": "2026-03-09 17:32:35 KST", "fail_count": 1, "warn_count": 0}
    text = watch._format_telegram_message(cfg, diff=None, detect_result=detect_result, pkg_id=None)
    assert text.startswith("[pkgmgr] [DETECT] 2026-03-09 17:32:35 KST")
    assert "확인 필요 사항이 발생하여 알려드립니다." in text
    assert "[detection] summary" in text
    assert "[detection] managed_by_reason" in text
    assert "[detection] by_reason" in text
    assert "[detection] git_by_reason" in text
    assert "[detection] managed_view" not in text


def test_telegram_chat_ids_merges_single_and_list():
    cfg = {
        "watch": {"telegram": {"enabled": True, "bot_token": "t", "chat_id": "c1", "chat_ids": ["c2", "c1"]}}
    }
    ids = watch._telegram_chat_ids(cfg)
    assert ids == ["c2", "c1"]


def test_maybe_notify_telegram_sends_to_multiple_chat_ids(monkeypatch):
    sent = []

    def _fake_send(_token, chat_id, _text):
        sent.append(chat_id)
        return True, ""

    monkeypatch.setattr(watch, "_send_telegram", _fake_send)
    monkeypatch.setattr(watch, "_watch_last_hash_path", lambda pkg_id=None: "/tmp/pkgmgr-watch-multi-test.sha256")
    monkeypatch.setattr(watch, "_load_last_hash", lambda _p: "")
    monkeypatch.setattr(watch, "_save_last_hash", lambda _p, _v: None)
    cfg = {
        "watch": {
            "telegram": {
                "enabled": True,
                "bot_token": "t",
                "chat_id": "c1",
                "chat_ids": ["c2"],
                "notify_on": ["all"],
                "dedup": False,
                "message_prefix": "[pkgmgr]",
            }
        }
    }
    watch._maybe_notify_telegram(cfg, diff={"added": ["x"], "modified": [], "deleted": []}, detect_result=None, pkg_id=None)
    assert sorted(sent) == ["c1", "c2"]


def test_maybe_notify_telegram_dedup_ignores_detect_run_at(monkeypatch):
    sent = {"count": 0}
    state = {"hash": ""}

    def _fake_send(_token, _chat_id, _text):
        sent["count"] += 1
        return True, ""

    monkeypatch.setattr(watch, "_send_telegram", _fake_send)
    monkeypatch.setattr(watch, "_watch_last_hash_path", lambda pkg_id=None: "/tmp/pkgmgr-watch-detect-dedup.sha256")
    monkeypatch.setattr(watch, "_load_last_hash", lambda _p: state["hash"])
    monkeypatch.setattr(watch, "_save_last_hash", lambda _p, _v: state.__setitem__("hash", _v))
    cfg = {
        "watch": {
            "telegram": {
                "enabled": True,
                "bot_token": "t",
                "chat_id": "c1",
                "notify_on": ["all"],
                "dedup": True,
                "message_prefix": "[pkgmgr]",
            }
        }
    }
    d1 = {"run_at": "2026-03-09 18:10:00 KST", "exit_code": 2, "fail_count": 1, "warn_count": 0, "by_reason": {"X": 1}}
    d2 = {"run_at": "2026-03-09 18:11:00 KST", "exit_code": 2, "fail_count": 1, "warn_count": 0, "by_reason": {"X": 1}}
    watch._maybe_notify_telegram(cfg, diff={"added": ["x"], "modified": [], "deleted": []}, detect_result=d1, pkg_id=None)
    watch._maybe_notify_telegram(cfg, diff={"added": ["x"], "modified": [], "deleted": []}, detect_result=d2, pkg_id=None)
    assert sent["count"] == 1


def test_tick_calls_jenkins_even_when_no_snapshot_changes(monkeypatch):
    calls = {"jenkins": 0, "git": 0, "file": 0, "telegram": 0}
    monkeypatch.setattr(watch.release, "pkg_is_closed", lambda _pkg: False)
    monkeypatch.setattr(watch, "_previous_snapshot", lambda _pkg_id: {"meta": {"type": "baseline"}})
    monkeypatch.setattr(watch.snapshot, "create_snapshot", lambda _cfg: {"meta": {"type": "snapshot"}})
    monkeypatch.setattr(
        watch.snapshot,
        "diff_snapshots",
        lambda _a, _b: {"added": [], "modified": [], "deleted": []},
    )
    monkeypatch.setattr(
        watch,
        "_maybe_notify_telegram",
        lambda *_a, **_k: calls.__setitem__("telegram", calls["telegram"] + 1),
    )
    monkeypatch.setattr(
        watch,
        "_maybe_notify_git_commit",
        lambda *_a, **_k: calls.__setitem__("git", calls["git"] + 1),
    )
    monkeypatch.setattr(
        watch,
        "_maybe_notify_jenkins",
        lambda *_a, **_k: calls.__setitem__("jenkins", calls["jenkins"] + 1),
    )
    monkeypatch.setattr(
        watch,
        "_maybe_notify_file_watch",
        lambda *_a, **_k: calls.__setitem__("file", calls["file"] + 1),
    )
    cfg = {"watch": {"detect": True, "on_change": []}}
    watch._tick(cfg, pkg_id=None, auto_point=False, point_label=None)
    assert calls["telegram"] == 1
    assert calls["git"] == 1
    assert calls["jenkins"] == 1
    assert calls["file"] == 1


def test_telegram_chat_ids_prefers_subscribers_file(tmp_path):
    subs = tmp_path / "telegram-subscribers.yaml"
    subs.write_text(
        "\n".join(
            [
                "approved_chat_ids:",
                "  - s1",
                "  - s2",
                "approved_users: []",
                "pending_users: []",
                "offset: 0",
            ]
        )
        + "\n"
    )
    cfg = {
        "watch": {
            "telegram": {
                "subscribers_file": str(subs),
                "chat_id": "legacy1",
                "chat_ids": ["legacy2"],
            }
        }
    }
    ids = watch._telegram_chat_ids(cfg)
    assert ids == ["s1", "s2", "legacy2", "legacy1"]


def test_telegram_poll_once_start_adds_pending_and_notifies_admin(tmp_path, monkeypatch):
    subs = tmp_path / "telegram-subscribers.yaml"
    sent = []
    monkeypatch.setattr(
        watch,
        "_telegram_get_updates",
        lambda _token, offset=None, timeout_sec=0: [
            {
                "update_id": 10,
                "message": {
                    "text": "/start",
                    "chat": {"id": "user1"},
                    "from": {"username": "u1", "first_name": "User One"},
                },
            }
        ],
    )
    monkeypatch.setattr(
        watch,
        "_send_telegram",
        lambda _token, chat_id, text: (sent.append((str(chat_id), text)) or True, ""),
    )
    cfg = {
        "watch": {
            "interval_sec": 1,
            "telegram": {
                "enabled": True,
                "bot_token": "t",
                "subscribers_file": str(subs),
                "admin_chat_ids": ["admin1"],
                "registration": {"enabled": True, "auto_reply": True, "notify_admin_on_start": True},
            },
        }
    }
    rc = watch.telegram_poll_once(cfg)
    assert rc == 0
    state = watch._load_subscribers(cfg, ensure_exists=False)
    assert state["offset"] == 11
    assert len(state["pending_users"]) == 1
    assert state["pending_users"][0]["chat_id"] == "user1"
    chat_ids = [x[0] for x in sent]
    assert "user1" in chat_ids
    assert "admin1" in chat_ids


def test_telegram_poll_once_admin_approve_moves_to_approved(tmp_path, monkeypatch):
    subs = tmp_path / "telegram-subscribers.yaml"
    watch._write_subscribers_yaml(
        str(subs),
        {
            "approved_chat_ids": [],
            "approved_users": [],
            "pending_users": [{"chat_id": "u100", "username": "u", "first_name": "U", "requested_at": "t"}],
            "offset": 1,
        },
    )
    monkeypatch.setattr(
        watch,
        "_telegram_get_updates",
        lambda _token, offset=None, timeout_sec=0: [
            {
                "update_id": 2,
                "message": {
                    "text": "/approve u100",
                    "chat": {"id": "admin1"},
                    "from": {"username": "admin", "first_name": "Admin"},
                },
            }
        ],
    )
    monkeypatch.setattr(watch, "_send_telegram", lambda *_a, **_k: (True, ""))
    cfg = {
        "watch": {
            "telegram": {
                "enabled": True,
                "bot_token": "t",
                "subscribers_file": str(subs),
                "admin_chat_ids": ["admin1"],
                "registration": {"enabled": True, "auto_reply": True, "notify_admin_on_start": True},
            }
        }
    }
    rc = watch.telegram_poll_once(cfg)
    assert rc == 0
    state = watch._load_subscribers(cfg, ensure_exists=False)
    assert "u100" in state["approved_chat_ids"]
    assert len(state["pending_users"]) == 0


def test_telegram_poll_once_notifies_admin_when_existing_pending_and_no_updates(tmp_path, monkeypatch):
    subs = tmp_path / "telegram-subscribers.yaml"
    watch._write_subscribers_yaml(
        str(subs),
        {
            "approved_chat_ids": ["admin1"],
            "approved_users": [],
            "pending_users": [{"chat_id": "u200", "username": "", "first_name": "은지", "requested_at": "2026-03-11 18:40:41 KST"}],
            "offset": 10,
        },
    )
    sent = []
    monkeypatch.setattr(watch, "_telegram_get_updates", lambda *_a, **_k: [])
    monkeypatch.setattr(watch, "_send_telegram", lambda _t, cid, txt, cfg=None: (sent.append((cid, txt)) or True, ""))
    hashes = {}
    monkeypatch.setattr(watch, "_load_last_hash", lambda p: hashes.get(p, ""))
    monkeypatch.setattr(watch, "_save_last_hash", lambda p, v: hashes.__setitem__(p, v))
    cfg = {
        "watch": {
            "telegram": {
                "enabled": True,
                "bot_token": "t",
                "subscribers_file": str(subs),
                "admin_chat_ids": ["admin1"],
                "registration": {"enabled": True, "auto_reply": True, "notify_admin_on_start": True},
            }
        }
    }
    rc = watch.telegram_poll_once(cfg)
    assert rc == 0
    assert any(str(cid) == "admin1" and "승인 대기 사용자가 있습니다." in msg for cid, msg in sent)
    assert any(str(cid) == "admin1" and "/approve u200" in msg for cid, msg in sent)
    assert any(str(cid) == "admin1" and "/reject u200" in msg for cid, msg in sent)


def test_telegram_poll_once_can_skip_pending_reminder(tmp_path, monkeypatch):
    subs = tmp_path / "telegram-subscribers.yaml"
    watch._write_subscribers_yaml(
        str(subs),
        {
            "approved_chat_ids": ["admin1"],
            "approved_users": [],
            "pending_users": [{"chat_id": "u200", "username": "", "first_name": "은지", "requested_at": "t"}],
            "offset": 10,
        },
    )
    sent = []
    monkeypatch.setattr(watch, "_telegram_get_updates", lambda *_a, **_k: [])
    monkeypatch.setattr(watch, "_send_telegram", lambda _t, cid, txt, cfg=None: (sent.append((cid, txt)) or True, ""))
    cfg = {
        "watch": {
            "telegram": {
                "enabled": True,
                "bot_token": "t",
                "subscribers_file": str(subs),
                "admin_chat_ids": ["admin1"],
                "registration": {"enabled": True, "auto_reply": True, "notify_admin_on_start": True},
            }
        }
    }
    rc = watch.telegram_poll_once(cfg, remind_pending=False)
    assert rc == 0
    assert sent == []
