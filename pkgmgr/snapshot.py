from __future__ import print_function
"""Snapshot scaffolding.

This module will house hash/mtime scanning for sources/install/pkg dirs.
"""

import os


def create_baseline(cfg):
    """
    Placeholder for baseline snapshot creation.
    Will use cfg['sources'], cfg['install'], cfg['pkg_release_root'].
    """
    roots = {
        "sources": cfg.get("sources", []),
        "install": cfg.get("install", {}).get("targets", []),
        "release": cfg.get("pkg_release_root"),
    }
    print("[init-snap] baseline placeholder. roots=%s" % roots)
    # TODO: implement hashing and storage under pkgmgr/state


def diff_snapshots(base, latest):
    """Placeholder diff helper."""
    print("[snapshot] diff placeholder: base=%s latest=%s" % (base, latest))
    return {}
