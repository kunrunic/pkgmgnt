from __future__ import print_function
"""CLI entrypoint scaffold for the pkg manager."""

import sys

try:
    import argparse
except Exception:
    argparse = None

from . import config, snapshot, release, gitcollect, watch


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
    p.set_defaults(func=_handle_install)


def _add_snapshot(sub):
    p = sub.add_parser(
        "snapshot", help="take a snapshot (baseline update after install)"
    )
    p.add_argument(
        "--config", default=config.DEFAULT_MAIN_CONFIG, help="config file path"
    )
    p.set_defaults(func=_handle_snapshot)

def _add_actions(sub):
    p = sub.add_parser("actions", help="run one or more configured actions")
    p.add_argument("names", nargs="+", help="action names to run")
    p.add_argument(
        "--config", default=config.DEFAULT_MAIN_CONFIG, help="config file path"
    )
    p.set_defaults(func=_handle_actions)


def _add_create_pkg(sub):
    p = sub.add_parser("create-pkg", help="create a pkg folder and template")
    p.add_argument("pkg_id", help="package identifier (e.g. 20240601)")
    p.add_argument(
        "--config", default=config.DEFAULT_MAIN_CONFIG, help="config file path"
    )
    p.set_defaults(func=_handle_create_pkg)


def _add_close_pkg(sub):
    p = sub.add_parser("close-pkg", help="mark a pkg as closed and stop watching")
    p.add_argument("pkg_id", help="package identifier to close")
    p.add_argument(
        "--config", default=config.DEFAULT_MAIN_CONFIG, help="config file path"
    )
    p.set_defaults(func=_handle_close_pkg)


def _add_watch(sub):
    p = sub.add_parser("watch", help="start watcher/daemon to monitor pkgs")
    p.add_argument(
        "--config", default=config.DEFAULT_MAIN_CONFIG, help="config file path"
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="run a single poll iteration then exit (useful for cron)",
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
        "--config", default=config.DEFAULT_MAIN_CONFIG, help="config file path"
    )
    p.set_defaults(func=_handle_collect)


def _add_export(sub):
    p = sub.add_parser("export", help="export pkg data (excel/word/etc)")
    p.add_argument("--pkg", required=True, help="package identifier")
    p.add_argument("--format", choices=["excel", "word", "json"], required=True)
    p.add_argument(
        "--config", default=config.DEFAULT_MAIN_CONFIG, help="config file path"
    )
    p.set_defaults(func=_handle_export)


def build_parser():
    if argparse is None:
        raise RuntimeError("argparse not available; install argparse")
    parser = argparse.ArgumentParser(prog="pkgmgr", description="Pkg manager CLI scaffold")
    sub = parser.add_subparsers(dest="command")

    _add_make_config(sub)
    _add_install(sub)
    _add_snapshot(sub)
    _add_create_pkg(sub)
    _add_close_pkg(sub)
    _add_watch(sub)
    _add_collect(sub)
    _add_export(sub)
    _add_actions(sub)
    return parser


def _handle_make_config(args):
    config.write_template(args.output)
    return 0


def _handle_install(args):
    cfg = config.load_main(config.DEFAULT_MAIN_CONFIG)
    release.ensure_environment()
    snapshot.create_baseline(cfg)
    return 0


def _handle_snapshot(args):
    cfg = config.load_main(args.config)
    snapshot.create_snapshot(cfg)
    return 0


def _handle_create_pkg(args):
    cfg = config.load_main(args.config)
    release.create_pkg(cfg, args.pkg_id)
    return 0


def _handle_close_pkg(args):
    cfg = config.load_main(args.config)
    release.close_pkg(cfg, args.pkg_id)
    return 0


def _handle_watch(args):
    cfg = config.load_main(args.config)
    watch.run(cfg, run_once=args.once)
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
    release.run_actions(cfg, args.names)
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
