from __future__ import print_function
"""CLI entrypoint scaffold for the pkg manager."""

import os
import sys

try:
    import argparse
except Exception:
    argparse = None

from . import config, snapshot, release, gitcollect, watch, __version__


def _add_make_config(sub):
    p = sub.add_parser("make-config", help="create a pkgmgr.yaml template to edit")
    p.add_argument(
        "-o",
        "--output",
        default=config.DEFAULT_MAIN_CONFIG,
        help="path to write the main config (default: %(default)s)",
    )
    p.set_defaults(func=_handle_make_config)


def _add_install(sub):
    p = sub.add_parser("install", help="prepare environment and collect initial baseline")
    p.add_argument(
        "--config",
        default=None,
        help="config file path (default: auto-discover under %s)" % config.BASE_DIR,
    )
    p.set_defaults(func=_handle_install)


def _add_snapshot(sub):
    p = sub.add_parser(
        "snapshot", help="take a snapshot (baseline update after install)"
    )
    p.add_argument(
        "--config",
        default=None,
        help="config file path (default: auto-discover under %s)" % config.BASE_DIR,
    )
    p.set_defaults(func=_handle_snapshot)

def _add_actions(sub):
    p = sub.add_parser("actions", help="list actions or run a configured action")
    p.add_argument("name", nargs="?", help="action name to run (omit to list)")
    p.add_argument(
        "action_args",
        nargs=argparse.REMAINDER,
        help="args passed to the action (everything after the name)",
    )
    p.set_defaults(func=_handle_actions)


def _add_create_pkg(sub):
    p = sub.add_parser("create-pkg", help="create a pkg folder and template")
    p.add_argument("pkg_id", help="package identifier (e.g. 20240601)")
    p.add_argument(
        "--config",
        default=None,
        help="config file path (default: auto-discover under %s)" % config.BASE_DIR,
    )
    p.set_defaults(func=_handle_create_pkg)


def _add_update_pkg(sub):
    p = sub.add_parser("update-pkg", help="collect git keyword hits and checksums for a pkg")
    p.add_argument("pkg_id", help="package identifier to update")
    p.add_argument(
        "-release",
        "--release",
        action="store_true",
        help="finalize the latest release bundle (tar + move to HISTORY)",
    )
    p.add_argument(
        "--config",
        default=None,
        help="config file path (default: auto-discover under %s)" % config.BASE_DIR,
    )
    p.set_defaults(func=_handle_update_pkg)


def _add_close_pkg(sub):
    p = sub.add_parser("close-pkg", help="mark a pkg as closed and stop watching")
    p.add_argument("pkg_id", help="package identifier to close")
    p.add_argument(
        "--config",
        default=None,
        help="config file path (default: auto-discover under %s)" % config.BASE_DIR,
    )
    p.set_defaults(func=_handle_close_pkg)


def _add_watch(sub):
    p = sub.add_parser("watch", help="start watcher/daemon to monitor pkgs")
    p.add_argument(
        "--config",
        default=None,
        help="config file path (default: auto-discover under %s)" % config.BASE_DIR,
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="run a single poll iteration then exit (useful for cron)",
    )
    p.add_argument("--pkg", help="package id to scope watch/points (optional)")
    p.add_argument(
        "--auto-point",
        action="store_true",
        help="create a checkpoint automatically after changes are handled",
    )
    p.add_argument(
        "--point-label",
        help="label to use when auto-creating a checkpoint (default: watch-auto)",
    )
    p.set_defaults(func=_handle_watch)


def _add_collect(sub):
    p = sub.add_parser("collect", help="run collectors for a pkg")
    p.add_argument("--pkg", required=True, help="package identifier")
    p.add_argument(
        "--collector",
        action="append",
        dest="collectors",
        help="specific collectors to run (default: all enabled)",
    )
    p.add_argument(
        "--config",
        default=None,
        help="config file path (default: auto-discover under %s)" % config.BASE_DIR,
    )
    p.set_defaults(func=_handle_collect)

def _add_point(sub):
    p = sub.add_parser("point", help="create or list checkpoints for a pkg")
    p.add_argument("--pkg", required=True, help="package identifier")
    p.add_argument("--label", help="optional label for this point")
    p.add_argument(
        "--actions-run",
        action="append",
        dest="actions_run",
        help="actions that were executed before creating this point",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="list existing points instead of creating a new one",
    )
    p.add_argument(
        "--config",
        default=None,
        help="config file path (default: auto-discover under %s)" % config.BASE_DIR,
    )
    p.set_defaults(func=_handle_point)


def _add_export(sub):
    p = sub.add_parser("export", help="export pkg data (excel/word/etc)")
    p.add_argument("--pkg", required=True, help="package identifier")
    p.add_argument("--format", choices=["excel", "word", "json"], required=True)
    p.add_argument(
        "--config",
        default=None,
        help="config file path (default: auto-discover under %s)" % config.BASE_DIR,
    )
    p.set_defaults(func=_handle_export)


def build_parser():
    if argparse is None:
        raise RuntimeError("argparse not available; install argparse")
    parser = argparse.ArgumentParser(prog="pkgmgr", description="Pkg manager CLI scaffold")
    # keep %(prog)s for argparse's mapping and append package version
    parser.add_argument("-V", "--version", action="version", version="%(prog)s " + __version__)
    parser.add_argument(
        "--config",
        default=None,
        help="config file path (default: auto-discover under %s)" % config.BASE_DIR,
    )
    sub = parser.add_subparsers(dest="command")

    _add_make_config(sub)
    _add_install(sub)
    _add_create_pkg(sub)
    _add_update_pkg(sub)
    _add_close_pkg(sub)
    _add_actions(sub)
    return parser


def _handle_make_config(args):
    wrote = config.write_template(args.output)
    return 0 if wrote else 1


def _handle_install(args):
    cfg = config.load_main(args.config)
    existing = []
    readme_path = os.path.join(config.BASE_DIR, "README.txt")
    baseline_path = os.path.join(snapshot.STATE_DIR, "baseline.json")
    if os.path.exists(readme_path):
        existing.append(readme_path)
    if os.path.exists(baseline_path):
        existing.append(baseline_path)
    if existing:
        print("[install] existing install artifacts found:")
        for path in existing:
            print("  - %s" % path)
        print("[install] remove these files to re-run install")
        return 1
    print("[install] step 1/2: shell integration")
    release.ensure_environment()
    print("[install] step 2/2: baseline snapshot")
    progress = snapshot.ProgressReporter("scan")
    snapshot.create_baseline(cfg, prompt_overwrite=True, progress=progress)
    return 0


def _handle_snapshot(args):
    cfg = config.load_main(args.config)
    snapshot.create_snapshot(cfg)
    return 0


def _handle_create_pkg(args):
    cfg = config.load_main(args.config)
    release.create_pkg(cfg, args.pkg_id)
    return 0

def _handle_update_pkg(args):
    cfg = config.load_main(args.config)
    if args.release:
        release.finalize_pkg_release(cfg, args.pkg_id)
        return 0
    release.update_pkg(cfg, args.pkg_id)
    return 0


def _handle_close_pkg(args):
    cfg = config.load_main(args.config)
    release.close_pkg(cfg, args.pkg_id)
    return 0


def _handle_watch(args):
    cfg = config.load_main(args.config)
    watch.run(
        cfg,
        run_once=args.once,
        pkg_id=args.pkg,
        auto_point=args.auto_point,
        point_label=args.point_label,
    )
    return 0


def _handle_collect(args):
    cfg = config.load_main(args.config)
    release.collect_for_pkg(cfg, args.pkg, args.collectors)
    return 0


def _handle_export(args):
    cfg = config.load_main(args.config)
    release.export_pkg(cfg, args.pkg, args.format)
    return 0


def _handle_actions(args):
    cfg = config.load_main(args.config)
    if not args.name:
        actions = cfg.get("actions", {}) or {}
        if not actions:
            print("[actions] no actions configured")
            return 0
        _print_actions(actions)
        return 0
    release.run_actions(cfg, [args.name], extra_args=args.action_args)
    return 0


def _print_actions(actions):
    ordered = sorted(actions.keys())
    print("[actions] available:")
    for idx, name in enumerate(ordered, 1):
        entries = actions.get(name) or []
        if isinstance(entries, dict):
            count = 1
        else:
            count = len(entries)
        print("  %d) %s (%d command(s))" % (idx, name, count))
    return ordered

def _handle_point(args):
    cfg = config.load_main(args.config)
    if args.list:
        release.list_points(cfg, args.pkg)
        return 0
    release.create_point(cfg, args.pkg, label=args.label, actions_run=args.actions_run)
    return 0


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    if not argv:
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
