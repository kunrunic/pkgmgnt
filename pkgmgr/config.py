from __future__ import print_function
"""Configuration helpers for the pkg manager scaffold."""

import os
import textwrap

# Default locations under the user's home directory.
BASE_DIR = os.path.expanduser("~/pkmgr")
DEFAULT_CONFIG_DIR = os.path.join(BASE_DIR, "config")
DEFAULT_STATE_DIR = os.path.join(BASE_DIR, "local", "state")
DEFAULT_CACHE_DIR = os.path.join(BASE_DIR, "cache")
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

artifacts:
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
  sources: ["relative/path/from/source/root"]
  artifacts: ["bin", "lib", "data"]
  pkg_dir: ["docs", "notes"]

git:
  keywords: ["BUG", "FEATURE"]
  since: null  # e.g. "2024-01-01"
  until: null

collectors:
  enabled: ["checksums"]
"""


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
    """Write the main pkgmgr.yaml template."""
    path = path or DEFAULT_MAIN_CONFIG
    target = os.path.abspath(path)
    parent = os.path.dirname(target)
    if parent and not os.path.exists(parent):
        os.makedirs(parent)
    content = _load_template_file("pkgmgr.yaml.sample", MAIN_TEMPLATE)
    with open(target, "w") as f:
        f.write(content)
    print("[make-config] wrote template to %s" % target)


def write_pkg_template(path):
    """Write a pkg.yaml template for a specific package."""
    target = os.path.abspath(path)
    parent = os.path.dirname(target)
    if parent and not os.path.exists(parent):
        os.makedirs(parent)
    content = _load_template_file("pkg.yaml.sample", PKG_TEMPLATE)
    with open(target, "w") as f:
        f.write(content)
    print("[create-pkg] wrote pkg template to %s" % target)


def load_main(path=None):
    """
    Load main config YAML. For now this is a thin wrapper; will grow validation.
    If PyYAML is missing, raise a clear error so installation can add it.
    """
    path = path or DEFAULT_MAIN_CONFIG
    if yaml is None:
        raise RuntimeError(
            "PyYAML not installed; install it or keep using templates manually"
        )
    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path):
        raise RuntimeError("config not found: %s" % abs_path)
    with open(abs_path, "r") as f:
        data = yaml.safe_load(f) or {}
    return data


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
