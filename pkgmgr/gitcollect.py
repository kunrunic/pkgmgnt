from __future__ import print_function
"""Git collection scaffolding."""


def collect(cfg, pkg_id):
    """
    Placeholder for git log collection using cfg['git']['keywords'].
    Will dump commits into state/pkg/<id>/commits.json in a future step.
    """
    print("[git] collect stub for pkg=%s keywords=%s" % (pkg_id, cfg.get("git")))
