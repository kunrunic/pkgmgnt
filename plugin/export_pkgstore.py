from __future__ import print_function

import argparse
import os
import shutil
import sys
import socket
import subprocess
import tempfile
import re

_RSYNC_SUPPORTS_INFO = None
_SHARED_STATE_FILES = ("pkg-summary.json", "baseline.json")

try:
    from rich.console import Console
    from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn
except Exception:
    Console = None
    Progress = None
    BarColumn = None
    TaskProgressColumn = None
    TextColumn = None


def _bool_env(name):
    val = os.environ.get(name)
    if val is None:
        return False
    return str(val).strip().lower() in ("1", "true", "y", "yes", "on")


class _TextUI(object):
    def __init__(self):
        self._rsync_last = -1

    def step(self, step, total, message):
        pct = int((float(step) / float(total)) * 100) if total else 100
        sys.stdout.write("\r[export_pkgstore] [%d/%d] %3d%% %s" % (step, total, pct, message))
        sys.stdout.flush()

    def done_step(self):
        sys.stdout.write("\n")
        sys.stdout.flush()

    def log(self, msg):
        print(msg)

    def rsync_progress(self, pct):
        if pct != self._rsync_last:
            sys.stdout.write("\r[export_pkgstore][rsync] %3d%%" % pct)
            sys.stdout.flush()
            self._rsync_last = pct

    def rsync_done(self):
        if self._rsync_last >= 0:
            sys.stdout.write("\r[export_pkgstore][rsync] 100%\n")
            sys.stdout.flush()

    def close(self):
        return

    def flush_progress(self):
        return


class _RichUI(object):
    def __init__(self):
        self.console = Console(markup=False)
        self.progress = Progress(
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(bar_width=28),
            TaskProgressColumn(),
            TextColumn("{task.fields[meta]}"),
            console=self.console,
            transient=False,
        )
        self.local_task = self.progress.add_task("export_pkgstore", total=5, meta="")
        self.rsync_task = self.progress.add_task("rsync", total=100, meta="", visible=False)
        self.progress.start()
        self._rsync_visible = False
        self._stopped = False

    def step(self, step, total, message):
        self.progress.update(self.local_task, total=max(total, 1), completed=step, meta=message)
        self.progress.refresh()

    def done_step(self):
        self.progress.refresh()

    def log(self, msg):
        self.console.print(msg)

    def rsync_progress(self, pct):
        if not self._rsync_visible:
            self.progress.update(self.rsync_task, visible=True)
            self._rsync_visible = True
        pct = max(0, min(100, int(pct)))
        self.progress.update(self.rsync_task, completed=pct, meta="")
        self.progress.refresh()

    def rsync_done(self):
        if self._rsync_visible:
            self.progress.update(self.rsync_task, completed=100, meta="done")
            self.progress.refresh()

    def close(self):
        if not self._stopped:
            self.progress.stop()
            self._stopped = True

    def flush_progress(self):
        if not self._stopped:
            self.progress.refresh()
            self.progress.stop()
            self._stopped = True


def _new_ui():
    if Progress is None:
        return _TextUI()
    if _bool_env("PKGMGR_NO_RICH"):
        return _TextUI()
    try:
        if not sys.stdout.isatty():
            return _TextUI()
    except Exception:
        return _TextUI()
    return _RichUI()


def _default_src():
    home = os.path.expanduser("~")
    return os.path.join(home, "pkgmgr", "local", "state")


def _copy_tree(src, dest):
    files_copied = 0
    dirs_created = 0
    for base, dirs, files in os.walk(src):
        rel = os.path.relpath(base, src)
        dest_dir = dest if rel == "." else os.path.join(dest, rel)
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)
            dirs_created += 1
        for name in files:
            s = os.path.join(base, name)
            d = os.path.join(dest_dir, name)
            shutil.copy2(s, d)
            files_copied += 1
        for name in dirs:
            d = os.path.join(dest_dir, name)
            if not os.path.exists(d):
                os.makedirs(d)
                dirs_created += 1
    return files_copied, dirs_created


def _default_release_root():
    home = os.path.expanduser("~")
    return os.path.join(home, "PKG", "RELEASE")


def _list_pkg_ids(src_state_root):
    pkg_dir = os.path.join(src_state_root, "pkg")
    if not os.path.isdir(pkg_dir):
        return []
    return sorted([name for name in os.listdir(pkg_dir) if os.path.isdir(os.path.join(pkg_dir, name))])


def _parse_pkg_ids(values):
    items = set()
    for raw in values or []:
        for token in str(raw).replace(";", ",").split(","):
            token = token.strip()
            if token:
                items.add(token)
    return sorted(items)


def _copy_state_for_pkgs(src_state_root, dest_state_root, pkg_ids):
    stats = {"files": 0, "dirs": 0, "pkg": 0, "missing": [], "present": []}
    pkg_src_root = os.path.join(src_state_root, "pkg")
    pkg_dest_root = os.path.join(dest_state_root, "pkg")
    if not os.path.exists(pkg_dest_root):
        os.makedirs(pkg_dest_root)
        stats["dirs"] += 1
    for pkg_id in sorted(pkg_ids or []):
        src_pkg = os.path.join(pkg_src_root, pkg_id)
        if not os.path.isdir(src_pkg):
            stats["missing"].append(pkg_id)
            continue
        dest_pkg = os.path.join(pkg_dest_root, pkg_id)
        files_copied, dirs_created = _copy_tree(src_pkg, dest_pkg)
        stats["pkg"] += 1
        stats["present"].append(pkg_id)
        stats["files"] += files_copied
        stats["dirs"] += dirs_created
    for name in _SHARED_STATE_FILES:
        src_path = os.path.join(src_state_root, name)
        if not os.path.isfile(src_path):
            continue
        if not os.path.exists(dest_state_root):
            os.makedirs(dest_state_root)
            stats["dirs"] += 1
        dest_path = os.path.join(dest_state_root, name)
        shutil.copy2(src_path, dest_path)
        stats["files"] += 1
    return stats


def _build_rsync_cmd(src_dir, remote_target, excludes, identity=None):
    rsync_cmd = ["rsync", "-avzc", "--delete"]
    for pattern in excludes or []:
        rsync_cmd.extend(["--exclude", pattern])
    if identity:
        rsync_cmd.extend(["-e", "ssh -i %s" % identity])
    rsync_cmd.extend([src_dir.rstrip("/") + "/", remote_target])
    return rsync_cmd


def _build_rsync_file_cmd(src_file, remote_target_file, identity=None):
    rsync_cmd = ["rsync", "-avzc"]
    if identity:
        rsync_cmd.extend(["-e", "ssh -i %s" % identity])
    rsync_cmd.extend([src_file, remote_target_file])
    return rsync_cmd


def _copy_export_dirs(release_root, dest_state_root, allowed_pkg_ids=None):
    if not os.path.isdir(release_root):
        return {"pkg": 0, "files": 0, "dirs": 0}
    stats = {"pkg": 0, "files": 0, "dirs": 0}
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
        stats["pkg"] += 1
        dest_export = os.path.join(pkg_root, name, "export")
        files_copied, dirs_created = _copy_tree(export_dir, dest_export)
        stats["files"] += files_copied
        stats["dirs"] += dirs_created
    return stats


def _prune_removed_pkgs(dest_state_root, allowed_pkg_ids):
    if allowed_pkg_ids is None:
        return 0
    removed = 0
    pkg_root = os.path.join(dest_state_root, "pkg")
    if not os.path.isdir(pkg_root):
        return 0
    for name in os.listdir(pkg_root):
        pkg_dir = os.path.join(pkg_root, name)
        if not os.path.isdir(pkg_dir):
            continue
        if name in allowed_pkg_ids:
            continue
        shutil.rmtree(pkg_dir)
        removed += 1
    return removed


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
            rel_norm = rel.replace("\\", "/")
            # Keep exported artifacts aligned with update-pkg release outputs only.
            # Historical baseline/partial-release archives must stay out of pkgstore sync.
            if "/HISTORY/" in ("/" + rel_norm):
                continue
            if not fname.startswith("release."):
                continue
            items.append((src, rel))
    return items


def _copy_release_tars(release_root, dest_state_root, allowed_pkg_ids=None):
    if not os.path.isdir(release_root):
        return {"copied": 0, "removed": 0}
    stats = {"copied": 0, "removed": 0}
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
                stats["copied"] += 1
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
                    stats["removed"] += 1
            _prune_empty_dirs(dest_artifacts)
    return stats


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
        return 0
    copied = 0
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
            copied += 1
    return copied


def _run_rsync_with_progress(rsync_cmd, verbose, ui):
    global _RSYNC_SUPPORTS_INFO
    if _RSYNC_SUPPORTS_INFO is None:
        try:
            probe = subprocess.check_output(
                ["rsync", "--help"],
                stderr=subprocess.STDOUT,
                universal_newlines=True,
            )
            _RSYNC_SUPPORTS_INFO = "--info" in probe
        except Exception:
            _RSYNC_SUPPORTS_INFO = False

    cmd = list(rsync_cmd)
    if len(cmd) >= 2:
        head = cmd[:-2]
        tail = cmd[-2:]
    else:
        head = cmd
        tail = []
    progress_token = None
    if _RSYNC_SUPPORTS_INFO:
        head.append("--info=progress2,stats2")
        progress_token = "to-chk="
    else:
        head.extend(["--progress", "--stats"])
        if verbose:
            ui.log("[export_pkgstore] rsync old-client mode (--progress/--stats)")
    if verbose:
        head.append("--itemize-changes")
    cmd = head + tail
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1,
    )
    percent_re = re.compile(r"(\d+)%")
    num_files_re = re.compile(r"^Number of files:\s+(\d+)")
    num_xfer_re = re.compile(r"^Number of files transferred:\s+(\d+)")
    saw_progress = False
    summary = {
        "total_files": None,
        "transferred_files": None,
        "deleted": 0,
        "warnings": [],
    }
    while True:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        text = line.rstrip("\n")
        m = percent_re.search(text)
        if m and (progress_token is None or progress_token in text):
            saw_progress = True
            pct = int(m.group(1))
            ui.rsync_progress(pct)
            continue
        if text.startswith("*deleting"):
            summary["deleted"] += 1
        if "cannot delete non-empty directory:" in text:
            summary["warnings"].append(text)
        m_total = num_files_re.match(text)
        if m_total:
            summary["total_files"] = int(m_total.group(1))
        m_xfer = num_xfer_re.match(text)
        if m_xfer:
            summary["transferred_files"] = int(m_xfer.group(1))
        if verbose and text:
            if saw_progress:
                saw_progress = False
            ui.log("[export_pkgstore][rsync] %s" % text)
    rc = proc.wait()
    ui.rsync_done()
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd)
    return summary


def export_pkgstore(src, dest, clean=False, release_root=None, system_name=None, verbose=True, ui=None, selected_pkg_ids=None):
    ui = ui or _TextUI()
    if not os.path.isdir(src):
        raise RuntimeError("source not found: %s" % src)
    total_steps = 5
    step = 0
    ui.step(step, total_steps, "prepare")
    if clean and os.path.exists(dest):
        shutil.rmtree(dest)
    if not os.path.exists(dest):
        os.makedirs(dest)
    step += 1
    ui.step(step, total_steps, "copy state tree")
    if selected_pkg_ids:
        scoped = _copy_state_for_pkgs(src, dest, selected_pkg_ids)
        state_files, state_dirs = scoped["files"], scoped["dirs"]
        if verbose:
            ui.log(
                "[export_pkgstore] state copy (pkg-scope) pkg=%d files=%d dirs=%d"
                % (scoped["pkg"], state_files, state_dirs)
            )
        if scoped["missing"]:
            ui.log("[export_pkgstore] missing pkg in state: %s" % ", ".join(sorted(scoped["missing"])))
        # Limit release-root copy to package ids that still exist in state.
        # This prevents recreate of deleted pkg dirs via export/readme artifacts.
        allowed_pkg_ids = list(scoped.get("present") or [])
    else:
        state_files, state_dirs = _copy_tree(src, dest)
        if verbose:
            ui.log("[export_pkgstore] state copy files=%d dirs=%d" % (state_files, state_dirs))
        allowed_pkg_ids = _list_pkg_ids(src)
    if release_root:
        step += 1
        ui.step(step, total_steps, "copy export dirs")
        export_stats = _copy_export_dirs(release_root, dest, allowed_pkg_ids=allowed_pkg_ids)
        if verbose:
            ui.log(
                "[export_pkgstore] export copy pkg=%d files=%d dirs=%d"
                % (export_stats["pkg"], export_stats["files"], export_stats["dirs"])
            )
        step += 1
        ui.step(step, total_steps, "sync release tars")
        tar_stats = _copy_release_tars(release_root, dest, allowed_pkg_ids=allowed_pkg_ids)
        if verbose:
            ui.log(
                "[export_pkgstore] release tars copied=%d removed=%d"
                % (tar_stats["copied"], tar_stats["removed"])
            )
        step += 1
        ui.step(step, total_steps, "copy readme files")
        readme_count = _copy_readme_files(release_root, dest, system_name, allowed_pkg_ids=allowed_pkg_ids)
        if verbose:
            ui.log("[export_pkgstore] readme copied=%d" % readme_count)
    else:
        step += 3
        ui.step(step, total_steps, "release-root skipped")
    step += 1
    ui.step(step, total_steps, "finalize local sync")
    if selected_pkg_ids:
        removed_pkg = 0
    else:
        removed_pkg = _prune_removed_pkgs(dest, allowed_pkg_ids)
    ui.done_step()
    if verbose:
        ui.log("[export_pkgstore] pruned packages=%d" % removed_pkg)


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
    parser.add_argument(
        "--rsync-exclude",
        action="append",
        default=[],
        help="rsync exclude pattern (repeatable). Default excludes can be disabled with --no-default-excludes",
    )
    parser.add_argument(
        "--no-default-excludes",
        action="store_true",
        help="disable default rsync excludes that protect local-only files",
    )
    parser.add_argument("--debug", action="store_true", help="print debug info about source contents")
    parser.add_argument("--quiet", action="store_true", help="simple mode (less logs); default is detailed")
    parser.add_argument(
        "--pkg-id",
        action="append",
        default=[],
        help="limit export/push to specific pkg id (repeatable, comma-separated)",
    )
    parser.add_argument(
        "--all-pkgs",
        action="store_true",
        help="explicitly allow full synchronization of all package ids",
    )
    args = parser.parse_args(argv)
    if not args.dest and not args.push:
        parser.error("--dest is required when --push is not set")

    selected_pkg_ids = _parse_pkg_ids(args.pkg_id)
    if args.all_pkgs and selected_pkg_ids:
        parser.error("use either --pkg-id or --all-pkgs, not both")
    if not args.all_pkgs and not selected_pkg_ids:
        parser.error("--pkg-id is required (or use --all-pkgs for full sync)")
    ui = _new_ui()
    verbose = not args.quiet
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

    try:
        if args.debug:
            try:
                items = _list_pkg_ids(src)
            except Exception:
                items = []
            ui.log("[export_pkgstore] src=%s pkg=%s" % (src, ", ".join(items) or "-"))
        export_pkgstore(
            src,
            dest_state,
            clean=args.clean,
            release_root=release_root,
            system_name=system_name,
            verbose=verbose,
            ui=ui,
            selected_pkg_ids=selected_pkg_ids,
        )
        ui.log("[export_pkgstore] synced %s -> %s" % (src, dest_state))

        if args.push:
            default_excludes = ["pkg/*/edr", "pkg/*/edr/**"]
            rsync_excludes = [] if args.no_default_excludes else list(default_excludes)
            rsync_excludes.extend(args.rsync_exclude or [])
            remote_root = args.remote_dest.rstrip("/")
            if system_name:
                remote_state = "%s/state/systems/%s" % (remote_root, system_name)
            else:
                remote_state = "%s/state" % remote_root
            subprocess.check_call(
                ["ssh", args.push, "mkdir", "-p", remote_state]
            )
            if selected_pkg_ids:
                rsync_summary = {"total_files": 0, "transferred_files": 0, "deleted": 0, "warnings": []}
                pushed_count = 0
                removed_missing_pkg_count = 0
                scoped_excludes = [p for p in rsync_excludes if p not in ("pkg/*/edr", "pkg/*/edr/**")]
                scoped_excludes.extend(["edr", "edr/**"])
                for pkg_id in selected_pkg_ids:
                    src_pkg = os.path.join(dest_state, "pkg", pkg_id)
                    remote_pkg = "%s/pkg/%s" % (remote_state, pkg_id)
                    if not os.path.isdir(src_pkg):
                        # In pkg-scope mode, a missing local pkg means it was removed from source state.
                        # Remove the remote pkg folder to mirror delete-pkg behavior.
                        subprocess.check_call(["ssh", args.push, "rm", "-rf", remote_pkg])
                        removed_missing_pkg_count += 1
                        ui.log("[export_pkgstore] removed remote pkg (missing local): %s" % remote_pkg)
                        continue
                    subprocess.check_call(["ssh", args.push, "mkdir", "-p", remote_pkg])
                    target = "%s:%s" % (args.push, remote_pkg)
                    rsync_cmd = _build_rsync_cmd(src_pkg, target, scoped_excludes, identity=args.identity)
                    ui.log("[export_pkgstore] rsync pkg %s -> %s" % (pkg_id, remote_pkg))
                    part = _run_rsync_with_progress(rsync_cmd, verbose=verbose, ui=ui)
                    pushed_count += 1
                    rsync_summary["total_files"] += int(part.get("total_files") or 0)
                    rsync_summary["transferred_files"] += int(part.get("transferred_files") or 0)
                    rsync_summary["deleted"] += int(part.get("deleted") or 0)
                    rsync_summary["warnings"].extend(part.get("warnings") or [])
                for fname in _SHARED_STATE_FILES:
                    src_file = os.path.join(dest_state, fname)
                    if not os.path.isfile(src_file):
                        continue
                    remote_file = "%s/%s" % (remote_state, fname)
                    target = "%s:%s" % (args.push, remote_file)
                    rsync_cmd = _build_rsync_file_cmd(src_file, target, identity=args.identity)
                    ui.log("[export_pkgstore] rsync state file %s -> %s" % (fname, remote_file))
                    part = _run_rsync_with_progress(rsync_cmd, verbose=verbose, ui=ui)
                    rsync_summary["total_files"] += int(part.get("total_files") or 0)
                    rsync_summary["transferred_files"] += int(part.get("transferred_files") or 0)
                    rsync_summary["deleted"] += int(part.get("deleted") or 0)
                    rsync_summary["warnings"].extend(part.get("warnings") or [])
                ui.log(
                    "[export_pkgstore] rsync pkg-scope pushed=%d requested=%d removed_missing=%d"
                    % (pushed_count, len(selected_pkg_ids), removed_missing_pkg_count)
                )
            else:
                src_dir = dest_state.rstrip("/") + "/"
                target = "%s:%s" % (args.push, remote_state)
                rsync_cmd = _build_rsync_cmd(src_dir, target, rsync_excludes, identity=args.identity)
                ui.log("[export_pkgstore] rsync -> %s" % (remote_state,))
                rsync_summary = _run_rsync_with_progress(rsync_cmd, verbose=verbose, ui=ui)
            ui.flush_progress()
            ui.log(
                "[export_pkgstore] rsync summary: transferred=%s total=%s deleted=%d warnings=%d"
                % (
                    rsync_summary.get("transferred_files")
                    if rsync_summary.get("transferred_files") is not None
                    else "-",
                    rsync_summary.get("total_files")
                    if rsync_summary.get("total_files") is not None
                    else "-",
                    rsync_summary.get("deleted", 0),
                    len(rsync_summary.get("warnings") or []),
                )
            )
            transferred = rsync_summary.get("transferred_files") or 0
            deleted = rsync_summary.get("deleted") or 0
            if transferred == 0 and deleted == 0:
                ui.log("[export_pkgstore] RESULT: NO REMOTE CHANGES")
            else:
                ui.log(
                    "[export_pkgstore] RESULT: REMOTE UPDATED (transferred=%d deleted=%d)"
                    % (transferred, deleted)
                )
            for w in (rsync_summary.get("warnings") or [])[:5]:
                ui.log("[export_pkgstore] rsync warning: %s" % w)
        else:
            ui.log("[export_pkgstore] push skipped (no --push)")
    finally:
        if tmp_root:
            shutil.rmtree(tmp_root)
        ui.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
