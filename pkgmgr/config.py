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


try:
    import yaml  # type: ignore
except Exception:
    yaml = None


MAIN_TEMPLATE = """\
version: 1

pkg_release_root: ~/PKG/RELEASE
sources:
  - /path/to/source-A
  - /path/to/source-B

install:
  targets: [bin, lib, data]
  exclude: [log, tmp, cache]

watch:
  interval_sec: 60

git:
  keywords: ["FIX", "BUG", "SECURITY"]

collectors:
  enabled: ["checksums"]
"""

PKG_TEMPLATE = """\
pkg:
  id: "<pkg-id>"
  root: "/path/to/release/<pkg-id>"
  status: "open"  # open|closed

include:
  sources: ["relative/path/from/source/root"]
  install: ["bin", "lib", "data"]
  pkg_dir: ["docs", "notes"]

git:
  keywords: ["BUG", "FEATURE"]
  since: null  # e.g. "2024-01-01"
  until: null

collectors:
  enabled: ["checksums"]
"""


def write_template(path=None):
    """Write the main pkgmgr.yaml template."""
    path = path or DEFAULT_MAIN_CONFIG
    target = os.path.abspath(path)
    parent = os.path.dirname(target)
    if parent and not os.path.exists(parent):
        os.makedirs(parent)
    with open(target, "w") as f:
        f.write(MAIN_TEMPLATE)
    print("[make-config] wrote template to %s" % target)


def write_pkg_template(path):
    """Write a pkg.yaml template for a specific package."""
    target = os.path.abspath(path)
    parent = os.path.dirname(target)
    if parent and not os.path.exists(parent):
        os.makedirs(parent)
    with open(target, "w") as f:
        f.write(PKG_TEMPLATE)
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
        version: schema version for future compatibility
        pkg_release_root: root directory where pkg/<id> will live
        sources: list of source roots to watch
        install.targets: top-level install directories to include
        install.exclude: subdirectories to skip
        watch.interval_sec: poll interval for the watcher
        git.keywords: list of keywords/regex for commit collection
        collectors.enabled: default collectors to run per pkg
        """
    ).strip()
