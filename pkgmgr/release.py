from __future__ import print_function
"""Release/package lifecycle scaffolding."""

import json
import os
import re
import shutil
import sys
import time
import subprocess

from . import config, snapshot, shell_integration, points
from .collectors import checksums as checksums_module


def ensure_environment():
    """Prepare environment: update shell PATH/alias for current python scripts."""
    script_dir = os.path.dirname(sys.executable)
    shell_integration.ensure_path_and_alias(script_dir)
    print("[install] ensured shell PATH/alias for script dir: %s" % script_dir)


def _pkg_dir(cfg, pkg_id):
    root = os.path.expanduser(cfg.get("pkg_release_root", ""))
    if not root:
        raise RuntimeError("pkg_release_root missing in config")
    return os.path.join(root, str(pkg_id))


def _pkg_state_dir(pkg_id):
    return os.path.join(config.DEFAULT_STATE_DIR, "pkg", str(pkg_id))


def _pkg_state_path(pkg_id):
    return os.path.join(_pkg_state_dir(pkg_id), "state.json")


def _timestamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _load_pkg_state(pkg_id):
    path = _pkg_state_path(pkg_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _write_pkg_state(pkg_id, status, extra=None):
    state_dir = _pkg_state_dir(pkg_id)
    if not os.path.exists(state_dir):
        os.makedirs(state_dir)
    now = _timestamp()
    existing = _load_pkg_state(pkg_id) or {}
    state = {
        "pkg_id": str(pkg_id),
        "status": status,
        "opened_at": existing.get("opened_at"),
        "updated_at": now,
    }
    if status == "open":
        state["opened_at"] = state["opened_at"] or now
        state.pop("closed_at", None)
    if status == "closed":
        state["closed_at"] = now
    if extra:
        state.update(extra)
    with open(_pkg_state_path(pkg_id), "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    return state


def pkg_is_closed(pkg_id):
    state = _load_pkg_state(pkg_id)
    return bool(state and state.get("status") == "closed")


def pkg_state(pkg_id):
    return _load_pkg_state(pkg_id)


def create_pkg(cfg, pkg_id):
    """Create pkg directory and write pkg.yaml template."""
    dest = _pkg_dir(cfg, pkg_id)
    if not os.path.exists(dest):
        os.makedirs(dest)
    template_path = os.path.join(dest, "pkg.yaml")

    def _should_write_template(path):
        if not os.path.exists(path):
            return True
        prompt = "[create-pkg] pkg.yaml already exists at %s; overwrite? [y/N]: " % path
        if not sys.stdin.isatty():
            print(prompt + "non-tty -> keeping existing")
            return False
        ans = input(prompt).strip().lower()
        return ans in ("y", "yes")

    if not _should_write_template(template_path):
        print("[create-pkg] kept existing pkg.yaml; no changes made")
        return

    git_cfg = cfg.get("git") or {}
    collectors_enabled = (cfg.get("collectors") or {}).get("enabled") or ["checksums"]
    config.write_pkg_template(
        template_path,
        pkg_id=pkg_id,
        pkg_root=dest,
        include_releases=[],
        git_cfg=git_cfg,
        collectors_enabled=collectors_enabled,
    )
    # initial snapshot placeholder (only if no baseline exists yet)
    baseline_path = os.path.join(config.DEFAULT_STATE_DIR, "baseline.json")
    if not os.path.exists(baseline_path):
        snapshot.create_baseline(cfg)
    else:
        print("[create-pkg] baseline already exists; skipping baseline creation")
    _write_pkg_state(pkg_id, "open")
    print("[create-pkg] prepared %s" % dest)


def close_pkg(cfg, pkg_id):
    """Mark pkg closed (stub)."""
    dest = _pkg_dir(cfg, pkg_id)
    if not os.path.exists(dest):
        print("[close-pkg] pkg dir not found, nothing to close: %s" % dest)
        return
    marker = os.path.join(dest, ".closed")
    with open(marker, "w") as f:
        f.write("closed\n")
    _write_pkg_state(pkg_id, "closed")
    print("[close-pkg] marked closed: %s" % dest)


def collect_for_pkg(cfg, pkg_id, collectors=None):
    """Run collector hooks (stub)."""
    if pkg_id and pkg_is_closed(pkg_id):
        print("[collect] pkg=%s is closed; skipping collectors" % pkg_id)
        return
    print(
        "[collect] pkg=%s collectors=%s (stub; wire to collectors.checksums etc.)"
        % (pkg_id, collectors or "default")
    )


def export_pkg(cfg, pkg_id, fmt):
    """Export pkg data placeholder."""
    print("[export] pkg=%s format=%s (stub)" % (pkg_id, fmt))


def run_actions(cfg, names):
    """Run configured actions by name. Returns result list."""
    actions = cfg.get("actions", {}) or {}
    if not names:
        print("[actions] no action names provided")
        return []
    results = []
    for name in names:
        entries = actions.get(name)
        if not entries:
            print("[actions] unknown action: %s" % name)
            results.append({"name": name, "status": "missing", "rc": None})
            continue
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, (list, tuple)):
            print("[actions] invalid action format for %s" % name)
            results.append({"name": name, "status": "invalid", "rc": None})
            continue
        print("[actions] running %s (%d command(s))" % (name, len(entries)))
        for idx, entry in enumerate(entries):
            cmd, cwd, env = _parse_action_entry(entry)
            if not cmd:
                print("[actions] skip empty cmd for %s #%d" % (name, idx + 1))
                continue
            rc = _run_cmd(cmd, cwd=cwd, env=env, label="%s #%d" % (name, idx + 1))
            results.append(
                {
                    "name": name,
                    "status": "ok" if rc == 0 else "failed",
                    "rc": rc,
                }
            )
    return results


def _parse_action_entry(entry):
    if isinstance(entry, dict):
        cmd = entry.get("cmd")
        cwd = entry.get("cwd")
        env = entry.get("env")
        return cmd, cwd, env
    return entry, None, None


def _run_cmd(cmd, cwd=None, env=None, label=None):
    merged_env = os.environ.copy()
    if env and isinstance(env, dict):
        for k, v in env.items():
            if v is None:
                continue
            merged_env[str(k)] = str(v)
    try:
        p = subprocess.Popen(cmd, shell=True, cwd=cwd, env=merged_env)
        rc = p.wait()
        prefix = "[actions]"
        tag = " (%s)" % label if label else ""
        if rc == 0:
            print("%s command ok%s" % (prefix, tag))
        else:
            print("%s command failed%s (rc=%s)" % (prefix, tag, rc))
    except Exception as e:
        prefix = "[actions]"
        tag = " (%s)" % label if label else ""
        print("%s error%s: %s" % (prefix, tag, str(e)))
        return 1
    return rc


def create_point(cfg, pkg_id, label=None, actions_run=None, actions_result=None, snapshot_data=None):
    """Create a checkpoint for a package (snapshot + meta)."""
    return points.create_point(
        cfg, pkg_id, label=label, actions_run=actions_run, actions_result=actions_result, snapshot_data=snapshot_data
    )


def list_points(cfg, pkg_id):
    """List checkpoints for a package."""
    return points.list_points(pkg_id)


def _git_repo_root(pkg_root, git_cfg):
    # Prefer explicit repo_root from pkg config; if relative, resolve from pkg_root.
    repo_root = (git_cfg or {}).get("repo_root")
    if repo_root:
        repo_root = os.path.expanduser(repo_root)
        if not os.path.isabs(repo_root):
            repo_root = os.path.abspath(os.path.join(pkg_root, repo_root))
        else:
            repo_root = os.path.abspath(repo_root)
        if os.path.isdir(repo_root):
            return repo_root
        print("[git] repo_root %s not found; falling back to git rev-parse" % repo_root)
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], stderr=subprocess.STDOUT, text=True
        )
        return out.strip()
    except Exception:
        print("[git] not a git repo or git unavailable; skipping git collection")
        return None


def _collect_git_hits(pkg_cfg, pkg_root):
    git_cfg = pkg_cfg.get("git") or {}
    keywords = [str(k) for k in (git_cfg.get("keywords") or []) if str(k).strip()]
    result = {"keywords": keywords, "commits": []}
    files = set()
    if not keywords:
        return result, files

    repo_root = _git_repo_root(pkg_root, git_cfg)
    if not repo_root:
        return result, files

    since = git_cfg.get("since")
    until = git_cfg.get("until")
    commits = {}
    current = None

    for kw in keywords:
        cmd = [
            "git",
            "--no-pager",
            "log",
            "--name-only",
            "--pretty=format:%H\t%s",
            "--grep",
            kw,
            "--regexp-ignore-case",
            "--all",
        ]
        if since:
            cmd.append("--since=%s" % since)
        if until:
            cmd.append("--until=%s" % until)
        try:
            out = subprocess.check_output(cmd, cwd=repo_root, stderr=subprocess.STDOUT, text=True)
        except Exception as e:
            print("[git] log failed for keyword %s: %s" % (kw, str(e)))
            continue

        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            if "\t" in line:
                parts = line.split("\t", 1)
                commit_hash, subject = parts[0], parts[1]
                current = commits.setdefault(
                    commit_hash, {"hash": commit_hash, "subject": subject, "keywords": set(), "files": set()}
                )
                current["keywords"].add(kw)
                continue
            if current:
                current["files"].add(line)
                files.add(os.path.join(repo_root, line))

    for c in commits.values():
        c["files"] = sorted(c["files"])
        c["keywords"] = sorted(c["keywords"])
        # fetch author and full commit message body for richer context
        try:
            info = subprocess.check_output(
                ["git", "show", "-s", "--format=%an\t%ae\t%ad%n%B", c["hash"]],
                cwd=repo_root,
                stderr=subprocess.STDOUT,
                text=True,
            )
            header, _, body = info.partition("\n")
            parts = header.split("\t")
            c["author_name"] = parts[0] if len(parts) > 0 else ""
            c["author_email"] = parts[1] if len(parts) > 1 else ""
            c["authored_at"] = parts[2] if len(parts) > 2 else ""
            c["message"] = body.strip()
        except Exception as e:
            print("[git] show failed for %s: %s" % (c["hash"], str(e)))
            c["message"] = c.get("subject", "")
        result["commits"].append(c)
    result["commits"] = sorted(result["commits"], key=lambda c: c["hash"])
    return result, files


def _collect_release_files(pkg_root, pkg_cfg):
    include_cfg = pkg_cfg.get("include") or {}
    releases = include_cfg.get("releases") or []
    files = []
    for rel in releases:
        target = os.path.abspath(os.path.join(pkg_root, str(rel)))
        if not os.path.exists(target):
            print("[update-pkg] skip missing release dir: %s" % target)
            continue
        for base, _, names in os.walk(target):
            for name in names:
                files.append(os.path.join(base, name))
    return files


def _hash_paths(paths):
    checksums = {}
    for path in sorted(set(paths)):
        if not os.path.exists(path) or not os.path.isfile(path):
            continue
        try:
            checksums[path] = checksums_module.sha256_of_file(path)
        except Exception as e:
            print("[update-pkg] failed to hash %s: %s" % (path, str(e)))
    return checksums


_REL_VER_RE = re.compile(r"release\.v(\d+)\.(\d+)\.(\d+)$")


def _list_release_versions(base_dir):
    """Return list of (major, minor, patch, path) under base_dir."""
    versions = []
    if not os.path.isdir(base_dir):
        return versions
    for name in os.listdir(base_dir):
        m = _REL_VER_RE.match(name)
        if not m:
            continue
        ver = tuple(int(x) for x in m.groups())
        versions.append((ver, os.path.join(base_dir, name)))
    versions.sort()
    return versions


def _next_release_version(base_dir):
    versions = _list_release_versions(base_dir)
    if not versions:
        return (0, 0, 1), None
    latest_ver, latest_path = versions[-1]
    next_ver = (latest_ver[0], latest_ver[1], latest_ver[2] + 1)
    return next_ver, latest_path


def _format_version(ver_tuple):
    return "release.v%d.%d.%d" % ver_tuple


def _relpath_from_pkg(pkg_dir, path):
    try:
        rel = os.path.relpath(path, pkg_dir)
        if rel.startswith(".."):
            return os.path.basename(path)
        return rel
    except Exception:
        return os.path.basename(path)


def _collect_release_sources(pkg_dir, pkg_cfg):
    include_cfg = pkg_cfg.get("include") or {}
    releases = include_cfg.get("releases") or []
    files = []
    for rel in releases:
        rel_str = str(rel)
        target = rel_str
        if not os.path.isabs(target):
            target = os.path.join(pkg_dir, rel_str)
        target = os.path.abspath(os.path.expanduser(target))
        if not os.path.exists(target):
            print("[update-pkg] skip missing release source: %s" % target)
            continue
        if os.path.isfile(target):
            files.append((target, _relpath_from_pkg(pkg_dir, target)))
            continue
        for base, _, names in os.walk(target):
            for name in names:
                abspath = os.path.join(base, name)
                relpath = _relpath_from_pkg(pkg_dir, abspath)
                files.append((abspath, relpath))
    return files


def _load_prev_hashes(prev_release_dir):
    hashes = {}
    for base, _, names in os.walk(prev_release_dir):
        for name in names:
            abspath = os.path.join(base, name)
            if not os.path.isfile(abspath):
                continue
            rel = os.path.relpath(abspath, prev_release_dir)
            try:
                hashes[rel] = checksums_module.sha256_of_file(abspath)
            except Exception:
                continue
    return hashes


def _prepare_release(pkg_dir, pkg_cfg):
    """
    Build release bundles grouped by top-level include root.
    Layout: <pkg_dir>/release/<root>/release.vX.Y.Z/<files-under-root>
    Returns list of bundle metadata per root.
    """
    release_root = os.path.join(pkg_dir, "release")
    bundles = []
    source_files = _collect_release_sources(pkg_dir, pkg_cfg)

    # group files by top-level root name
    grouped = {}
    for src, rel in source_files:
        parts = rel.split("/", 1)
        if len(parts) == 2:
            root, subrel = parts[0], parts[1]
        else:
            root, subrel = "root", rel
        grouped.setdefault(root, []).append((src, subrel))

    for root, entries in grouped.items():
        root_dir = os.path.join(release_root, root)
        next_ver, prev_dir = _next_release_version(root_dir)
        release_name = _format_version(next_ver)
        release_dir = os.path.join(root_dir, release_name)
        if not os.path.exists(release_dir):
            os.makedirs(release_dir)

        prev_hashes = _load_prev_hashes(prev_dir) if prev_dir else {}
        copied = []
        skipped = []

        for src, rel in entries:
            dest = os.path.join(release_dir, rel)
            dest_parent = os.path.dirname(dest)
            if dest_parent and not os.path.exists(dest_parent):
                os.makedirs(dest_parent)
            prev_hash = prev_hashes.get(rel)
            try:
                curr_hash = checksums_module.sha256_of_file(src)
            except Exception as e:
                print("[update-pkg] failed to hash %s: %s" % (src, str(e)))
                continue
            if prev_hash and prev_hash == curr_hash:
                skipped.append(rel)
                continue
            shutil.copy2(src, dest)
            copied.append(rel)

        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        prev_label = _format_version(_list_release_versions(root_dir)[-2][0]) if prev_dir else "none"
        readme_lines = [
            "Release root: %s" % root,
            "Release: %s" % release_name,
            "Created at: %s" % ts,
            "Base version: %s" % prev_label,
            "Files included: %d (skipped unchanged: %d)" % (len(copied), len(skipped)),
            "Tar example:",
            "  tar cvf %s.tar -C %s %s" % (release_name, root_dir, release_name),
            "",
            "Included files:",
        ]
        readme_lines.extend(["  - %s" % f for f in copied] or ["  (none)"])
        readme_lines.append("")
        readme_lines.append("TODO: baseline change detection/notification for future revision.")

        readme_path = os.path.join(release_dir, "README.txt")
        with open(readme_path, "w") as f:
            f.write("\n".join(readme_lines))

        print("[update-pkg] prepared %s (files=%d skipped=%d)" % (release_dir, len(copied), len(skipped)))
        bundles.append(
            {
                "root": root,
                "release_dir": release_dir,
                "release_name": release_name,
                "copied": copied,
                "skipped": skipped,
                "prev_release": prev_dir,
            }
        )

    return bundles


def update_pkg(cfg, pkg_id):
    """Collect git keyword hits and release checksums into a timestamped history."""
    pkg_dir = _pkg_dir(cfg, pkg_id)
    if not os.path.exists(pkg_dir):
        raise RuntimeError("pkg dir not found: %s" % pkg_dir)
    pkg_cfg_path = os.path.join(pkg_dir, "pkg.yaml")
    pkg_cfg = config.load_pkg_config(pkg_cfg_path)

    ts = time.strftime("%Y%m%dT%H%M%S", time.localtime())
    updates_dir = os.path.join(config.DEFAULT_STATE_DIR, "pkg", str(pkg_id), "updates")
    if not os.path.exists(updates_dir):
        os.makedirs(updates_dir)

    git_info, git_files = _collect_git_hits(pkg_cfg, pkg_dir)
    release_files = _collect_release_files(pkg_dir, pkg_cfg)

    release_bundle = _prepare_release(pkg_dir, pkg_cfg)

    data = {
        "pkg_id": str(pkg_id),
        "run_at": ts,
        "git": git_info,
        "checksums": {
            "git_files": _hash_paths(git_files),
            "release_files": _hash_paths(release_files),
        },
        "release": release_bundle,
    }

    out_path = os.path.join(updates_dir, "update-%s.json" % ts)
    with open(out_path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    print("[update-pkg] wrote %s" % out_path)
    return out_path
