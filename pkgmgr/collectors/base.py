from __future__ import print_function
"""Collector interface definitions."""


class CollectorResult(dict):
    """Lightweight result mapping for collector outputs."""


class Collector:
    """Base collector contract."""

    name = "base"

    def run(self, pkg_ctx, cfg):
        raise NotImplementedError
