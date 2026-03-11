from __future__ import print_function
"""CLI entrypoint scaffold for the pkg manager."""

import os
import sys
import io
import time
import hashlib
from contextlib import redirect_stdout

try:
    import argparse
except Exception:
    argparse = None

from . import config, snapshot, release, watch, detection, __version__


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
        "snapshot", help="take a standalone snapshot (does not modify baseline)"
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


def _add_detect(sub):
    p = sub.add_parser("detect", help="detect unmanaged or not-yet-updated changes")
    p.add_argument(
        "--config",
        default=None,
        help="config file path (default: auto-discover under %s)" % config.BASE_DIR,
    )
    p.set_defaults(func=_handle_detect)


def _add_telegram(sub):
    p = sub.add_parser("telegram", help="telegram registration/approval helpers")
    p.add_argument(
        "--config",
        default=None,
        help="config file path (default: auto-discover under %s)" % config.BASE_DIR,
    )
    tsp = p.add_subparsers(dest="telegram_cmd")

    p_poll = tsp.add_parser("poll", help="poll telegram bot updates and process registration commands")
    p_poll.add_argument("--once", action="store_true", help="process one poll cycle then exit")
    p_poll.set_defaults(func=_handle_telegram_poll)

    p_list = tsp.add_parser("list", help="show approved/pending telegram subscribers")
    p_list.set_defaults(func=_handle_telegram_list)

    p_ap = tsp.add_parser("approve", help="approve pending subscriber")
    p_ap.add_argument("chat_id", help="target chat id")
    p_ap.set_defaults(func=_handle_telegram_approve)

    p_rj = tsp.add_parser("reject", help="reject pending subscriber")
    p_rj.add_argument("chat_id", help="target chat id")
    p_rj.set_defaults(func=_handle_telegram_reject)


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
        "--release",
        action="store_true",
        help="finalize the latest release bundle (tar + move to HISTORY)",
    )
    p.add_argument(
        "--cancel",
        help="cancel a finalized release and restore it to active (e.g. v0.0.2 or release.v0.0.2)",
    )
    p.add_argument(
        "--root",
        help="scope release/cancel to a specific release root (e.g. SYS_2)",
    )
    p.add_argument(
        "--cancel-force",
        action="store_true",
        help="remove active release dirs before canceling",
    )
    p.add_argument(
        "--cancel-clean-history",
        action="store_true",
        help="remove release history entries after cancel (implies --cancel-force)",
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


def _add_delete_pkg(sub):
    p = sub.add_parser("delete-pkg", help="delete a closed pkg from local state")
    p.add_argument("pkg_id", help="package identifier to delete (closed only)")
    p.add_argument(
        "--config",
        default=None,
        help="config file path (default: auto-discover under %s)" % config.BASE_DIR,
    )
    p.set_defaults(func=_handle_delete_pkg)


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


def build_parser():
    if argparse is None:
        raise RuntimeError("argparse not available; install argparse")
    parser = argparse.ArgumentParser(
        prog="pkgmgr",
        description="Pkg manager CLI v%s" % __version__,
    )
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
    _add_snapshot(sub)
    _add_create_pkg(sub)
    _add_update_pkg(sub)
    _add_close_pkg(sub)
    _add_delete_pkg(sub)
    _add_watch(sub)
    _add_actions(sub)
    _add_detect(sub)
    _add_telegram(sub)
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
    _run_auto_actions(cfg, "create_pkg", config_path=args.config, context={"pkg_id": args.pkg_id, "event": "create_pkg"})
    watch.notify_lifecycle_event(cfg, "create_pkg", pkg_id=args.pkg_id)
    return 0

def _handle_update_pkg(args):
    cfg = config.load_main(args.config)
    if args.cancel_clean_history and not args.cancel:
        raise RuntimeError("--cancel-clean-history requires --cancel")
    if args.cancel:
        if args.release:
            raise RuntimeError("cannot use --release with --cancel")
        cancel_force = bool(args.cancel_force)
        if args.cancel_clean_history:
            cancel_force = True
        name, roots = release.list_cancel_targets(cfg, args.pkg_id, args.cancel)
        if not roots and not args.cancel_clean_history:
            raise RuntimeError("release not found: %s" % name)
        if not args.cancel_clean_history:
            prompt = (
                "[cancel] history will remain in web. Use --cancel-clean-history to remove it.\n"
                "[cancel] continue without cleaning history? [y/N]: "
            )
            answer = input(prompt).strip().lower()
            if answer not in ("y", "yes"):
                print("[cancel] skipped; example:")
                print("[cancel]  pkgmgr update-pkg %s --cancel %s --root %s --cancel-clean-history" % (args.pkg_id, name, (args.root or roots[0])))
                return 0
        if args.root:
            if args.root not in roots and not args.cancel_clean_history:
                raise RuntimeError("release not found for root %s: %s" % (args.root, name))
        elif len(roots) > 1:
            prompt = "[cancel] release %s found in roots: %s. Proceed cancel all? [y/N]: " % (name, ", ".join(roots))
            answer = input(prompt).strip().lower()
            if answer not in ("y", "yes"):
                print("[cancel] skipped")
                print("[cancel] single root cancel example")
                print("[cancel]  pkgmgr update-pkg %s --cancel %s --root %s" % (args.pkg_id, name, roots[0]))
                if len(roots) > 1:
                    print("[cancel]  pkgmgr update-pkg %s --cancel %s --root %s" % (args.pkg_id, name, roots[1]))
                print("[cancel] history cleanup example")
                print("[cancel]  pkgmgr update-pkg %s --cancel %s --root %s --cancel-clean-history" % (args.pkg_id, name, roots[0]))
                return 0
        release.cancel_pkg_release(
            cfg,
            args.pkg_id,
            args.cancel,
            root_name=args.root,
            force=cancel_force,
            clean_history=bool(args.cancel_clean_history),
        )
        if not args.cancel_clean_history:
            print("[cancel] history not cleaned; use --cancel-clean-history to remove release history entries")
        _run_auto_actions(
            cfg,
            "cancel_pkg_release",
            config_path=args.config,
            context={"pkg_id": args.pkg_id, "event": "cancel_pkg_release", "release": args.cancel},
        )
        watch.notify_lifecycle_event(
            cfg,
            "cancel_pkg_release",
            pkg_id=args.pkg_id,
            details={"release": args.cancel, "root": args.root or "all"},
        )
        return 0
    if args.release:
        active_roots = release.list_active_release_roots(cfg, args.pkg_id)
        if not active_roots:
            print("[update-pkg] no active release; run `pkgmgr update-pkg %s` first" % args.pkg_id)
            return 0
        if args.root:
            if args.root not in active_roots:
                raise RuntimeError("active release not found for root %s" % args.root)
            roots = [args.root]
        else:
            roots = active_roots
            if len(active_roots) > 1:
                prompt = "[release] active roots: %s. Proceed finalize all? [y/N]: " % ", ".join(active_roots)
                answer = input(prompt).strip().lower()
                if answer not in ("y", "yes"):
                    print("[release] skipped; use --root to finalize a single root")
                    print("[release] single root release example")
                    print("[release]  pkgmgr update-pkg %s --release --root %s" % (args.pkg_id, active_roots[0]))
                    if len(active_roots) > 1:
                        print("[release]  pkgmgr update-pkg %s --release --root %s" % (args.pkg_id, active_roots[1]))
                    return 0
        release.finalize_pkg_release(cfg, args.pkg_id, roots=roots)
        _run_auto_actions(cfg, "update_pkg_release", config_path=args.config, context={"pkg_id": args.pkg_id, "event": "update_pkg_release"})
        watch.notify_lifecycle_event(
            cfg, "update_pkg_release", pkg_id=args.pkg_id, details={"roots": ",".join(roots)}
        )
        return 0
    release.update_pkg(cfg, args.pkg_id)
    _run_auto_actions(cfg, "update_pkg", config_path=args.config, context={"pkg_id": args.pkg_id, "event": "update_pkg"})
    watch.notify_lifecycle_event(cfg, "update_pkg", pkg_id=args.pkg_id)
    return 0


def _handle_close_pkg(args):
    cfg = config.load_main(args.config)
    release.close_pkg(cfg, args.pkg_id)
    _run_auto_actions(cfg, "close_pkg", config_path=args.config, context={"pkg_id": args.pkg_id, "event": "close_pkg"})
    watch.notify_lifecycle_event(cfg, "close_pkg", pkg_id=args.pkg_id)
    return 0


def _handle_delete_pkg(args):
    cfg = config.load_main(args.config)
    release.delete_pkg(cfg, args.pkg_id)
    _run_auto_actions(cfg, "delete_pkg", config_path=args.config, context={"pkg_id": args.pkg_id, "event": "delete_pkg"})
    watch.notify_lifecycle_event(cfg, "delete_pkg", pkg_id=args.pkg_id)
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


def _handle_actions(args):
    cfg = config.load_main(args.config)
    if not args.name:
        actions = cfg.get("actions", {}) or {}
        if not actions:
            print("[actions] no actions configured")
            return 0
        _print_actions(actions)
        return 0
    release.run_actions(
        cfg, [args.name], extra_args=args.action_args, config_path=args.config
    )
    return 0


def _handle_detect(args):
    cfg = config.load_main(args.config)
    buf = io.StringIO()
    with redirect_stdout(buf):
        result = detection.run(cfg)
    text = buf.getvalue()
    if text:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
    _save_detect_report(cfg, text)
    return int(result.get("exit_code", 0))


def _handle_telegram_poll(args):
    cfg = config.load_main(args.config)
    return watch.telegram_poll(cfg, run_once=bool(args.once))


def _handle_telegram_list(args):
    cfg = config.load_main(args.config)
    return watch.telegram_list(cfg)


def _handle_telegram_approve(args):
    cfg = config.load_main(args.config)
    return watch.telegram_approve(cfg, args.chat_id)


def _handle_telegram_reject(args):
    cfg = config.load_main(args.config)
    return watch.telegram_reject(cfg, args.chat_id)


def _save_detect_report(cfg, text):
    detection_cfg = cfg.get("detection") if isinstance(cfg.get("detection"), dict) else {}
    report_path = detection_cfg.get("report_file")
    if not report_path:
        return
    out_path = os.path.abspath(os.path.expanduser(str(report_path)))
    parent = os.path.dirname(out_path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent)
    existing = None
    if os.path.isfile(out_path):
        try:
            with open(out_path, "r", encoding="utf-8", errors="replace") as f:
                existing = f.read()
        except Exception:
            existing = None
    if existing == text:
        return
    if existing is not None:
        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        backup_path = out_path + ".bak_" + ts
        with open(backup_path, "w", encoding="utf-8") as bf:
            bf.write(existing)
        digest = hashlib.sha256(existing.encode("utf-8")).hexdigest()[:12]
        print("[detect] backup saved: %s (sha256=%s)" % (backup_path, digest))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text or "")
    print("[detect] report saved: %s" % out_path)


def _run_auto_actions(cfg, event, config_path=None, context=None):
    auto_actions = cfg.get("auto_actions") or {}
    names = auto_actions.get(event) or []
    if not names:
        return []
    return release.run_actions(cfg, names, config_path=config_path, context=context)


def _print_actions(actions):
    ordered = sorted([name for name in actions.keys() if not str(name).startswith("auto_")])
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
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
