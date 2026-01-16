from __future__ import print_function
"""Snapshot utilities: hashing and state persistence."""

import os
import hashlib
import json
import fnmatch
import time
import sys

from . import config

STATE_DIR = config.DEFAULT_STATE_DIR


class DuplicateBaselineError(RuntimeError):
    """Raised when attempting to create a baseline that already exists."""


class ProgressReporter(object):
    """TTY-friendly one-line progress reporter (no-op when stdout is not a TTY)."""

    def __init__(self, prefix):
        self.prefix = prefix
        self._is_tty = sys.stdout.isatty()
        self._last_len = 0
        self._label = None
        self._total = 0
        self._current = 0

    def start(self, label, total):
        if not self._is_tty:
            return
        self._label = label
        self._total = int(total or 0)
        self._current = 0
        self._render()

    def advance(self, step=1):
        if not self._is_tty:
            return
        self._current += int(step or 0)
        if self._current > self._total:
            self._current = self._total
        self._render()

    def finish(self):
        if not self._is_tty:
            return
        if self._total == 0:
            self._current = 0
        else:
            self._current = self._total
        self._render(final=True)
        sys.stdout.write("\n")
        sys.stdout.flush()

    def _render(self, final=False):
        total = self._total
        current = self._current
        denom = total if total > 0 else 1
        pct = int((float(current) / float(denom)) * 100)
        if total == 0 and final:
            pct = 100
        bar_len = 30
        filled = int((float(current) / float(denom)) * bar_len)
        bar = "#" * filled + "-" * (bar_len - filled)
        label = self._label or ""
        line = "[%s] %s %d/%d %3d%% [%s]" % (
            self.prefix,
            label,
            current,
            total,
            pct,
            bar,
        )
        pad = " " * max(0, self._last_len - len(line))
        sys.stdout.write("\r" + line + pad)
        sys.stdout.flush()
        self._last_len = len(line)


def _ensure_state_dir():
    if not os.path.exists(STATE_DIR):
        os.makedirs(STATE_DIR)


def _sha256(path, chunk=1024 * 1024):
    h = hashlib.sha256()
    f = open(path, "rb")
    try:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    finally:
        f.close()
    return h.hexdigest()


def _should_skip(relpath, patterns):
    for p in patterns or []:
        if fnmatch.fnmatch(relpath, p):
            return True
    return False


def _count_files(root_abs, exclude):
    total = 0
    for base, _, files in os.walk(root_abs):
        for name in files:
            abspath = os.path.join(base, name)
            rel = os.path.relpath(abspath, root_abs).replace("\\", "/")
            if _should_skip(rel, exclude):
                continue
            total += 1
    return total


def _scan(root, exclude, progress=None, label=None):
    res = {}
    root_abs = os.path.abspath(os.path.expanduser(root))
    if not os.path.exists(root_abs):
        print("[snap] skip missing root: %s" % root_abs)
        return res
    if progress and label:
        total = _count_files(root_abs, exclude)
        progress.start(label, total)
    for base, _, files in os.walk(root_abs):
        for name in files:
            abspath = os.path.join(base, name)
            rel = os.path.relpath(abspath, root_abs).replace("\\", "/")
            if _should_skip(rel, exclude):
                continue
            try:
                st = os.stat(abspath)
                res[rel] = {
                    "hash": _sha256(abspath),
                    "size": int(st.st_size),
                    "mtime": int(st.st_mtime),
                }
            except Exception as e:
                print("[snap] warn skip %s: %s" % (abspath, str(e)))
            if progress:
                progress.advance()
    if progress and label:
        progress.finish()
    return res


def _maybe_keep_existing_baseline(path, prompt_overwrite):
    """
    When prompt_overwrite=True and baseline exists, ask user (if tty) whether to overwrite.
    Raises DuplicateBaselineError when overwrite is declined or non-interactive.
    """
    if not prompt_overwrite:
        return None
    if not os.path.exists(path):
        return None

    if not sys.stdin.isatty():
        msg = "[baseline] existing baseline at %s; non-tty -> refusing overwrite" % path
        raise DuplicateBaselineError(msg)

    ans = input("[baseline] existing baseline at %s; overwrite? [y/N]: " % path).strip().lower()
    if ans not in ("y", "yes"):
        msg = "[baseline] keeping existing baseline; skipped overwrite"
        raise DuplicateBaselineError(msg)
    return None


def _scan_artifacts(cfg, progress=None):
    """
    Scan artifact roots/targets similar to sources.
    artifacts.root: base path (optional)
    artifacts.targets: names or absolute paths
    artifacts.exclude: patterns
    """
    artifacts_cfg = cfg.get("artifacts") or {}
    art_root = artifacts_cfg.get("root")
    art_targets = artifacts_cfg.get("targets") or []
    art_exclude = artifacts_cfg.get("exclude") or []

    result = {}
    base_root = os.path.abspath(os.path.expanduser(art_root)) if art_root else None
    for t in art_targets:
        target_str = str(t)
        if base_root and not os.path.isabs(target_str):
            target_path = os.path.join(base_root, target_str)
        else:
            target_path = target_str
        target_path = os.path.abspath(os.path.expanduser(target_path))
        label = "artifact %s" % target_path
        result[target_path] = _scan(target_path, art_exclude, progress=progress, label=label)
    return result


def create_baseline(cfg, prompt_overwrite=False, progress=None):
    """
    Collect initial baseline snapshot.
    Scans sources and artifacts (if configured).
    """
    _ensure_state_dir()
    sources = cfg.get("sources", []) or []
    src_exclude = (cfg.get("source") or {}).get("exclude", []) or []

    snapshot_data = {
        "meta": {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "type": "baseline",
        },
        "sources": {},
        "artifacts": {},
    }

    for root in sources:
        label = "source %s" % root
        snapshot_data["sources"][root] = _scan(
            root, src_exclude, progress=progress, label=label
        )

    snapshot_data["artifacts"] = _scan_artifacts(cfg, progress=progress)

    path = os.path.join(STATE_DIR, "baseline.json")
    existing = _maybe_keep_existing_baseline(path, prompt_overwrite)
    if existing is not None:
        return existing

    f = open(path, "w")
    try:
        json.dump(snapshot_data, f, ensure_ascii=False, indent=2, sort_keys=True)
    finally:
        f.close()
    print("[baseline] saved to %s" % path)
    return snapshot_data


def create_snapshot(cfg, progress=None):
    """
    Collect a fresh snapshot (for updates).
    """
    _ensure_state_dir()
    sources = cfg.get("sources", []) or []
    src_exclude = (cfg.get("source") or {}).get("exclude", []) or []

    snapshot_data = {
        "meta": {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "type": "snapshot",
        },
        "sources": {},
        "artifacts": {},
    }

    for root in sources:
        label = "source %s" % root
        snapshot_data["sources"][root] = _scan(
            root, src_exclude, progress=progress, label=label
        )

    snapshot_data["artifacts"] = _scan_artifacts(cfg, progress=progress)

    path = os.path.join(STATE_DIR, "snapshot.json")
    f = open(path, "w")
    try:
        json.dump(snapshot_data, f, ensure_ascii=False, indent=2, sort_keys=True)
    finally:
        f.close()
    print("[snap] snapshot saved to %s" % path)
    return snapshot_data


def diff_snapshots(base, latest):
    """Diff two snapshot dicts."""
    added = []
    modified = []
    deleted = []

    def _diff_map(a, b):
        a_keys = set(a.keys())
        b_keys = set(b.keys())
        for k in b_keys - a_keys:
            added.append(k)
        for k in a_keys - b_keys:
            deleted.append(k)
        for k in a_keys & b_keys:
            if a[k].get("hash") != b[k].get("hash"):
                modified.append(k)

    # flatten per-root
    def _flatten_section(snap, section):
        flat = {}
        for root, entries in (snap or {}).get(section, {}).items():
            for rel, meta in (entries or {}).items():
                flat[root + "/" + rel] = meta
        return flat

    a_flat = {}
    b_flat = {}
    for section in ("sources", "artifacts"):
        a_flat.update(_flatten_section(base or {}, section))
        b_flat.update(_flatten_section(latest or {}, section))
    _diff_map(a_flat, b_flat)

    return {"added": sorted(added), "modified": sorted(modified), "deleted": sorted(deleted)}
