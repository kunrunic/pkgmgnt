from __future__ import print_function
"""Configuration helpers for the pkg manager scaffold."""

import glob
import os
import re
import sys
import textwrap

# Default locations under the user's home directory.
BASE_DIR = os.path.expanduser("~/pkgmgr")
DEFAULT_CONFIG_DIR = os.path.join(BASE_DIR, "config")
DEFAULT_STATE_DIR = os.path.join(BASE_DIR, "local", "state")
DEFAULT_CACHE_DIR = os.path.join(BASE_DIR, "cache")
# Default main config lives under BASE_DIR/config; configs under BASE_DIR
# are also discovered for backward compatibility.
DEFAULT_MAIN_CONFIG = os.path.join(DEFAULT_CONFIG_DIR, "pkgmgr.yaml")
HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(HERE, "templates")


try:
    import yaml  # type: ignore
except Exception:
    yaml = None


MAIN_TEMPLATE = """\
pkg_release_root: ~/PKG/RELEASE
git:
  repo_root: null  # optional override; default is git rev-parse from cwd
  repo_url: "https://github.com/org/repo"
  keyword_prefix: "DEV-CODE:"
sources:
  - /path/to/source-A
  - /path/to/source-B
  
source:
  # glob patterns to exclude from source scanning
  exclude:
    - "**/build/**"
    - "**/*.tmp"
    - "**/bk"
    - "**/*.sc*"
    - "**/unit_test/**"
    - "Jamrules*"
    - "Jamfile*"
    - "**/Jamrules*"
    - "**/Jamfile*"

artifacts:
  root: ~/HOME
  targets: [bin, lib, data]
  # glob patterns to exclude in artifacts area
  exclude:
    - log
    - tmp/**
    - "*.bak"
    - "**/*.tmp"

watch:
  interval_sec: 60
  on_change: []   # optional list of action names to run on change (poller)
  detect: true
  telegram:
    enabled: false
    bot_token: ""
    tls_verify: true
    ca_file: null
    subscribers_file: ~/pkgmgr/config/telegram-subscribers.yaml
    admin_chat_ids: []
    chat_id: ""   # fallback only (read-only compatibility)
    chat_ids: []  # fallback only (read-only compatibility)
    message_prefix: "[pkgmgr]"
    notify_on: [fail, warn]
    dedup: true
    registration:
      enabled: true
      auto_reply: true
      notify_admin_on_start: true
    channels:
      detect:
        enabled: true
        message_file: null
        max_chars: 3800
        wrap_width: 72
        message_file_max_lines: 120
      lifecycle:
        enabled: false
        events: [create_pkg, update_pkg, update_pkg_release, cancel_pkg_release, close_pkg, delete_pkg]
      git:
        enabled: false
        repo_root: null
        branches: []
      jenkins:
        enabled: false
        notify_on: [started, failed, success]
        notify_on_first_seen: false
        jobs: []
      file_watch:
        enabled: false
        max_chars: 3000
        files: []

collectors:
  enabled: ["checksums"]

actions:
  # action_name: list of commands (cmd required, cwd/env optional)
  export_cksum:
    - cmd: python export_cksum.py --pkg-dir /path/to/pkg --excel /path/to/template.xlsx
      cwd: /app/script
      env: { APP_ENV: dev }
  export_world_dev:
    - cmd: python dev_world.py
      cwd: /app/script
  export_world_security:
    - cmd: python security_world.py
      cwd: /app/script
  noti_email:
    - cmd: sh noti_email.sh
      cwd: /app/script

auto_actions:
  create_pkg: []
  update_pkg: []
  update_pkg_release: []
  cancel_pkg_release: []
  delete_pkg: []
  close_pkg: []

detection:
  enabled: true
  system: null
  report_file: ~/pkgmgr/local/state/detect/detect-report.txt
  ignore: []
  fail_on: [TRACKED_CHANGED_NOT_IN_PKG, UNTRACKED_NOT_IN_PKG, AMBIGUOUS_PKG]
  warn_on: [CHANGED_NOT_UPDATED, DELETED_NOT_UPDATED]
"""

PKG_TEMPLATE = """\
pkg:
  id: "<pkg-id>"
  root: "/path/to/release/<pkg-id>"
  status: "open"  # open|closed

include:
  releases: []

git:
  repo_root: null  # optional override; default is git rev-parse from cwd
  keywords: []
  since: null  # e.g. "2024-01-01"
  until: null

collectors:
  enabled: ["checksums"]
"""

MAIN_DEFAULTS = {
    "pkg_release_root": None,
    "git": {"repo_root": None, "repo_url": None, "keyword_prefix": None},
    "sources": [],
    "source": {"exclude": []},
    "artifacts": {"root": None, "targets": [], "exclude": []},
    "watch": {
        "interval_sec": 60,
        "on_change": [],
        "detect": True,
        "telegram": {
            "enabled": False,
            "bot_token": "",
            "tls_verify": True,
            "ca_file": None,
            "subscribers_file": os.path.join(DEFAULT_CONFIG_DIR, "telegram-subscribers.yaml"),
            "admin_chat_ids": [],
            "chat_id": "",
            "chat_ids": [],
            "message_prefix": "[pkgmgr]",
            "notify_on": ["fail", "warn"],
            "dedup": True,
            "registration": {
                "enabled": True,
                "auto_reply": True,
                "notify_admin_on_start": True,
            },
            "channels": {
                "detect": {
                    "enabled": True,
                    "message_file": None,
                    "max_chars": 3800,
                    "wrap_width": 72,
                    "message_file_max_lines": 120,
                },
                "lifecycle": {
                    "enabled": False,
                    "events": [
                        "create_pkg",
                        "update_pkg",
                        "update_pkg_release",
                        "cancel_pkg_release",
                        "close_pkg",
                        "delete_pkg",
                    ],
                },
                "git": {"enabled": False, "repo_root": None, "branches": []},
                "jenkins": {
                    "enabled": False,
                    "notify_on": ["started", "failed", "success"],
                    "notify_on_first_seen": False,
                    "jobs": [],
                },
                "file_watch": {"enabled": False, "max_chars": 3000, "files": []},
            },
        },
    },
    "collectors": {"enabled": ["checksums"]},
    "actions": {},
    "auto_actions": {
        "create_pkg": [],
        "update_pkg": [],
        "update_pkg_release": [],
        "cancel_pkg_release": [],
        "close_pkg": [],
        "delete_pkg": [],
    },
    "detection": {
        "enabled": True,
        "system": None,
        "report_file": os.path.join(DEFAULT_STATE_DIR, "detect", "detect-report.txt"),
        "ignore": [],
        "fail_on": [
            "TRACKED_CHANGED_NOT_IN_PKG",
            "UNTRACKED_NOT_IN_PKG",
            "AMBIGUOUS_PKG",
        ],
        "warn_on": ["CHANGED_NOT_UPDATED", "DELETED_NOT_UPDATED"],
    },
}


def _deep_merge(defaults, overrides):
    merged = dict(defaults or {})
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged.get(key, {}), value)
        else:
            merged[key] = value
    return merged


def _ensure_list(value, field):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _ensure_list_of_strings(value, field):
    raw_list = _ensure_list(value, field)
    result = []
    for idx, item in enumerate(raw_list):
        if item is None:
            continue
        if not isinstance(item, (str, bytes, int, float)):
            raise RuntimeError("expected %s[%d] to be string-like" % (field, idx))
        result.append(str(item))
    return result


def _validate_actions(actions):
    if actions is None:
        return {}
    if not isinstance(actions, dict):
        raise RuntimeError("actions must be a mapping of name -> command list")
    validated = {}
    for name, entry in actions.items():
        if isinstance(entry, dict):
            commands = [entry]
        elif isinstance(entry, (list, tuple)):
            commands = list(entry)
        else:
            raise RuntimeError("action %s must be a mapping or list" % name)
        validated[name] = commands
    return validated


def _validate_watch(watch_cfg):
    watch = watch_cfg if isinstance(watch_cfg, dict) else {}
    interval = watch.get("interval_sec", MAIN_DEFAULTS["watch"]["interval_sec"])
    try:
        interval = int(interval)
        if interval <= 0:
            raise ValueError
    except Exception:
        interval = MAIN_DEFAULTS["watch"]["interval_sec"]
    on_change = _ensure_list_of_strings(watch.get("on_change"), "watch.on_change")
    detect_enabled = watch.get("detect", MAIN_DEFAULTS["watch"]["detect"])
    telegram_cfg = watch.get("telegram") if isinstance(watch.get("telegram"), dict) else {}
    notify_on = _ensure_list_of_strings(
        telegram_cfg.get("notify_on", MAIN_DEFAULTS["watch"]["telegram"]["notify_on"]),
        "watch.telegram.notify_on",
    )
    subscribers_file = str(
        telegram_cfg.get("subscribers_file", MAIN_DEFAULTS["watch"]["telegram"]["subscribers_file"]) or ""
    )
    admin_chat_ids = _ensure_list_of_strings(
        telegram_cfg.get("admin_chat_ids", MAIN_DEFAULTS["watch"]["telegram"]["admin_chat_ids"]),
        "watch.telegram.admin_chat_ids",
    )
    registration_cfg = telegram_cfg.get("registration") if isinstance(telegram_cfg.get("registration"), dict) else {}
    chat_ids = _ensure_list_of_strings(
        telegram_cfg.get("chat_ids", MAIN_DEFAULTS["watch"]["telegram"]["chat_ids"]),
        "watch.telegram.chat_ids",
    )
    chat_id_single = str(telegram_cfg.get("chat_id") or "")
    if chat_id_single and chat_id_single not in chat_ids:
        chat_ids.append(chat_id_single)
    channels_cfg = telegram_cfg.get("channels") if isinstance(telegram_cfg.get("channels"), dict) else {}
    lifecycle_cfg = channels_cfg.get("lifecycle") if isinstance(channels_cfg.get("lifecycle"), dict) else {}
    git_channel_cfg = channels_cfg.get("git") if isinstance(channels_cfg.get("git"), dict) else {}
    jenkins_cfg = channels_cfg.get("jenkins") if isinstance(channels_cfg.get("jenkins"), dict) else {}
    file_watch_cfg = channels_cfg.get("file_watch") if isinstance(channels_cfg.get("file_watch"), dict) else {}
    detect_chan_cfg = channels_cfg.get("detect") if isinstance(channels_cfg.get("detect"), dict) else {}
    jenkins_jobs = jenkins_cfg.get("jobs") if isinstance(jenkins_cfg.get("jobs"), list) else []
    normalized_jobs = []
    for idx, job in enumerate(jenkins_jobs):
        if isinstance(job, str):
            normalized_jobs.append({"name": str(job), "url": str(job), "user": "", "api_token": ""})
            continue
        if not isinstance(job, dict):
            raise RuntimeError("watch.telegram.channels.jenkins.jobs[%d] must be string or mapping" % idx)
        normalized_jobs.append(
            {
                "name": str(job.get("name") or job.get("url") or ""),
                "url": str(job.get("url") or ""),
                "user": str(job.get("user") or ""),
                "api_token": str(job.get("api_token") or ""),
            }
        )

    file_specs = file_watch_cfg.get("files") if isinstance(file_watch_cfg.get("files"), list) else []
    normalized_files = []
    for idx, item in enumerate(file_specs):
        if isinstance(item, str):
            normalized_files.append({"path": str(item), "encoding": "utf-8"})
            continue
        if not isinstance(item, dict):
            raise RuntimeError("watch.telegram.channels.file_watch.files[%d] must be string or mapping" % idx)
        normalized_files.append(
            {
                "path": str(item.get("path") or ""),
                "encoding": str(item.get("encoding") or "utf-8"),
            }
        )
    return {
        "interval_sec": interval,
        "on_change": on_change,
        "detect": bool(detect_enabled),
        "telegram": {
            "enabled": bool(telegram_cfg.get("enabled", MAIN_DEFAULTS["watch"]["telegram"]["enabled"])),
            "bot_token": str(telegram_cfg.get("bot_token") or ""),
            "tls_verify": bool(telegram_cfg.get("tls_verify", MAIN_DEFAULTS["watch"]["telegram"]["tls_verify"])),
            "ca_file": str(telegram_cfg.get("ca_file") or "") or None,
            "subscribers_file": subscribers_file or MAIN_DEFAULTS["watch"]["telegram"]["subscribers_file"],
            "admin_chat_ids": admin_chat_ids,
            "chat_id": str(telegram_cfg.get("chat_id") or ""),
            "chat_ids": chat_ids,
            "message_prefix": str(
                telegram_cfg.get("message_prefix", MAIN_DEFAULTS["watch"]["telegram"]["message_prefix"]) or ""
            ),
            "notify_on": [n.lower() for n in notify_on if n],
            "dedup": bool(telegram_cfg.get("dedup", MAIN_DEFAULTS["watch"]["telegram"]["dedup"])),
            "registration": {
                "enabled": bool(
                    registration_cfg.get(
                        "enabled",
                        MAIN_DEFAULTS["watch"]["telegram"]["registration"]["enabled"],
                    )
                ),
                "auto_reply": bool(
                    registration_cfg.get(
                        "auto_reply",
                        MAIN_DEFAULTS["watch"]["telegram"]["registration"]["auto_reply"],
                    )
                ),
                "notify_admin_on_start": bool(
                    registration_cfg.get(
                        "notify_admin_on_start",
                        MAIN_DEFAULTS["watch"]["telegram"]["registration"]["notify_admin_on_start"],
                    )
                ),
            },
            "channels": {
                "detect": {
                    "enabled": bool(detect_chan_cfg.get("enabled", True)),
                    "message_file": str(detect_chan_cfg.get("message_file") or "") or None,
                    "max_chars": int(detect_chan_cfg.get("max_chars", 3800) or 3800),
                    "wrap_width": int(detect_chan_cfg.get("wrap_width", 72) or 72),
                    "message_file_max_lines": int(detect_chan_cfg.get("message_file_max_lines", 120) or 120),
                },
                "lifecycle": {
                    "enabled": bool(lifecycle_cfg.get("enabled", False)),
                    "events": _ensure_list_of_strings(
                        lifecycle_cfg.get("events", MAIN_DEFAULTS["watch"]["telegram"]["channels"]["lifecycle"]["events"]),
                        "watch.telegram.channels.lifecycle.events",
                    ),
                },
                "git": {
                    "enabled": bool(git_channel_cfg.get("enabled", False)),
                    "repo_root": str(git_channel_cfg.get("repo_root") or "") or None,
                    "branches": _ensure_list_of_strings(
                        git_channel_cfg.get("branches", MAIN_DEFAULTS["watch"]["telegram"]["channels"]["git"]["branches"]),
                        "watch.telegram.channels.git.branches",
                    ),
                },
                "jenkins": {
                    "enabled": bool(jenkins_cfg.get("enabled", False)),
                    "notify_on": [
                        n.lower()
                        for n in _ensure_list_of_strings(
                            jenkins_cfg.get("notify_on", MAIN_DEFAULTS["watch"]["telegram"]["channels"]["jenkins"]["notify_on"]),
                            "watch.telegram.channels.jenkins.notify_on",
                        )
                    ],
                    "notify_on_first_seen": bool(
                        jenkins_cfg.get(
                            "notify_on_first_seen",
                            MAIN_DEFAULTS["watch"]["telegram"]["channels"]["jenkins"]["notify_on_first_seen"],
                        )
                    ),
                    "jobs": normalized_jobs,
                },
                "file_watch": {
                    "enabled": bool(file_watch_cfg.get("enabled", False)),
                    "max_chars": int(file_watch_cfg.get("max_chars", MAIN_DEFAULTS["watch"]["telegram"]["channels"]["file_watch"]["max_chars"]) or 3000),
                    "files": normalized_files,
                },
            },
        },
    }


def _validate_auto_actions(auto_actions):
    cfg = auto_actions if isinstance(auto_actions, dict) else {}
    return {
        "create_pkg": _ensure_list_of_strings(cfg.get("create_pkg"), "auto_actions.create_pkg"),
        "update_pkg": _ensure_list_of_strings(cfg.get("update_pkg"), "auto_actions.update_pkg"),
        "update_pkg_release": _ensure_list_of_strings(cfg.get("update_pkg_release"), "auto_actions.update_pkg_release"),
        "cancel_pkg_release": _ensure_list_of_strings(cfg.get("cancel_pkg_release"), "auto_actions.cancel_pkg_release"),
        "close_pkg": _ensure_list_of_strings(cfg.get("close_pkg"), "auto_actions.close_pkg"),
        "delete_pkg": _ensure_list_of_strings(cfg.get("delete_pkg"), "auto_actions.delete_pkg"),
    }


def _validate_main_config(data):
    if not isinstance(data, dict):
        raise RuntimeError("main config must be a mapping")
    cfg = _deep_merge(MAIN_DEFAULTS, data)

    pkg_root = cfg.get("pkg_release_root")
    if not pkg_root or not isinstance(pkg_root, (str, bytes)):
        raise RuntimeError("pkg_release_root is required (path string)")
    cfg["pkg_release_root"] = str(pkg_root)

    git_cfg = cfg.get("git") if isinstance(cfg.get("git"), dict) else {}
    repo_root = git_cfg.get("repo_root")
    repo_url = git_cfg.get("repo_url")
    keyword_prefix = git_cfg.get("keyword_prefix")
    cfg["git"] = {
        "repo_root": str(repo_root) if repo_root else None,
        "repo_url": str(repo_url) if repo_url else None,
        "keyword_prefix": str(keyword_prefix) if keyword_prefix else None,
    }

    cfg["sources"] = _ensure_list_of_strings(cfg.get("sources"), "sources")
    src = cfg.get("source") if isinstance(cfg.get("source"), dict) else {}
    cfg["source"] = {"exclude": _ensure_list_of_strings(src.get("exclude"), "source.exclude")}

    artifacts = cfg.get("artifacts") if isinstance(cfg.get("artifacts"), dict) else {}
    art_root = artifacts.get("root")
    cfg["artifacts"] = {
        "root": str(art_root) if art_root else None,
        "targets": _ensure_list_of_strings(artifacts.get("targets"), "artifacts.targets"),
        "exclude": _ensure_list_of_strings(artifacts.get("exclude"), "artifacts.exclude"),
    }

    cfg["watch"] = _validate_watch(cfg.get("watch"))

    collectors = cfg.get("collectors") if isinstance(cfg.get("collectors"), dict) else {}
    cfg["collectors"] = {
        "enabled": _ensure_list_of_strings(collectors.get("enabled"), "collectors.enabled")
    }

    cfg["actions"] = _validate_actions(cfg.get("actions"))
    cfg["auto_actions"] = _validate_auto_actions(cfg.get("auto_actions"))
    detection_cfg = cfg.get("detection") if isinstance(cfg.get("detection"), dict) else {}
    enabled = detection_cfg.get("enabled", True)
    cfg["detection"] = {
        "enabled": bool(enabled),
        "system": str(detection_cfg.get("system") or "") or None,
        "report_file": str(
            detection_cfg.get("report_file", MAIN_DEFAULTS["detection"]["report_file"]) or ""
        )
        or None,
        "ignore": _ensure_list_of_strings(detection_cfg.get("ignore"), "detection.ignore"),
        "fail_on": _ensure_list_of_strings(detection_cfg.get("fail_on"), "detection.fail_on"),
        "warn_on": _ensure_list_of_strings(detection_cfg.get("warn_on"), "detection.warn_on"),
    }

    return cfg


def _load_template_file(filename, fallback):
    """Try loading a template file under pkgmgr/templates; fallback to inline default."""
    path = os.path.join(TEMPLATE_DIR, filename)
    try:
        f = open(path, "r")
        try:
            return f.read()
        finally:
            f.close()
    except Exception:
        return fallback


def write_template(path=None):
    """Write the main pkgmgr.yaml template. Returns True if written."""
    path = path or DEFAULT_MAIN_CONFIG
    target = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
    if os.path.exists(target):
        print("[make-config] config already exists at %s; remove it and re-run" % target)
        return False
    parent = os.path.dirname(target)
    if parent and not os.path.exists(parent):
        os.makedirs(parent)
    content = _load_template_file("pkgmgr.yaml.sample", MAIN_TEMPLATE)
    with open(target, "w") as f:
        f.write(content)
    print("[make-config] wrote template to %s" % target)
    return True


def write_pkg_template(path, pkg_id=None, pkg_root=None, include_releases=None, git_cfg=None, collectors_enabled=None):
    """
    Write a pkg.yaml file. When pkg_id/pkg_root provided, render with those values;
    otherwise fall back to the static template.
    """
    target = os.path.abspath(path)
    parent = os.path.dirname(target)
    if parent and not os.path.exists(parent):
        os.makedirs(parent)

    if pkg_id is None or pkg_root is None or yaml is None:
        content = _load_template_file("pkg.yaml.sample", PKG_TEMPLATE)
        with open(target, "w", encoding="euc-kr") as f:
            f.write(content)
    else:
        data = {
            "pkg": {"id": str(pkg_id), "root": os.path.abspath(os.path.expanduser(pkg_root)), "status": "open"},
            "include": {"releases": include_releases or []},
            "git": {
                "repo_root": (git_cfg or {}).get("repo_root"),
                "keywords": _ensure_list_of_strings((git_cfg or {}).get("keywords"), "git.keywords"),
                "since": (git_cfg or {}).get("since"),
                "until": (git_cfg or {}).get("until"),
            },
            "collectors": {"enabled": collectors_enabled or ["checksums"]},
        }
        dumped = yaml.safe_dump(data, allow_unicode=True, sort_keys=True)
        lines = dumped.splitlines()
        out_lines = []
        for line in lines:
            out_lines.append(line)
            if line.strip().startswith("repo_root:"):
                out_lines.append("  # pkgmgr.yaml 의 repo_root 값으로 자동 생성됩니다.")
            if line.strip().startswith("releases:"):
                out_lines.append("  # update-pkg 실행 시 추가 항목은 수동으로 include.releases에 입력 필요")
        with open(target, "w", encoding="euc-kr") as f:
            f.write("\n".join(out_lines) + "\n")
    print("[create-pkg] wrote pkg config to %s" % target)


def _load_yaml_with_fallback(path, encodings=None):
    if yaml is None:
        raise RuntimeError("PyYAML not installed; cannot read %s" % path)
    encs = []
    for enc in (encodings or ["utf-8", "euc-kr", "cp949"]):
        norm = str(enc).strip().lower()
        if norm and norm not in encs:
            encs.append(norm)
    with open(path, "rb") as f:
        raw = f.read()
    last_decode_error = None
    for enc in encs:
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError as exc:
            last_decode_error = exc
            continue
        try:
            return yaml.safe_load(text) or {}
        except Exception:
            repaired = _repair_common_yaml_issues(text)
            if repaired != text:
                try:
                    return yaml.safe_load(repaired) or {}
                except Exception:
                    pass
    if last_decode_error:
        raise RuntimeError(
            "failed to decode YAML file: %s (tried: %s)" % (path, ", ".join(encs))
        )
    raise RuntimeError("failed to parse YAML file: %s" % path)


def _repair_common_yaml_issues(text):
    """
    Best-effort repair for frequently observed malformed flow lists, e.g.
      releases: ["A/bin" "A/lib"]
    -> inserts missing commas between adjacent quoted items.
    """
    if not text:
        return text
    repaired = re.sub(r'"\s+"', '", "', text)
    repaired = re.sub(r"'\s+'", "', '", repaired)
    return repaired


def load_pkg_config(path):
    """Load a pkg.yaml file."""
    abs_path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(abs_path):
        raise RuntimeError("pkg config not found: %s" % abs_path)
    return _load_yaml_with_fallback(abs_path)


def discover_main_configs(base_dir=None):
    """
    Find pkgmgr config files under the base directory.
    Search order:
      - <base_dir>/pkgmgr*.yaml (new default)
      - <base_dir>/config/pkgmgr*.yaml (legacy default)
    """
    base = os.path.abspath(os.path.expanduser(base_dir or BASE_DIR))
    search_roots = [base, os.path.join(base, "config")]
    found = []
    seen = set()
    patterns = ["pkgmgr*.yaml", "pkgmgr*.yml"]
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        for pattern in patterns:
            for path in glob.glob(os.path.join(root, pattern)):
                apath = os.path.realpath(os.path.abspath(path))
                if apath not in seen:
                    seen.add(apath)
                    found.append(apath)
    return sorted(found)


def _prompt_to_pick(paths):
    """Interactive selector for multiple configs."""
    print("[config] multiple pkgmgr configs found; pick one:")
    for idx, p in enumerate(paths, 1):
        print("  %d) %s" % (idx, p))
    choice = None
    while choice is None:
        raw = input("Select number (1-%d): " % len(paths)).strip()
        if not raw:
            continue
        try:
            val = int(raw)
            if 1 <= val <= len(paths):
                choice = paths[val - 1]
            else:
                print("  invalid selection")
        except Exception:
            print("  enter a number")
    return choice


def resolve_main_config(path=None, base_dir=None, allow_interactive=True):
    """
    Resolve main config path with discovery and optional interactive choice.
    - If `path` is provided, return it as-is (expanded/abs).
    - Otherwise search under BASE_DIR for pkgmgr*.yaml.
      - none -> instruct user to create or pass --config
      - one  -> return it
      - many -> prompt (tty) or raise (non-tty)
    """
    if path:
        return os.path.realpath(os.path.abspath(os.path.expanduser(path)))
    configs = discover_main_configs(base_dir=base_dir)
    if not configs:
        raise RuntimeError(
            "no pkgmgr config found under %s; run `pkgmgr make-config` "
            "or pass --config" % os.path.abspath(os.path.expanduser(base_dir or BASE_DIR))
        )
    if len(configs) == 1:
        return configs[0]

    msg = "multiple pkgmgr configs found: %s" % ", ".join(configs)
    if allow_interactive and sys.stdin.isatty():
        return _prompt_to_pick(configs)
    raise RuntimeError(msg + "; specify one with --config")


def load_main(path=None, base_dir=None, allow_interactive=True):
    """
    Load and validate the main config YAML.
    If PyYAML is missing, raise a clear error so installation can add it.
    """
    path = resolve_main_config(
        path=path, base_dir=base_dir, allow_interactive=allow_interactive
    )
    if yaml is None:
        raise RuntimeError(
            "PyYAML not installed; install it or keep using templates manually"
        )
    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path):
        raise RuntimeError("config not found: %s" % abs_path)
    data = _load_yaml_with_fallback(abs_path)
    return _validate_main_config(data)


def describe_expected_fields():
    """Return a help string for the main config layout."""
    return textwrap.dedent(
        """
        pkg_release_root: root directory where pkg/<id> will live
        sources: list of source roots to watch
        source.exclude: glob patterns to skip under sources (supports **, *.ext)
        artifacts.targets: top-level artifacts (bin/lib/data) to include
        artifacts.exclude: glob patterns for dirs/files to skip (supports **, *.ext)
        watch.interval_sec: poll interval for the watcher
        watch.on_change: action names to run when changes are detected
        watch.detect: run detection during watch tick (default: true)
        watch.telegram.enabled: send watch/detection summary to Telegram
        watch.telegram.bot_token: Telegram bot token
        watch.telegram.tls_verify: verify Telegram API TLS certificate (default: true)
        watch.telegram.ca_file: optional custom CA bundle path for Telegram TLS verification
        watch.telegram.subscribers_file: telegram subscriber registry YAML path
        watch.telegram.admin_chat_ids: admin chat ids allowed to approve/reject subscribers
        watch.telegram.chat_id/chat_ids: fallback recipients (read-only compatibility)
        watch.telegram.registration.enabled: enable /start approval workflow for telegram poller
        watch.telegram.registration.auto_reply: auto send 안내 message for start/approve/reject commands
        watch.telegram.registration.notify_admin_on_start: notify admins when a new /start request arrives
        watch.telegram.message_prefix: message prefix text
        watch.telegram.notify_on: one or more of fail/warn/changes/all
        watch.telegram.dedup: suppress duplicate message bodies
        collectors.enabled: default collectors to run per pkg
        actions: mapping action_name -> list of command entries with:
          - cmd: shell command string (required, often relative to cwd)
          - cwd: working directory (optional)
          - env: key/value env overrides for that command only (optional)
        auto_actions: mapping of lifecycle events to action names (create_pkg/update_pkg/update_pkg_release/cancel_pkg_release/close_pkg/delete_pkg)
        detection.enabled: enable detection flow
        detection.system: system/equipment label included in detection report
        detection.report_file: detect text report output path (auto backup on changed content)
        detection.ignore: path patterns to skip during detection
        detection.fail_on: status codes that should fail CI/command
        detection.warn_on: status codes that should be warning-only
        git.repo_root: override repo root for git scanning (optional)
        git.repo_url: base repository URL for commit links (per system)
        git.keyword_prefix: commit prefix used with git.keywords (e.g. "DEV-CODE:")
        """
    ).strip()
