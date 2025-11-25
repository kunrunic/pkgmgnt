from __future__ import print_function
"""Checksum collector stub."""

import hashlib
import os

from .base import Collector, CollectorResult


class ChecksumsCollector(Collector):
    name = "checksums"

    def run(self, pkg_ctx, cfg):
        """
        Placeholder: walk pkg_ctx['paths'] and compute sha256.
        pkg_ctx is expected to contain 'paths' list of absolute file paths.
        """
        res = CollectorResult()
        paths = pkg_ctx.get("paths", [])
        for path in paths:
            if not os.path.exists(path):
                continue
            res[path] = sha256_of_file(path)
        return res


def sha256_of_file(path, chunk=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()
