from __future__ import print_function
"""Watcher/daemon scaffold."""

import json
import os
import time
import hashlib
import base64
import glob
import tempfile
import subprocess
import textwrap
import ssl
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import snapshot, release, points, detection, config


def run(cfg, run_once=False, pkg_id=None, auto_point=False, point_label=None):
    """
    Basic poller:
      - loads last point snapshot (if pkg_id provided) or baseline
      - takes new snapshot
      - if diff exists, run watch.on_change actions
      - optionally create a point after actions
    """
    interval = cfg.get("watch", {}).get("interval_sec", 60)
    print("[watch] starting poller interval=%ss once=%s pkg=%s auto_point=%s" % (interval, run_once, pkg_id, auto_point))
    if run_once:
        _tick(cfg, pkg_id=pkg_id, auto_point=auto_point, point_label=point_label)
        return
    while True:
        _tick(cfg, pkg_id=pkg_id, auto_point=auto_point, point_label=point_label)
        time.sleep(interval)


def _load_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _previous_snapshot(pkg_id):
    """Return previous snapshot data for diff: latest point snapshot if available, else baseline."""
    if pkg_id:
        _, snap = points.load_latest_point(pkg_id)
        if snap:
            return snap
    baseline_path = os.path.join(snapshot.STATE_DIR, "baseline.json")
    return _load_json(baseline_path)


def _tick(cfg, pkg_id=None, auto_point=False, point_label=None):
    if pkg_id and release.pkg_is_closed(pkg_id):
        print("[watch] pkg=%s is closed; skipping poll" % pkg_id)
        return
    prev_snap = _previous_snapshot(pkg_id)
    current_snap = snapshot.create_snapshot(cfg)
    if prev_snap:
        diff = snapshot.diff_snapshots(prev_snap, current_snap)
        if not any(diff.values()):
            print("[watch] no changes since last point/baseline")
            _maybe_notify_telegram(cfg, diff=diff, detect_result=None, pkg_id=pkg_id)
            _maybe_notify_git_commit(cfg)
            _maybe_notify_jenkins(cfg)
            _maybe_notify_file_watch(cfg)
            return
        print("[watch] changes detected: added=%d modified=%d deleted=%d" % (len(diff["added"]), len(diff["modified"]), len(diff["deleted"])))
    else:
        print("[watch] no previous snapshot; treating as initial run")
        diff = None

    detect_result = None
    if (cfg.get("watch") or {}).get("detect", True):
        detect_result = detection.run(cfg, emit=False)

    actions_to_run = (cfg.get("watch") or {}).get("on_change", []) or []
    results = []
    if actions_to_run:
        context = _build_watch_context(diff, detect_result, pkg_id=pkg_id)
        results = release.run_actions(cfg, actions_to_run, context=context)
    else:
        print("[watch] no watch.on_change actions configured")

    _maybe_notify_telegram(cfg, diff=diff, detect_result=detect_result, pkg_id=pkg_id)
    _maybe_notify_git_commit(cfg)
    _maybe_notify_jenkins(cfg)
    _maybe_notify_file_watch(cfg)

    if auto_point and pkg_id:
        label = point_label or "watch-auto"
        release.create_point(
            cfg,
            pkg_id,
            label=label,
            actions_run=actions_to_run,
            actions_result=results,
            snapshot_data=current_snap,
        )


def _build_watch_context(diff, detect_result, pkg_id=None):
    diff = diff or {"added": [], "modified": [], "deleted": []}
    by_reason = (detect_result or {}).get("by_reason") or {}
    return {
        "event": "watch",
        "pkg_id": pkg_id or "",
        "watch_added": len(diff.get("added") or []),
        "watch_modified": len(diff.get("modified") or []),
        "watch_deleted": len(diff.get("deleted") or []),
        "detect_exit_code": (detect_result or {}).get("exit_code", 0),
        "detect_fail_count": (detect_result or {}).get("fail_count", 0),
        "detect_warn_count": (detect_result or {}).get("warn_count", 0),
        "detect_ambiguous_count": by_reason.get("AMBIGUOUS_PKG", 0),
        "detect_changed_not_updated_count": by_reason.get("CHANGED_NOT_UPDATED", 0),
        "detect_deleted_not_updated_count": by_reason.get("DELETED_NOT_UPDATED", 0),
        "detect_tracked_not_in_pkg_count": by_reason.get("TRACKED_CHANGED_NOT_IN_PKG", 0),
        "detect_untracked_not_in_pkg_count": by_reason.get("UNTRACKED_NOT_IN_PKG", 0),
    }


def _watch_state_dir():
    path = os.path.join(snapshot.STATE_DIR, "watch")
    if not os.path.exists(path):
        os.makedirs(path)
    return path


def _subscribers_default():
    return {
        "approved_chat_ids": [],
        "approved_users": [],
        "pending_users": [],
        "offset": 0,
    }


def _subscribers_file_path(cfg):
    tcfg = _telegram_cfg(cfg)
    configured = str(tcfg.get("subscribers_file") or "").strip()
    if not configured:
        configured = os.path.join(config.DEFAULT_CONFIG_DIR, "telegram-subscribers.yaml")
    return os.path.abspath(os.path.expanduser(configured))


def _subscribers_backup_glob(path):
    return path + ".bak_*"


def _normalize_subscribers(data):
    src = data if isinstance(data, dict) else {}
    out = _subscribers_default()
    for cid in (src.get("approved_chat_ids") or []):
        s = str(cid).strip()
        if s and s not in out["approved_chat_ids"]:
            out["approved_chat_ids"].append(s)

    for row in (src.get("approved_users") or []):
        if not isinstance(row, dict):
            continue
        chat_id = str(row.get("chat_id") or "").strip()
        if not chat_id:
            continue
        entry = {
            "chat_id": chat_id,
            "username": str(row.get("username") or "").strip(),
            "first_name": str(row.get("first_name") or "").strip(),
            "approved_at": str(row.get("approved_at") or "").strip(),
            "approved_by": str(row.get("approved_by") or "").strip(),
        }
        out["approved_users"].append(entry)
        if chat_id not in out["approved_chat_ids"]:
            out["approved_chat_ids"].append(chat_id)

    for row in (src.get("pending_users") or []):
        if not isinstance(row, dict):
            continue
        chat_id = str(row.get("chat_id") or "").strip()
        if not chat_id:
            continue
        entry = {
            "chat_id": chat_id,
            "username": str(row.get("username") or "").strip(),
            "first_name": str(row.get("first_name") or "").strip(),
            "requested_at": str(row.get("requested_at") or "").strip(),
        }
        out["pending_users"].append(entry)

    try:
        out["offset"] = int(src.get("offset", 0) or 0)
    except Exception:
        out["offset"] = 0
    return out


def _load_subscribers_yaml(path):
    if config.yaml is None:
        raise RuntimeError("PyYAML not installed")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        parsed = config.yaml.safe_load(f.read()) or {}
    return _normalize_subscribers(parsed)


def _write_subscribers_yaml(path, data):
    if config.yaml is None:
        raise RuntimeError("PyYAML not installed")
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent)
    temp_fd, temp_path = tempfile.mkstemp(prefix=".telegram-subscribers-", suffix=".tmp", dir=parent or None)
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            dumped = config.yaml.safe_dump(_normalize_subscribers(data), allow_unicode=True, sort_keys=False)
            f.write(dumped or "")
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


def _save_subscribers(cfg, data):
    path = _subscribers_file_path(cfg)
    existing = None
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                existing = f.read()
        except Exception:
            existing = None
    if existing is not None:
        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        backup_path = path + ".bak_" + ts
        try:
            with open(backup_path, "w", encoding="utf-8") as bf:
                bf.write(existing)
        except Exception:
            pass
    _write_subscribers_yaml(path, data)


def _load_subscribers(cfg, ensure_exists=False):
    path = _subscribers_file_path(cfg)
    if os.path.isfile(path):
        try:
            return _load_subscribers_yaml(path)
        except Exception as exc:
            print("[watch][telegram] subscribers parse failed: %s" % str(exc))
            backups = sorted(glob.glob(_subscribers_backup_glob(path)), reverse=True)
            for bp in backups:
                try:
                    restored = _load_subscribers_yaml(bp)
                    print("[watch][telegram] subscribers restored from backup: %s" % bp)
                    _write_subscribers_yaml(path, restored)
                    return restored
                except Exception:
                    continue
            reset = _subscribers_default()
            print("[watch][telegram] subscribers reset to empty schema")
            if ensure_exists:
                _write_subscribers_yaml(path, reset)
            return reset
    if ensure_exists:
        base = _subscribers_default()
        _write_subscribers_yaml(path, base)
        return base
    return _subscribers_default()


def _subscribers_lock_path(cfg):
    return _subscribers_file_path(cfg) + ".lock"


def _subscribers_lock_acquire(cfg, timeout_sec=10):
    lock_path = _subscribers_lock_path(cfg)
    deadline = time.time() + max(1, int(timeout_sec))
    while time.time() < deadline:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(fd, str(os.getpid()).encode("utf-8"))
            return fd, lock_path
        except FileExistsError:
            time.sleep(0.1)
        except Exception:
            break
    raise RuntimeError("telegram subscribers lock timeout: %s" % lock_path)


def _subscribers_lock_release(fd, lock_path):
    try:
        os.close(fd)
    except Exception:
        pass
    try:
        os.remove(lock_path)
    except Exception:
        pass


def _watch_last_hash_path(pkg_id=None):
    suffix = str(pkg_id) if pkg_id else "global"
    return os.path.join(_watch_state_dir(), "telegram-last-%s.sha256" % suffix)


def _watch_channel_hash_path(channel, key):
    k = hashlib.sha256(("%s:%s" % (channel, key)).encode("utf-8")).hexdigest()
    return os.path.join(_watch_state_dir(), "telegram-%s-%s.sha256" % (channel, k))


def _watch_state_json_path(channel, key):
    k = hashlib.sha256(("%s:%s" % (channel, key)).encode("utf-8")).hexdigest()
    return os.path.join(_watch_state_dir(), "%s-%s.json" % (channel, k))


def _load_last_hash(path):
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except Exception:
        return ""


def _save_last_hash(path, value):
    try:
        with open(path, "w") as f:
            f.write(str(value))
    except Exception:
        return


def _load_state_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_state_json(path, value):
    try:
        with open(path, "w") as f:
            json.dump(value or {}, f, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception:
        return


def _telegram_cfg(cfg):
    watch_cfg = cfg.get("watch") or {}
    tcfg = watch_cfg.get("telegram") if isinstance(watch_cfg.get("telegram"), dict) else {}
    return tcfg


def _telegram_enabled(cfg):
    tcfg = _telegram_cfg(cfg)
    ids = _telegram_chat_ids(cfg)
    return bool(tcfg.get("enabled")) and bool(tcfg.get("bot_token")) and bool(ids)


def _telegram_chat_ids(cfg):
    tcfg = _telegram_cfg(cfg)
    ids = []
    if "subscribers_file" in tcfg:
        subscribers = _load_subscribers(cfg, ensure_exists=False)
        for v in (subscribers.get("approved_chat_ids") or []):
            s = str(v).strip()
            if s and s not in ids:
                ids.append(s)
    for v in (tcfg.get("chat_ids") or []):
        s = str(v).strip()
        if s and s not in ids:
            ids.append(s)
    single = str(tcfg.get("chat_id") or "").strip()
    if single and single not in ids:
        ids.append(single)
    return ids


def _channel_cfg(cfg, channel):
    tcfg = _telegram_cfg(cfg)
    channels = tcfg.get("channels") if isinstance(tcfg.get("channels"), dict) else {}
    default = {"enabled": False}
    if channel == "detect":
        default = {"enabled": True}
    chan = channels.get(channel) if isinstance(channels.get(channel), dict) else {}
    out = dict(default)
    out.update(chan)
    return out


def _send_channel_notification(cfg, channel, key, text, dedup=True):
    if not _telegram_enabled(cfg):
        return False
    tcfg = _telegram_cfg(cfg)
    digest = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
    hash_path = _watch_channel_hash_path(channel, key)
    if dedup and bool(tcfg.get("dedup", True)) and _load_last_hash(hash_path) == digest:
        return False
    chat_ids = _telegram_chat_ids(cfg)
    all_ok = True
    for cid in chat_ids:
        try:
            ok, err = _send_telegram(tcfg.get("bot_token"), cid, text, cfg=cfg)
        except TypeError:
            ok, err = _send_telegram(tcfg.get("bot_token"), cid, text)
        if not ok:
            all_ok = False
            print("[watch] telegram notification failed (%s, chat_id=%s): %s" % (channel, cid, err))
    if all_ok and dedup and bool(tcfg.get("dedup", True)):
        _save_last_hash(hash_path, digest)
    return all_ok


def _should_notify(telegram_cfg, diff, detect_result):
    rules = set([str(v).strip().lower() for v in (telegram_cfg.get("notify_on") or []) if str(v).strip()])
    if not rules:
        rules = set(["fail", "warn"])
    diff = diff or {"added": [], "modified": [], "deleted": []}
    changed = bool((diff.get("added") or []) or (diff.get("modified") or []) or (diff.get("deleted") or []))
    fail_count = (detect_result or {}).get("fail_count", 0)
    warn_count = (detect_result or {}).get("warn_count", 0)
    if "all" in rules:
        return True
    if "changes" in rules and changed:
        return True
    if "fail" in rules and fail_count > 0:
        return True
    if "warn" in rules and warn_count > 0:
        return True
    return False


def _format_telegram_message(cfg, diff, detect_result, pkg_id=None):
    detect_chan = _channel_cfg(cfg, "detect")
    message_file = str(detect_chan.get("message_file") or "").strip()
    max_chars = int(detect_chan.get("max_chars") or 3800)
    wrap_width = int(detect_chan.get("wrap_width") or 72)
    max_lines = int(detect_chan.get("message_file_max_lines") or 120)
    if message_file:
        ap = os.path.abspath(os.path.expanduser(message_file))
        try:
            with open(ap, "r", encoding="utf-8", errors="replace") as f:
                body = f.read()
            if body.strip():
                run_at = (detect_result or {}).get("run_at") or time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime())
                fail_count = int((detect_result or {}).get("fail_count", 0) or 0)
                warn_count = int((detect_result or {}).get("warn_count", 0) or 0)
                intro = "확인 필요 사항이 발생하여 알려드립니다." if (fail_count > 0 or warn_count > 0) else "정상 상태입니다."
                excerpt = _extract_detection_sections(body, max_lines=max_lines)
                if excerpt:
                    lines = [
                        "%s [DETECT] %s" % (((cfg.get("watch") or {}).get("telegram") or {}).get("message_prefix") or "[pkgmgr]", run_at),
                        intro,
                        "",
                        excerpt,
                    ]
                    out = "\n".join(lines)
                    if len(out) > max_chars:
                        omitted = len(out) - max_chars
                        out = out[:max_chars] + "\n...(omitted %d chars)" % omitted
                    return _wrap_for_telegram(out, width=wrap_width)
                if len(body) > max_chars:
                    omitted = len(body) - max_chars
                    body = body[:max_chars] + "\n...(omitted %d chars)" % omitted
                return _wrap_for_telegram(body, width=wrap_width)
        except Exception:
            pass
    prefix = ((cfg.get("watch") or {}).get("telegram") or {}).get("message_prefix") or "[pkgmgr]"
    by_reason = (detect_result or {}).get("by_reason") or {}
    run_at = (detect_result or {}).get("run_at") or time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime())
    system_name = str((detect_result or {}).get("system") or ((cfg.get("detection") or {}).get("system") or "")).strip()
    lines = [
        "%s [DETECT][SUMMARY]" % prefix,
    ]
    if system_name:
        lines.append("system=%s" % system_name)
    lines.extend(
        [
            "run_at=%s" % run_at,
            "pkg=%s" % (pkg_id or "all"),
        ]
    )
    if detect_result:
        lines.append(
            "detect: exit=%s fail=%d warn=%d"
            % (
                detect_result.get("exit_code", 0),
                detect_result.get("fail_count", 0),
                detect_result.get("warn_count", 0),
            )
        )
        if by_reason:
            parts = []
            for key in sorted(by_reason.keys()):
                parts.append("%s=%d" % (key, by_reason[key]))
            lines.append("by_reason: " + ", ".join(parts))
    else:
        diff = diff or {"added": [], "modified": [], "deleted": []}
        lines.append(
            "diff: added=%d modified=%d deleted=%d"
            % (len(diff.get("added") or []), len(diff.get("modified") or []), len(diff.get("deleted") or []))
        )
    return _wrap_for_telegram("\n".join(lines), width=wrap_width)


def _wrap_for_telegram(text, width=72):
    w = int(width or 72)
    out = []
    for raw in str(text or "").splitlines():
        line = raw.rstrip("\n")
        if not line:
            out.append("")
            continue
        if len(line) <= w:
            out.append(line)
            continue
        # Keep indented bullets/readability while wrapping.
        indent_len = len(line) - len(line.lstrip(" "))
        indent = " " * indent_len
        wrapped = textwrap.wrap(
            line,
            width=w,
            break_long_words=False,
            break_on_hyphens=False,
            subsequent_indent=indent + "  ",
        )
        if not wrapped:
            out.append(line)
        else:
            out.extend(wrapped)
    return "\n".join(out)


def _extract_detection_sections(text, max_lines=120):
    targets = set(
        [
            "[detection] summary",
            "[detection] managed_by_reason",
            "[detection] unmanaged_by_reason",
            "[detection] by_reason",
            "[detection] git_by_reason",
        ]
    )
    lines = str(text or "").splitlines()
    out = []
    keep = False
    for line in lines:
        if line.startswith("[detection] "):
            keep = line.strip() in targets
            if keep:
                out.append(line)
            continue
        if keep:
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    limit = int(max_lines or 0)
    if limit > 0 and len(out) > limit:
        omitted = len(out) - limit
        out = out[:limit] + ["...(omitted %d lines)" % omitted]
    return "\n".join(out).strip()


def _detect_dedup_payload(detect_result):
    d = detect_result or {}
    payload = {
        "exit_code": int(d.get("exit_code", 0) or 0),
        "fail_count": int(d.get("fail_count", 0) or 0),
        "warn_count": int(d.get("warn_count", 0) or 0),
        "by_reason": d.get("by_reason") or {},
        "managed_by_reason": d.get("managed_by_reason") or {},
        "unmanaged_by_reason": d.get("unmanaged_by_reason") or {},
        "git_by_reason": d.get("git_by_reason") or {},
        "system": str(d.get("system") or ""),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _send_telegram(bot_token, chat_id, text, cfg=None):
    if not bot_token or not chat_id:
        return False, "missing token/chat_id"
    url = "https://api.telegram.org/bot%s/sendMessage" % str(bot_token).strip()
    body = urlencode({"chat_id": str(chat_id), "text": text}).encode("utf-8")
    req = Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        ctx = _telegram_ssl_context(cfg or {})
        if ctx is None:
            resp_ctx = urlopen(req, timeout=10)
        else:
            resp_ctx = urlopen(req, timeout=10, context=ctx)
        with resp_ctx as resp:
            code = getattr(resp, "status", 200)
            if int(code) >= 400:
                return False, "http status %s" % code
    except Exception as exc:
        return False, str(exc)
    return True, ""


def _telegram_ssl_context(cfg):
    tcfg = _telegram_cfg(cfg)
    verify = bool(tcfg.get("tls_verify", True))
    if not verify:
        return ssl._create_unverified_context()
    caf = str(tcfg.get("ca_file") or "").strip()
    if not caf:
        return None
    path = os.path.abspath(os.path.expanduser(caf))
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cafile=path)
    return ctx


def _telegram_get_updates(bot_token, offset=None, timeout_sec=0, cfg=None):
    if not bot_token:
        return []
    url = "https://api.telegram.org/bot%s/getUpdates" % str(bot_token).strip()
    params = {"timeout": int(timeout_sec or 0)}
    if offset is not None:
        params["offset"] = int(offset)
    body = urlencode(params).encode("utf-8")
    req = Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        tout = max(10, int(timeout_sec or 0) + 5)
        ctx = _telegram_ssl_context(cfg or {})
        if ctx is None:
            resp_ctx = urlopen(req, timeout=tout)
        else:
            resp_ctx = urlopen(req, timeout=tout, context=ctx)
        with resp_ctx as resp:
            raw = resp.read()
        payload = json.loads(raw.decode("utf-8", errors="replace")) if raw else {}
    except Exception as exc:
        print("[telegram] getUpdates failed: %s" % str(exc))
        return []
    if not payload.get("ok"):
        print("[telegram] getUpdates failed: %s" % payload)
        return []
    items = payload.get("result")
    return items if isinstance(items, list) else []


def _registration_cfg(cfg):
    reg = (_telegram_cfg(cfg).get("registration") if isinstance(_telegram_cfg(cfg).get("registration"), dict) else {})
    return {
        "enabled": bool(reg.get("enabled", True)),
        "auto_reply": bool(reg.get("auto_reply", True)),
        "notify_admin_on_start": bool(reg.get("notify_admin_on_start", True)),
    }


def _admin_chat_ids(cfg):
    ids = []
    for raw in (_telegram_cfg(cfg).get("admin_chat_ids") or []):
        s = str(raw).strip()
        if s and s not in ids:
            ids.append(s)
    return ids


def _send_direct(cfg, chat_id, text):
    tcfg = _telegram_cfg(cfg)
    try:
        ok, err = _send_telegram(tcfg.get("bot_token"), str(chat_id), text, cfg=cfg)
    except TypeError:
        ok, err = _send_telegram(tcfg.get("bot_token"), str(chat_id), text)
    if not ok:
        print("[telegram] send failed (chat_id=%s): %s" % (chat_id, err))
    return ok


def _ts_now():
    return time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime())


def _find_user(users, chat_id):
    target = str(chat_id).strip()
    for idx, row in enumerate(users or []):
        if str((row or {}).get("chat_id") or "").strip() == target:
            return idx, row
    return -1, None


def _apply_start_request(cfg, state, chat_id, username, first_name):
    approved_ids = state.get("approved_chat_ids") or []
    if str(chat_id) in approved_ids:
        return "already_approved"
    idx, _ = _find_user(state.get("pending_users") or [], chat_id)
    if idx >= 0:
        return "already_pending"
    state["pending_users"].append(
        {
            "chat_id": str(chat_id),
            "username": str(username or ""),
            "first_name": str(first_name or ""),
            "requested_at": _ts_now(),
        }
    )
    return "pending_added"


def _approve_pending(state, chat_id, approved_by):
    cid = str(chat_id).strip()
    pidx, prow = _find_user(state.get("pending_users") or [], cid)
    if pidx < 0:
        return False, None
    state["pending_users"].pop(pidx)
    if cid not in (state.get("approved_chat_ids") or []):
        state["approved_chat_ids"].append(cid)
    aidx, _ = _find_user(state.get("approved_users") or [], cid)
    entry = {
        "chat_id": cid,
        "username": str((prow or {}).get("username") or ""),
        "first_name": str((prow or {}).get("first_name") or ""),
        "approved_at": _ts_now(),
        "approved_by": str(approved_by or ""),
    }
    if aidx >= 0:
        state["approved_users"][aidx] = entry
    else:
        state["approved_users"].append(entry)
    return True, prow


def _reject_pending(state, chat_id):
    cid = str(chat_id).strip()
    pidx, prow = _find_user(state.get("pending_users") or [], cid)
    if pidx < 0:
        return False, None
    state["pending_users"].pop(pidx)
    return True, prow


def _extract_text_command(update):
    msg = (update or {}).get("message")
    if not isinstance(msg, dict):
        return None
    text = str(msg.get("text") or "").strip()
    if not text.startswith("/"):
        return None
    chat = msg.get("chat") if isinstance(msg.get("chat"), dict) else {}
    sender = msg.get("from") if isinstance(msg.get("from"), dict) else {}
    return {
        "update_id": int(update.get("update_id") or 0),
        "text": text,
        "chat_id": str(chat.get("id") or ""),
        "username": str(sender.get("username") or ""),
        "first_name": str(sender.get("first_name") or ""),
    }


def _admin_notify_start(cfg, cmd):
    admins = _admin_chat_ids(cfg)
    if not admins:
        return
    prefix = (_telegram_cfg(cfg).get("message_prefix") or "[pkgmgr]").strip()
    msg = "\n".join(
        [
            "%s [REGISTRATION] %s" % (prefix, _ts_now()),
            "신규 구독 승인 요청이 있습니다.",
            "",
            "chat_id=%s" % cmd.get("chat_id"),
            "username=%s" % (cmd.get("username") or "-"),
            "first_name=%s" % (cmd.get("first_name") or "-"),
            "",
            "승인: /approve %s" % cmd.get("chat_id"),
            "거절: /reject %s" % cmd.get("chat_id"),
        ]
    )
    for admin_id in admins:
        _send_direct(cfg, admin_id, msg)


def _admin_notify_pending_reminder(cfg, state, force=False):
    admins = _admin_chat_ids(cfg)
    rows = state.get("pending_users") or []
    if not admins or not rows:
        return
    prefix = (_telegram_cfg(cfg).get("message_prefix") or "[pkgmgr]").strip()
    pending_lines = []
    for row in rows:
        pending_lines.append(
            "- chat_id=%s username=%s first_name=%s requested_at=%s"
            % (
                row.get("chat_id"),
                row.get("username") or "-",
                row.get("first_name") or "-",
                row.get("requested_at") or "-",
            )
        )
    stable = "\n".join(pending_lines)
    digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()
    for admin_id in admins:
        key = "pending-reminder:%s" % str(admin_id)
        hash_path = _watch_channel_hash_path("registration", key)
        if (not force) and _load_last_hash(hash_path) == digest:
            continue
        first_chat_id = str((rows[0] or {}).get("chat_id") or "").strip() if rows else ""
        approve_hint = "/approve <chat_id>"
        reject_hint = "/reject <chat_id>"
        if first_chat_id:
            approve_hint = "/approve %s" % first_chat_id
            reject_hint = "/reject %s" % first_chat_id
        msg = "\n".join(
            [
                "%s [REGISTRATION] %s" % (prefix, _ts_now()),
                "승인 대기 사용자가 있습니다.",
                "",
                "pending_count=%d" % len(rows),
                "",
                stable,
                "",
                "승인: %s" % approve_hint,
                "거절: %s" % reject_hint,
                "목록: /pending",
            ]
        )
        if _send_direct(cfg, admin_id, msg):
            _save_last_hash(hash_path, digest)


def _format_pending_list(state):
    rows = state.get("pending_users") or []
    if not rows:
        return "pending: none"
    out = ["pending list:"]
    for row in rows:
        out.append(
            "- chat_id=%s username=%s first_name=%s requested_at=%s"
            % (
                row.get("chat_id"),
                row.get("username") or "-",
                row.get("first_name") or "-",
                row.get("requested_at") or "-",
            )
        )
    return "\n".join(out)


def telegram_list(cfg):
    state = _load_subscribers(cfg, ensure_exists=True)
    print("[telegram] subscribers_file=%s" % _subscribers_file_path(cfg))
    print("[telegram] approved_chat_ids=%d pending_users=%d offset=%d" % (
        len(state.get("approved_chat_ids") or []),
        len(state.get("pending_users") or []),
        int(state.get("offset") or 0),
    ))
    for cid in (state.get("approved_chat_ids") or []):
        print("  approved: %s" % cid)
    for row in (state.get("pending_users") or []):
        print("  pending: chat_id=%s username=%s requested_at=%s" % (
            row.get("chat_id"), row.get("username") or "-", row.get("requested_at") or "-"
        ))
    return 0


def telegram_approve(cfg, chat_id, approved_by="manual"):
    fd, lp = _subscribers_lock_acquire(cfg)
    try:
        state = _load_subscribers(cfg, ensure_exists=True)
        ok, pending_row = _approve_pending(state, chat_id, approved_by=approved_by)
        if not ok:
            print("[telegram] pending user not found: %s" % chat_id)
            return 1
        _save_subscribers(cfg, state)
    finally:
        _subscribers_lock_release(fd, lp)
    reg = _registration_cfg(cfg)
    if reg.get("auto_reply"):
        _send_direct(cfg, chat_id, "구독이 승인되었습니다. 알림을 수신합니다.")
    print("[telegram] approved: %s" % chat_id)
    return 0


def telegram_reject(cfg, chat_id, rejected_by="manual"):
    _ = rejected_by
    fd, lp = _subscribers_lock_acquire(cfg)
    try:
        state = _load_subscribers(cfg, ensure_exists=True)
        ok, _row = _reject_pending(state, chat_id)
        if not ok:
            print("[telegram] pending user not found: %s" % chat_id)
            return 1
        _save_subscribers(cfg, state)
    finally:
        _subscribers_lock_release(fd, lp)
    reg = _registration_cfg(cfg)
    if reg.get("auto_reply"):
        _send_direct(cfg, chat_id, "구독 요청이 거절되었습니다. 관리자에게 문의하세요.")
    print("[telegram] rejected: %s" % chat_id)
    return 0


def _handle_registration_command(cfg, state, cmd):
    reg = _registration_cfg(cfg)
    text = str(cmd.get("text") or "").strip()
    chat_id = str(cmd.get("chat_id") or "")
    admins = set(_admin_chat_ids(cfg))

    if text.startswith("/start"):
        status = _apply_start_request(cfg, state, chat_id, cmd.get("username"), cmd.get("first_name"))
        if reg.get("auto_reply"):
            if status == "already_approved":
                _send_direct(cfg, chat_id, "이미 승인된 사용자입니다.")
            elif status == "already_pending":
                _send_direct(cfg, chat_id, "이미 승인 대기 중입니다.")
            else:
                _send_direct(cfg, chat_id, "승인 요청이 접수되었습니다. 관리자 승인 후 알림을 받습니다.")
        if status == "pending_added" and reg.get("notify_admin_on_start"):
            _admin_notify_start(cfg, cmd)
        return status == "pending_added"

    if text.startswith("/pending"):
        if chat_id not in admins:
            if reg.get("auto_reply"):
                _send_direct(cfg, chat_id, "관리자만 사용할 수 있습니다.")
            return False
        _send_direct(cfg, chat_id, _format_pending_list(state))
        return False

    if text.startswith("/approve"):
        if chat_id not in admins:
            if reg.get("auto_reply"):
                _send_direct(cfg, chat_id, "관리자만 사용할 수 있습니다.")
            return False
        parts = text.split()
        if len(parts) < 2:
            if reg.get("auto_reply"):
                _send_direct(cfg, chat_id, "사용법: /approve <chat_id>")
            return False
        target = str(parts[1]).strip()
        ok, _row = _approve_pending(state, target, approved_by=chat_id)
        if not ok:
            if reg.get("auto_reply"):
                _send_direct(cfg, chat_id, "pending 사용자 없음: %s" % target)
            return False
        if reg.get("auto_reply"):
            _send_direct(cfg, target, "구독이 승인되었습니다. 알림을 수신합니다.")
            _send_direct(cfg, chat_id, "승인 완료: %s" % target)
        return True

    if text.startswith("/reject"):
        if chat_id not in admins:
            if reg.get("auto_reply"):
                _send_direct(cfg, chat_id, "관리자만 사용할 수 있습니다.")
            return False
        parts = text.split()
        if len(parts) < 2:
            if reg.get("auto_reply"):
                _send_direct(cfg, chat_id, "사용법: /reject <chat_id>")
            return False
        target = str(parts[1]).strip()
        ok, _row = _reject_pending(state, target)
        if not ok:
            if reg.get("auto_reply"):
                _send_direct(cfg, chat_id, "pending 사용자 없음: %s" % target)
            return False
        if reg.get("auto_reply"):
            _send_direct(cfg, target, "구독 요청이 거절되었습니다. 관리자에게 문의하세요.")
            _send_direct(cfg, chat_id, "거절 완료: %s" % target)
        return True

    if text.startswith("/help"):
        _send_direct(cfg, chat_id, "/start\n/pending (admin)\n/approve <chat_id> (admin)\n/reject <chat_id> (admin)")
        return False
    return False


def telegram_poll_once(cfg, remind_pending=True):
    tcfg = _telegram_cfg(cfg)
    reg = _registration_cfg(cfg)
    if not bool(tcfg.get("enabled")):
        print("[telegram] disabled")
        return 0
    if not reg.get("enabled"):
        print("[telegram] registration disabled")
        return 0
    token = str(tcfg.get("bot_token") or "").strip()
    if not token:
        raise RuntimeError("telegram bot_token is required")

    fd, lp = _subscribers_lock_acquire(cfg)
    try:
        state = _load_subscribers(cfg, ensure_exists=True)
        offset = int(state.get("offset") or 0)
        try:
            updates = _telegram_get_updates(token, offset=offset, timeout_sec=0, cfg=cfg)
        except TypeError:
            updates = _telegram_get_updates(token, offset=offset, timeout_sec=0)
        if remind_pending and (not updates) and (state.get("pending_users") or []):
            _admin_notify_pending_reminder(cfg, state, force=True)
        changed = False
        max_update_id = offset - 1
        for upd in updates:
            cmd = _extract_text_command(upd)
            try:
                uid = int((upd or {}).get("update_id") or 0)
            except Exception:
                uid = 0
            if uid > max_update_id:
                max_update_id = uid
            if not cmd:
                continue
            if _handle_registration_command(cfg, state, cmd):
                changed = True
        if max_update_id >= 0:
            new_offset = max_update_id + 1
            if int(state.get("offset") or 0) != new_offset:
                state["offset"] = new_offset
                changed = True
        if changed:
            _save_subscribers(cfg, state)
        print("[telegram] polled updates=%d changed=%s offset=%s" % (len(updates), str(changed).lower(), state.get("offset")))
    finally:
        _subscribers_lock_release(fd, lp)
    return 0


def telegram_poll(cfg, run_once=False):
    interval = int((cfg.get("watch") or {}).get("interval_sec") or 60)
    if run_once:
        return telegram_poll_once(cfg, remind_pending=True)
    print("[telegram] poller started interval=%ss" % interval)
    first_tick = True
    while True:
        telegram_poll_once(cfg, remind_pending=first_tick)
        first_tick = False
        time.sleep(interval)


def _maybe_notify_telegram(cfg, diff, detect_result, pkg_id=None):
    watch_cfg = cfg.get("watch") or {}
    telegram_cfg = watch_cfg.get("telegram") if isinstance(watch_cfg.get("telegram"), dict) else {}
    detect_channel = _channel_cfg(cfg, "detect")
    if not bool(detect_channel.get("enabled", True)):
        return
    if not telegram_cfg.get("enabled"):
        return
    if not _should_notify(telegram_cfg, diff, detect_result):
        return
    message = _format_telegram_message(cfg, diff, detect_result, pkg_id=pkg_id)
    dedup = bool(telegram_cfg.get("dedup", True))
    hash_path = _watch_last_hash_path(pkg_id=pkg_id)
    # Detect messages include run timestamp; dedupe on stable signal, not rendered text.
    if detect_result is not None:
        dedup_source = _detect_dedup_payload(detect_result)
    else:
        dedup_source = message
    digest = hashlib.sha256(dedup_source.encode("utf-8")).hexdigest()
    if dedup and _load_last_hash(hash_path) == digest:
        print("[watch] telegram skip duplicate message")
        return
    all_ok = True
    for cid in _telegram_chat_ids(cfg):
        try:
            ok, err = _send_telegram(telegram_cfg.get("bot_token"), cid, message, cfg=cfg)
        except TypeError:
            ok, err = _send_telegram(telegram_cfg.get("bot_token"), cid, message)
        if not ok:
            all_ok = False
            print("[watch] telegram notification failed (chat_id=%s): %s" % (cid, err))
    if all_ok:
        print("[watch] telegram notification sent")
        if dedup:
            _save_last_hash(hash_path, digest)


def notify_lifecycle_event(cfg, event, pkg_id=None, details=None):
    channel_cfg = _channel_cfg(cfg, "lifecycle")
    if not bool(channel_cfg.get("enabled")):
        return False
    events = set([str(v).strip() for v in (channel_cfg.get("events") or []) if str(v).strip()])
    if events and str(event) not in events:
        return False
    prefix = (_telegram_cfg(cfg).get("message_prefix") or "[pkgmgr]").strip()
    text = _format_pkg_event_message(prefix, event, pkg_id, details or {})
    key = "%s:%s" % (event, pkg_id or "none")
    return _send_channel_notification(cfg, "lifecycle", key, text, dedup=True)


def _format_pkg_event_message(prefix, event, pkg_id, details):
    run_at = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime())
    lines = [
        "%s [PKG] %s" % (prefix, run_at),
        "pkg 변경 이력이 발생했습니다.",
        "",
        "event=%s" % str(event),
        "pkg=%s" % (pkg_id or "n/a"),
    ]
    for k in sorted((details or {}).keys()):
        lines.append("%s=%s" % (k, details[k]))
    return "\n".join(lines)


def _git_current_head(repo_root, branch=None):
    root = str(repo_root or "").strip()
    if not root:
        return {}
    if branch:
        try:
            sha = subprocess.check_output(
                ["git", "-C", root, "rev-parse", branch],
                stderr=subprocess.STDOUT,
                universal_newlines=True,
            ).strip()
            log = (
                subprocess.check_output(
                    ["git", "-C", root, "show", "-s", "--format=%H|%an|%ad|%s", sha],
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                )
                .strip()
            )
        except Exception:
            return {}
    else:
        try:
            log = (
                subprocess.check_output(
                    ["git", "-C", root, "show", "-s", "--format=%H|%an|%ad|%s", "HEAD"],
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                )
                .strip()
            )
        except Exception:
            return {}
    parts = (log or "").split("|", 3)
    if len(parts) < 4:
        return {}
    return {"sha": parts[0], "author": parts[1], "date": parts[2], "subject": parts[3]}


def _maybe_notify_git_commit(cfg):
    chan = _channel_cfg(cfg, "git")
    if not bool(chan.get("enabled")):
        return
    repo_root = chan.get("repo_root") or ((cfg.get("git") or {}).get("repo_root"))
    branches = chan.get("branches") or []
    if not branches:
        branches = [chan.get("branch")] if chan.get("branch") else [None]
    prefix = (_telegram_cfg(cfg).get("message_prefix") or "[pkgmgr]").strip()
    for branch in branches:
        key = "%s|%s" % (repo_root or "", branch or "HEAD")
        state_path = _watch_state_json_path("git", key)
        prev = _load_state_json(state_path)
        cur = _git_current_head(repo_root, branch=branch)
        if not cur or not cur.get("sha"):
            continue
        if not prev:
            _save_state_json(state_path, cur)
            continue
        if prev.get("sha") == cur.get("sha"):
            continue
        text = "\n".join(
            [
                "%s git commit detected" % prefix,
                "repo=%s" % str(repo_root),
                "branch=%s" % (branch or "HEAD"),
                "sha=%s" % cur.get("sha"),
                "author=%s" % cur.get("author"),
                "subject=%s" % cur.get("subject"),
                "date=%s" % cur.get("date"),
            ]
        )
        _send_channel_notification(cfg, "git", key, text, dedup=True)
        _save_state_json(state_path, cur)


def _jenkins_build_info(job):
    url = str((job or {}).get("url") or "").strip()
    if not url:
        return {}
    api_url = url if url.endswith("/api/json") else (url.rstrip("/") + "/lastBuild/api/json")
    req = Request(api_url)
    user = str((job or {}).get("user") or "").strip()
    token = str((job or {}).get("api_token") or "").strip()
    if user and token:
        cred = base64.b64encode(("%s:%s" % (user, token)).encode("utf-8")).decode("ascii")
        req.add_header("Authorization", "Basic %s" % cred)
    try:
        with urlopen(req, timeout=10) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8", errors="replace")) if raw else {}
    except Exception:
        return {}
    base_url = url
    if base_url.endswith("/api/json"):
        base_url = base_url[: -len("/api/json")]
    base_url = base_url.rstrip("/")
    build_number = data.get("number")
    if build_number is not None:
        try:
            build_url = "%s/%s/" % (base_url, int(build_number))
        except Exception:
            build_url = "%s/%s/" % (base_url, str(build_number))
    else:
        build_url = base_url + "/"
    desc = str(data.get("description") or "").strip()
    if desc:
        desc = " ".join(desc.splitlines()).strip()
    return {
        "name": str((job or {}).get("name") or url),
        "number": build_number,
        "building": bool(data.get("building")),
        "result": data.get("result"),
        "timestamp": data.get("timestamp"),
        "url": build_url,
        "display_name": str(data.get("fullDisplayName") or data.get("displayName") or "").strip(),
        "description": desc,
    }


def _jenkins_should_notify(chan_cfg, prev, cur):
    rules = set([str(v).strip().lower() for v in (chan_cfg.get("notify_on") or []) if str(v).strip()])
    if not rules:
        rules = set(["started", "failed", "success"])
    if "all" in rules:
        return True
    if cur.get("building") and not prev.get("building"):
        return "started" in rules
    if prev.get("building") and not cur.get("building"):
        if "finished" in rules:
            return True
        result = str(cur.get("result") or "").strip().lower()
        return result in rules
    if prev.get("number") != cur.get("number"):
        result = str(cur.get("result") or "").strip().lower()
        return ("started" in rules and cur.get("building")) or result in rules
    return False


def _maybe_notify_jenkins(cfg):
    chan = _channel_cfg(cfg, "jenkins")
    if not bool(chan.get("enabled")):
        print("[watch][jenkins] channel disabled")
        return
    jobs = chan.get("jobs") if isinstance(chan.get("jobs"), list) else []
    if not jobs:
        print("[watch][jenkins] no jobs configured")
        return
    prefix = (_telegram_cfg(cfg).get("message_prefix") or "[pkgmgr]").strip()
    for job in jobs:
        if isinstance(job, str):
            job = {"name": job, "url": job}
        if not isinstance(job, dict):
            continue
        info = _jenkins_build_info(job)
        if not info:
            print("[watch][jenkins] fetch failed: name=%s url=%s" % (job.get("name"), job.get("url")))
            continue
        key = str(info.get("name") or job.get("url") or "job")
        state_path = _watch_state_json_path("jenkins", key)
        prev = _load_state_json(state_path)
        notify_on_first_seen = bool(chan.get("notify_on_first_seen", False))
        if not prev:
            if notify_on_first_seen:
                text = _format_jenkins_message(prefix, info)
                sent = _send_channel_notification(cfg, "jenkins", key, text, dedup=True)
                if sent:
                    print("[watch][jenkins] notified first-seen: job=%s number=%s" % (info.get("name"), info.get("number")))
                else:
                    print("[watch][jenkins] skipped first-seen (duplicate or telegram disabled): job=%s" % info.get("name"))
            else:
                print("[watch][jenkins] initialized state (first-seen notify disabled): job=%s" % info.get("name"))
            _save_state_json(state_path, info)
            continue
        if not _jenkins_should_notify(chan, prev, info):
            print(
                "[watch][jenkins] no event: job=%s prev(number=%s,building=%s,result=%s) cur(number=%s,building=%s,result=%s)"
                % (
                    info.get("name"),
                    prev.get("number"),
                    prev.get("building"),
                    prev.get("result"),
                    info.get("number"),
                    info.get("building"),
                    info.get("result"),
                )
            )
            _save_state_json(state_path, info)
            continue
        text = "\n".join(
            _format_jenkins_message(prefix, info).splitlines()
        )
        sent = _send_channel_notification(cfg, "jenkins", key, text, dedup=True)
        if sent:
            print("[watch][jenkins] notified event: job=%s number=%s" % (info.get("name"), info.get("number")))
        else:
            print("[watch][jenkins] skipped event (duplicate or telegram disabled): job=%s" % info.get("name"))
        _save_state_json(state_path, info)


def _format_jenkins_message(prefix, info):
    run_at = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime())
    intro = "실행 이력이 발생했습니다."
    title = str(info.get("display_name") or "").strip()
    desc = str(info.get("description") or "").strip()
    lines = [
        "%s [JENKINS] %s" % (prefix, run_at),
        intro,
        "",
    ]
    if title:
        lines.append(title)
    if desc:
        lines.append(desc)
    if title or desc:
        lines.append("")
    lines.extend(
        [
            "job=%s" % info.get("name"),
            "number=%s" % info.get("number"),
            "building=%s" % info.get("building"),
            "result=%s" % (info.get("result") or "N/A"),
            "url=%s" % info.get("url"),
        ]
    )
    return "\n".join(lines)


def _maybe_notify_file_watch(cfg):
    chan = _channel_cfg(cfg, "file_watch")
    if not bool(chan.get("enabled")):
        return
    files = chan.get("files") if isinstance(chan.get("files"), list) else []
    prefix = (_telegram_cfg(cfg).get("message_prefix") or "[pkgmgr]").strip()
    max_chars = int(chan.get("max_chars") or 3000)
    for spec in files:
        if isinstance(spec, str):
            spec = {"path": spec}
        if not isinstance(spec, dict):
            continue
        path = str(spec.get("path") or "").strip()
        if not path:
            continue
        ap = os.path.abspath(os.path.expanduser(path))
        if not os.path.isfile(ap):
            continue
        encoding = str(spec.get("encoding") or "utf-8")
        try:
            with open(ap, "r", encoding=encoding, errors="replace") as f:
                content = f.read()
        except Exception:
            continue
        key = ap
        state_path = _watch_state_json_path("file_watch", key)
        prev = _load_state_json(state_path)
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if prev.get("hash") == content_hash:
            continue
        body = content if len(content) <= max_chars else (content[:max_chars] + "\n...(truncated)")
        text = "\n".join(
            [
                "%s file alert" % prefix,
                "path=%s" % ap,
                "",
                body,
            ]
        )
        _send_channel_notification(cfg, "file_watch", key, text, dedup=True)
        _save_state_json(state_path, {"hash": content_hash, "path": ap, "updated_at": int(time.time())})
