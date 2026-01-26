from __future__ import print_function

import argparse
import os
import shutil
import sys
import socket
import subprocess
import tempfile


def _default_src():
    home = os.path.expanduser("~")
    return os.path.join(home, "pkgmgr", "local", "state")


def _copy_tree(src, dest):
    for base, dirs, files in os.walk(src):
        rel = os.path.relpath(base, src)
        dest_dir = dest if rel == "." else os.path.join(dest, rel)
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)
        for name in files:
            s = os.path.join(base, name)
            d = os.path.join(dest_dir, name)
            shutil.copy2(s, d)
        for name in dirs:
            d = os.path.join(dest_dir, name)
            if not os.path.exists(d):
                os.makedirs(d)


def _default_release_root():
    home = os.path.expanduser("~")
    return os.path.join(home, "PKG", "RELEASE")


def _list_pkg_ids(src_state_root):
    pkg_dir = os.path.join(src_state_root, "pkg")
    if not os.path.isdir(pkg_dir):
        return []
    return sorted([name for name in os.listdir(pkg_dir) if os.path.isdir(os.path.join(pkg_dir, name))])


def _copy_export_dirs(release_root, dest_state_root, allowed_pkg_ids=None):
    if not os.path.isdir(release_root):
        return
    pkg_root = os.path.join(dest_state_root, "pkg")
    if not os.path.exists(pkg_root):
        os.makedirs(pkg_root)
    for name in os.listdir(release_root):
        pkg_dir = os.path.join(release_root, name)
        if not os.path.isdir(pkg_dir):
            continue
        if allowed_pkg_ids is not None and name not in allowed_pkg_ids:
            continue
        export_dir = os.path.join(pkg_dir, "export")
        if not os.path.isdir(export_dir):
            continue
        dest_export = os.path.join(pkg_root, name, "export")
        _copy_tree(export_dir, dest_export)


def _prune_empty_dirs(root_dir):
    for base, dirs, files in os.walk(root_dir, topdown=False):
        if files:
            continue
        if not dirs and base != root_dir:
            os.rmdir(base)


def _list_release_tars(release_dir):
    items = []
    for base, _, files in os.walk(release_dir):
        for fname in files:
            if not fname.endswith(".tar"):
                continue
            src = os.path.join(base, fname)
            rel = os.path.relpath(src, release_dir)
            items.append((src, rel))
    return items


def _copy_release_tars(release_root, dest_state_root, allowed_pkg_ids=None):
    if not os.path.isdir(release_root):
        return
    pkg_root = os.path.join(dest_state_root, "pkg")
    if not os.path.exists(pkg_root):
        os.makedirs(pkg_root)
    for name in os.listdir(release_root):
        pkg_dir = os.path.join(release_root, name)
        if not os.path.isdir(pkg_dir):
            continue
        if allowed_pkg_ids is not None and name not in allowed_pkg_ids:
            continue
        release_dir = os.path.join(pkg_dir, "release")
        expected = set()
        if os.path.isdir(release_dir):
            for src, rel in _list_release_tars(release_dir):
                expected.add(rel)
                dest_tar = os.path.join(pkg_root, name, "release_artifacts", rel)
                dest_parent = os.path.dirname(dest_tar)
                if not os.path.exists(dest_parent):
                    os.makedirs(dest_parent)
                shutil.copy2(src, dest_tar)
        dest_artifacts = os.path.join(pkg_root, name, "release_artifacts")
        if os.path.isdir(dest_artifacts):
            for base, _, files in os.walk(dest_artifacts):
                for fname in files:
                    if not fname.endswith(".tar"):
                        continue
                    rel = os.path.relpath(os.path.join(base, fname), dest_artifacts)
                    if rel in expected:
                        continue
                    os.remove(os.path.join(base, fname))
            _prune_empty_dirs(dest_artifacts)


def _list_readmes(pkg_dir):
    readmes = {}
    root_readme = os.path.join(pkg_dir, "README.txt")
    if os.path.isfile(root_readme):
        readmes["root"] = root_readme
    for name in os.listdir(pkg_dir):
        subdir = os.path.join(pkg_dir, name)
        if not os.path.isdir(subdir):
            continue
        candidate = os.path.join(subdir, "README.txt")
        if os.path.isfile(candidate):
            readmes[name] = candidate
    return readmes


def _copy_readme_files(release_root, dest_state_root, system_name, allowed_pkg_ids=None):
    if not os.path.isdir(release_root):
        return
    pkg_root = os.path.join(dest_state_root, "pkg")
    if not os.path.exists(pkg_root):
        os.makedirs(pkg_root)
    for name in os.listdir(release_root):
        pkg_dir = os.path.join(release_root, name)
        if not os.path.isdir(pkg_dir):
            continue
        if allowed_pkg_ids is not None and name not in allowed_pkg_ids:
            continue
        readmes = _list_readmes(pkg_dir)
        if not readmes:
            continue
        for root, src in readmes.items():
            dest_readme = os.path.join(pkg_root, name, "readme", root, "README.txt")
            dest_parent = os.path.dirname(dest_readme)
            if not os.path.exists(dest_parent):
                os.makedirs(dest_parent)
            shutil.copy2(src, dest_readme)


def export_pkgstore(src, dest, clean=False, release_root=None, system_name=None):
    if not os.path.isdir(src):
        raise RuntimeError("source not found: %s" % src)
    if clean and os.path.exists(dest):
        shutil.rmtree(dest)
    if not os.path.exists(dest):
        os.makedirs(dest)
    _copy_tree(src, dest)
    if release_root:
        allowed_pkg_ids = _list_pkg_ids(src)
        _copy_export_dirs(release_root, dest, allowed_pkg_ids=allowed_pkg_ids)
        _copy_release_tars(release_root, dest, allowed_pkg_ids=allowed_pkg_ids)
        _copy_readme_files(release_root, dest, system_name, allowed_pkg_ids=allowed_pkg_ids)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export pkgmgr state into a pkgstore directory.")
    parser.add_argument("--src", default=_default_src(), help="pkgmgr state root (default: ~/pkgmgr/local/state)")
    parser.add_argument("--dest", help="pkgstore destination root (will create /state)")
    parser.add_argument("--clean", action="store_true", help="clean destination state before export")
    parser.add_argument("--release-root", default=_default_release_root(), help="PKG/RELEASE root (default: ~/PKG/RELEASE)")
    parser.add_argument("--system", help="system identifier (writes to pkgstore/state/systems/<system>)")
    parser.add_argument("--push", help="rsync target like user@host (pushes to remote)")
    parser.add_argument("--remote-dest", default="~/data/pkgstore", help="remote pkgstore root (default: ~/data/pkgstore)")
    parser.add_argument("--identity", help="ssh private key path for rsync (optional)")
    parser.add_argument("--debug", action="store_true", help="print debug info about source contents")
    args = parser.parse_args(argv)
    if not args.dest and not args.push:
        parser.error("--dest is required when --push is not set")

    src = os.path.abspath(os.path.expanduser(args.src))
    tmp_root = None
    if args.dest:
        dest_root = os.path.abspath(os.path.expanduser(args.dest))
    else:
        tmp_root = tempfile.mkdtemp(prefix="pkgstore_")
        dest_root = tmp_root
    system_name = args.system or socket.gethostname()
    if system_name:
        dest_state = os.path.join(dest_root, "state", "systems", system_name)
    else:
        dest_state = os.path.join(dest_root, "state")
    release_root = os.path.abspath(os.path.expanduser(args.release_root)) if args.release_root else None

    if args.debug:
        try:
            items = _list_pkg_ids(src)
        except Exception:
            items = []
        print("[export_pkgstore] src=%s pkg=%s" % (src, ", ".join(items) or "-"))
    export_pkgstore(
        src,
        dest_state,
        clean=args.clean,
        release_root=release_root,
        system_name=system_name,
    )
    print("[export_pkgstore] synced %s -> %s" % (src, dest_state))

    if args.push:
        remote_root = args.remote_dest.rstrip("/")
        if system_name:
            remote_state = "%s/state/systems/%s" % (remote_root, system_name)
        else:
            remote_state = "%s/state" % remote_root
        src_dir = dest_state.rstrip("/") + "/"
        subprocess.check_call(
            ["ssh", args.push, "mkdir", "-p", remote_state]
        )
        rsync_cmd = ["rsync", "-avzc", "--delete"]
        if args.identity:
            rsync_cmd.extend(["-e", "ssh -i %s" % args.identity])
        rsync_cmd.extend([src_dir, "%s:%s" % (args.push, remote_state)])
        print("[export_pkgstore] rsync -> %s" % (remote_state,))
        subprocess.check_call(rsync_cmd)
    else:
        print("[export_pkgstore] push skipped (no --push)")
    if tmp_root:
        shutil.rmtree(tmp_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
