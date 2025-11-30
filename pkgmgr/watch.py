from __future__ import print_function
"""Watcher/daemon scaffold."""

import json
import os
import time

from . import snapshot, release, points


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
            return
        print("[watch] changes detected: added=%d modified=%d deleted=%d" % (len(diff["added"]), len(diff["modified"]), len(diff["deleted"])))
    else:
        print("[watch] no previous snapshot; treating as initial run")
        diff = None

    actions_to_run = (cfg.get("watch") or {}).get("on_change", []) or []
    results = []
    if actions_to_run:
        results = release.run_actions(cfg, actions_to_run)
    else:
        print("[watch] no watch.on_change actions configured")

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
