from __future__ import print_function
"""Configuration helpers for the pkg manager scaffold."""

import glob
import os
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

collectors:
  enabled: ["checksums"]

actions:
  # action_name: list of commands (cmd required, cwd/env optional)
  export_cksum:
    - cmd: python cksum_excel.py
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
    "sources": [],
    "source": {"exclude": []},
    "artifacts": {"root": None, "targets": [], "exclude": []},
    "watch": {"interval_sec": 60, "on_change": []},
    "collectors": {"enabled": ["checksums"]},
    "actions": {},
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
    return {"interval_sec": interval, "on_change": on_change}


def _validate_main_config(data):
    if not isinstance(data, dict):
        raise RuntimeError("main config must be a mapping")
    cfg = _deep_merge(MAIN_DEFAULTS, data)

    pkg_root = cfg.get("pkg_release_root")
    if not pkg_root or not isinstance(pkg_root, (str, bytes)):
        raise RuntimeError("pkg_release_root is required (path string)")
    cfg["pkg_release_root"] = str(pkg_root)

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
        with open(target, "w") as f:
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
        with open(target, "w") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=True)
    print("[create-pkg] wrote pkg config to %s" % target)


def load_pkg_config(path):
    """Load a pkg.yaml file."""
    if yaml is None:
        raise RuntimeError("PyYAML not installed; cannot read %s" % path)
    abs_path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(abs_path):
        raise RuntimeError("pkg config not found: %s" % abs_path)
    with open(abs_path, "r") as f:
        return yaml.safe_load(f) or {}


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
    with open(abs_path, "r") as f:
        data = yaml.safe_load(f) or {}
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
        collectors.enabled: default collectors to run per pkg
        actions: mapping action_name -> list of command entries with:
          - cmd: shell command string (required, often relative to cwd)
          - cwd: working directory (optional)
          - env: key/value env overrides for that command only (optional)
        """
    ).strip()
