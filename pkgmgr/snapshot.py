from __future__ import print_function
"""Snapshot utilities: hashing and state persistence."""

import os
import hashlib
import json
import fnmatch
import time

from . import config

STATE_DIR = config.DEFAULT_STATE_DIR


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


def _scan(root, exclude):
    res = {}
    root_abs = os.path.abspath(os.path.expanduser(root))
    if not os.path.exists(root_abs):
        print("[snap] skip missing root: %s" % root_abs)
        return res
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
    return res


def create_baseline(cfg):
    """
    Collect initial baseline snapshot.
    For now scans sources only; artifacts can be added when roots are available.
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
    }

    for root in sources:
        snapshot_data["sources"][root] = _scan(root, src_exclude)

    path = os.path.join(STATE_DIR, "baseline.json")
    f = open(path, "w")
    try:
        json.dump(snapshot_data, f, ensure_ascii=False, indent=2, sort_keys=True)
    finally:
        f.close()
    print("[baseline] saved to %s" % path)
    return snapshot_data


def create_snapshot(cfg):
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
    }

    for root in sources:
        snapshot_data["sources"][root] = _scan(root, src_exclude)

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
    def _flatten(snap):
        flat = {}
        for root, entries in (snap or {}).items():
            for rel, meta in (entries or {}).items():
                flat[root + "/" + rel] = meta
        return flat

    a_flat = _flatten(base.get("sources") if base else {})
    b_flat = _flatten(latest.get("sources") if latest else {})
    _diff_map(a_flat, b_flat)

    return {"added": sorted(added), "modified": sorted(modified), "deleted": sorted(deleted)}
