from __future__ import print_function
"""Checkpoint/point helpers for pkg workflow."""

import json
import os
import time

from . import config, snapshot


def _points_root(pkg_id):
    return os.path.join(config.DEFAULT_STATE_DIR, "pkg", str(pkg_id), "points")


def create_point(cfg, pkg_id, label=None, actions_run=None, actions_result=None, snapshot_data=None):
    """
    Create a checkpoint ("point") for the given pkg:
    - takes a snapshot (or uses provided data)
    - writes meta + snapshot under state/pkg/<id>/points/<ts>/
    """
    ts = time.strftime("%Y%m%dT%H%M%S", time.localtime())
    base = _points_root(pkg_id)
    point_dir = os.path.join(base, ts)
    if not os.path.exists(point_dir):
        os.makedirs(point_dir)

    snap = snapshot_data or snapshot.create_snapshot(cfg)
    meta = {
        "pkg_id": str(pkg_id),
        "label": label,
        "created_at": ts,
        "actions_run": actions_run or [],
        "actions_result": actions_result or [],
        "snapshot": "snapshot.json",
    }

    meta_path = os.path.join(point_dir, "meta.json")
    snap_path = os.path.join(point_dir, "snapshot.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2, sort_keys=True)
    with open(snap_path, "w") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2, sort_keys=True)

    print("[point] created %s (label=%s actions=%s)" % (point_dir, label, actions_run or []))
    return point_dir


def load_latest_point(pkg_id):
    """Load latest point's meta and snapshot for a pkg. Returns (meta, snapshot) or (None, None)."""
    base = _points_root(pkg_id)
    if not os.path.exists(base):
        return None, None
    candidates = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))]
    if not candidates:
        return None, None
    latest = sorted(candidates)[-1]
    pdir = os.path.join(base, latest)
    meta_path = os.path.join(pdir, "meta.json")
    snap_path = os.path.join(pdir, "snapshot.json")
    meta = None
    snap = None
    try:
        with open(meta_path, "r") as f:
            meta = json.load(f)
    except Exception:
        meta = {"id": latest}
    try:
        with open(snap_path, "r") as f:
            snap = json.load(f)
    except Exception:
        snap = None
    return meta, snap


def list_points(pkg_id):
    """List available points for a package."""
    base = _points_root(pkg_id)
    if not os.path.exists(base):
        print("[point] no points found for pkg %s" % pkg_id)
        return []

    entries = []
    for name in sorted(os.listdir(base)):
        pdir = os.path.join(base, name)
        if not os.path.isdir(pdir):
            continue
        meta_path = os.path.join(pdir, "meta.json")
        meta = {}
        try:
            with open(meta_path, "r") as f:
                meta = json.load(f)
        except Exception:
            meta = {"created_at": name, "label": None}
        entries.append({"id": name, "path": pdir, "label": meta.get("label"), "created_at": meta.get("created_at")})

    for e in entries:
        print("[point] %s label=%s path=%s" % (e["id"], e["label"], e["path"]))
    return entries
