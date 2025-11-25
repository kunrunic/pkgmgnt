from __future__ import print_function
"""Watcher/daemon scaffold."""

import time


def run(cfg, run_once=False):
    """
    Basic poller placeholder. Future work: inotify/watchdog and pkg status checks.
    """
    interval = cfg.get("watch", {}).get("interval_sec", 60)
    print("[watch] starting poller interval=%ss once=%s" % (interval, run_once))
    if run_once:
        _tick(cfg)
        return
    while True:
        _tick(cfg)
        time.sleep(interval)


def _tick(cfg):
    print("[watch] tick (stub) cfg=%s" % cfg.get("pkg_release_root"))
