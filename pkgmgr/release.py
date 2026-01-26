from __future__ import print_function
"""Release/package lifecycle scaffolding."""

import json
import os
import re
import shutil
import shlex
import sys
import time
import tarfile
import subprocess
import glob

from . import config, snapshot, shell_integration, points
from .collectors import checksums as checksums_module


def ensure_environment():
    """Prepare environment: print shell PATH/alias instructions."""
    script_dir = os.path.dirname(sys.executable)
    shell_integration.ensure_path_and_alias(script_dir)


def _pkg_dir(cfg, pkg_id):
    root = os.path.expanduser(cfg.get("pkg_release_root", ""))
    if not root:
        raise RuntimeError("pkg_release_root missing in config")
    return os.path.join(root, str(pkg_id))


def _pkg_state_dir(pkg_id):
    return os.path.join(config.DEFAULT_STATE_DIR, "pkg", str(pkg_id))


def _pkg_state_path(pkg_id):
    return os.path.join(_pkg_state_dir(pkg_id), "state.json")


def _pkg_summary_path():
    return os.path.join(config.DEFAULT_STATE_DIR, "pkg-summary.json")


def _pkg_release_history_dir(pkg_id):
    return os.path.join(config.DEFAULT_STATE_DIR, "pkg", str(pkg_id), "release")


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


def _parse_ts(value):
    if not value:
        return 0
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y%m%dT%H%M%S"):
        try:
            return int(time.mktime(time.strptime(str(value), fmt)))
        except Exception:
            continue
    return 0


def _load_pkg_summary():
    path = _pkg_summary_path()
    if not os.path.exists(path):
        return {"generated_at": _timestamp(), "pkgs": []}
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("pkgs"), list):
            return data
    except Exception:
        pass
    return {"generated_at": _timestamp(), "pkgs": []}


def _find_latest_update(pkg_id):
    updates_dir = os.path.join(config.DEFAULT_STATE_DIR, "pkg", str(pkg_id), "updates")
    if not os.path.isdir(updates_dir):
        return None, None
    candidates = []
    for name in os.listdir(updates_dir):
        if not name.startswith("update-") or not name.endswith(".json"):
            continue
        ts = name[len("update-"):-len(".json")]
        candidates.append((ts, name))
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: _parse_ts(item[0]))
    latest_ts, latest_name = candidates[-1]
    return os.path.join(updates_dir, latest_name), latest_ts


def _build_pkg_summary_entry(pkg_id):
    state = _load_pkg_state(pkg_id) or {}
    update_path, update_ts = _find_latest_update(pkg_id)
    update_data = {}
    if update_path:
        try:
            with open(update_path, "r") as f:
                update_data = json.load(f) or {}
        except Exception:
            update_data = {}
    git_info = update_data.get("git") or {}
    release_info = update_data.get("release") or []
    checksums = update_data.get("checksums") or {}
    git_files = checksums.get("git_files") or {}
    release_files = checksums.get("release_files") or {}

    entry = {
        "pkg_id": str(pkg_id),
        "status": state.get("status") or "unknown",
        "opened_at": state.get("opened_at"),
        "updated_at": state.get("updated_at"),
        "closed_at": state.get("closed_at"),
        "last_update_id": os.path.basename(update_path) if update_path else None,
        "last_update_at": update_ts,
        "git": {
            "keywords": git_info.get("keywords") or [],
            "commit_count": len(git_info.get("commits") or []),
        },
        "release": {
            "bundle_count": len(release_info),
            "roots": sorted({b.get("root") for b in release_info if b.get("root")}),
            "names": sorted({b.get("release_name") for b in release_info if b.get("release_name")}),
        },
        "artifacts": {
            "git_files": len(git_files),
            "release_files": len(release_files),
        },
    }
    return entry


def _update_pkg_summary(pkg_id):
    data = _load_pkg_summary()
    pkgs = data.get("pkgs") or []
    by_id = {p.get("pkg_id"): p for p in pkgs if isinstance(p, dict)}
    entry = _build_pkg_summary_entry(pkg_id)
    by_id[entry["pkg_id"]] = entry

    def _sort_key(item):
        status = item.get("status") or ""
        updated_ts = max(_parse_ts(item.get("updated_at")), _parse_ts(item.get("last_update_at")))
        return (0 if status == "open" else 1, -updated_ts)

    ordered = sorted(by_id.values(), key=_sort_key)
    data = {
        "generated_at": _timestamp(),
        "pkgs": ordered,
    }
    path = _pkg_summary_path()
    if not os.path.exists(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)


def _write_release_history(pkg_id, run_at, bundles):
    if not bundles:
        return None
    rel_dir = _pkg_release_history_dir(pkg_id)
    if not os.path.exists(rel_dir):
        os.makedirs(rel_dir)
    payload = {
        "pkg_id": str(pkg_id),
        "run_at": run_at,
        "generated_at": _timestamp(),
        "bundles": bundles,
    }
    out_path = os.path.join(rel_dir, "release-%s.json" % run_at)
    with open(out_path, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
    return out_path


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
    _update_pkg_summary(pkg_id)
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
    _update_pkg_summary(pkg_id)
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



def run_actions(cfg, names, extra_args=None, config_path=None, context=None):
    """Run configured actions by name. Returns result list."""
    actions = cfg.get("actions", {}) or {}
    if not names:
        print("[actions] no action names provided")
        return []
    extra_args = extra_args or []
    extra_suffix = ""
    if extra_args:
        quoted = [shlex.quote(str(arg)) for arg in extra_args]
        extra_suffix = " " + " ".join(quoted)
    results = []
    context = context or {}
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
            cmd = _render_action_value(cmd, context)
            cwd = _render_action_value(cwd, context)
            env = _render_action_env(env, context)
            if config_path:
                env = dict(env or {})
                env.setdefault("PKGMGR_CONFIG", config_path)
            if extra_suffix:
                cmd = "%s%s" % (cmd, extra_suffix)
            rc = _run_cmd(cmd, cwd=cwd, env=env, label="%s #%d" % (name, idx + 1))
            results.append(
                {
                    "name": name,
                    "status": "ok" if rc == 0 else "failed",
                    "rc": rc,
                }
            )
    return results


def _render_action_value(value, context):
    if not value or not context:
        return value
    text = str(value)
    for key, val in context.items():
        text = text.replace("{%s}" % key, str(val))
    return text


def _render_action_env(env, context):
    if not env or not isinstance(env, dict):
        return env
    rendered = {}
    for k, v in env.items():
        rendered[k] = _render_action_value(v, context)
    return rendered


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
            ["git", "rev-parse", "--show-toplevel"], stderr=subprocess.STDOUT, universal_newlines=True
        )
        return out.strip()
    except Exception:
        print("[git] not a git repo or git unavailable; skipping git collection")
        return None


def _text_type():
    try:
        return unicode  # type: ignore[name-defined]
    except Exception:
        return str


def _decode_git_output(raw, encodings):
    if raw is None:
        return ""
    text_type = _text_type()
    if isinstance(raw, text_type):
        return raw
    if not encodings:
        encodings = []
    candidates = [e for e in encodings if e]
    candidates.extend(["utf-8", "euc-kr", "cp949"])
    best_text = None
    best_score = None
    for enc in candidates:
        try:
            text = raw.decode(enc, errors="replace")
        except Exception:
            continue
        score = text.count(u"\ufffd")
        if best_score is None or score < best_score:
            best_score = score
            best_text = text
        if score == 0:
            break
    if best_text is not None:
        return best_text
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return str(raw)


def _git_output_encoding(repo_root):
    for key in ("i18n.logOutputEncoding", "i18n.commitEncoding"):
        try:
            out = subprocess.check_output(
                ["git", "config", "--get", key],
                cwd=repo_root,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
            ).strip()
        except Exception:
            out = ""
        if out:
            return out
    return "utf-8"


def _collect_git_hits(pkg_cfg, pkg_root, main_git_cfg=None):
    git_cfg = pkg_cfg.get("git") or {}
    main_git_cfg = main_git_cfg or {}
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

    output_encoding = _git_output_encoding(repo_root)
    prefix = str(main_git_cfg.get("keyword_prefix") or "").strip()
    prefix_re = re.escape(prefix) if prefix else ""
    for kw in keywords:
        grep_kw = kw
        if prefix_re:
            grep_kw = "%s\\s*%s" % (prefix_re, re.escape(kw))
        cmd = [
            "git",
            "--no-pager",
            "log",
            "--name-only",
            "--pretty=format:%H\t%s",
            "--grep=%s" % grep_kw,
            "--regexp-ignore-case",
            "--all",
            "--",
        ]
        if since:
            cmd.append("--since=%s" % since)
        if until:
            cmd.append("--until=%s" % until)
        try:
            out_raw = subprocess.check_output(
                cmd,
                cwd=repo_root,
                stderr=subprocess.STDOUT,
                universal_newlines=False,
            )
            out = _decode_git_output(out_raw, [output_encoding])
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
        # Provide stable, user-facing aliases.
        c["commit"] = c.get("hash")
        # fetch author and full commit message body for richer context
        try:
            info_raw = subprocess.check_output(
                ["git", "show", "-s", "--format=%an\t%ae\t%ad%n%s%n%b", c["hash"]],
                cwd=repo_root,
                stderr=subprocess.STDOUT,
                universal_newlines=False,
            )
            info = _decode_git_output(info_raw, [output_encoding])
            header, _, body = info.partition("\n")
            parts = header.split("\t")
            c["author_name"] = parts[0] if len(parts) > 0 else ""
            c["author_email"] = parts[1] if len(parts) > 1 else ""
            c["authored_at"] = parts[2] if len(parts) > 2 else ""
            c["message"] = body.rstrip("\n")
        except Exception as e:
            print("[git] show failed for %s: %s" % (c["hash"], str(e)))
            c["message"] = c.get("subject", "")
        if c.get("author_name") or c.get("author_email"):
            if c.get("author_email"):
                c["author"] = "%s <%s>" % (c.get("author_name", ""), c.get("author_email", ""))
            else:
                c["author"] = c.get("author_name", "")
        c["date"] = c.get("authored_at", "")
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
_PKG_NOTE_NAME = "PKG_NOTE"
_PKG_LIST_NAME = "PKG_LIST"


def _read_json_path(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        try:
            with open(path, "r", encoding="euc-kr", errors="replace") as f:
                return json.load(f)
        except Exception:
            return None


def _read_note_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        try:
            with open(path, "r", encoding="euc-kr", errors="replace") as f:
                return f.read()
        except Exception:
            return ""


def _update_release_history_note(pkg_id, root_name, release_name, note_text):
    rel_dir = _pkg_release_history_dir(pkg_id)
    if not os.path.isdir(rel_dir):
        return False
    filenames = [n for n in os.listdir(rel_dir) if n.startswith("release-") and n.endswith(".json")]
    for name in sorted(filenames, reverse=True):
        path = os.path.join(rel_dir, name)
        payload = _read_json_path(path) or {}
        bundles = payload.get("bundles") or []
        updated = False
        for bundle in bundles:
            if bundle.get("root") == root_name and bundle.get("release_name") == release_name:
                bundle["note"] = note_text
                updated = True
        if updated:
            payload["generated_at"] = _timestamp()
            with open(path, "w") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
            return True
    return False


def _list_release_versions(base_dir, include_history=False):
    """Return list of (major, minor, patch, path) under base_dir (optional HISTORY)."""
    versions = []
    if not os.path.isdir(base_dir):
        return versions
    scan_dirs = [base_dir]
    if include_history:
        scan_dirs.append(os.path.join(base_dir, "HISTORY"))
    for scan_dir in scan_dirs:
        if not os.path.isdir(scan_dir):
            continue
        for name in os.listdir(scan_dir):
            m = _REL_VER_RE.match(name)
            if not m:
                continue
            ver = tuple(int(x) for x in m.groups())
            versions.append((ver, os.path.join(scan_dir, name)))
    versions.sort()
    return versions


def _next_release_version(base_dir):
    versions = _list_release_versions(base_dir, include_history=True)
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
        active_versions = _list_release_versions(root_dir, include_history=False)
        history_dir = os.path.join(root_dir, "HISTORY")
        history_versions = _list_release_versions(history_dir, include_history=False)
        baseline_dir = os.path.join(history_dir, "BASELINE")
        reuse_active = False

        if active_versions:
            latest_ver, latest_path = active_versions[-1]
            release_name = _format_version(latest_ver)
            release_dir = latest_path
            prev_dir = latest_path
            reuse_active = True
            base_label = os.path.basename(history_versions[-1][1]) if history_versions else "none"
        else:
            next_ver, prev_dir = _next_release_version(root_dir)
            release_name = _format_version(next_ver)
            release_dir = os.path.join(root_dir, release_name)
            base_label = os.path.basename(prev_dir) if prev_dir else "none"

        has_baseline = os.path.isdir(baseline_dir)
        baseline_hashes = _load_prev_hashes(baseline_dir) if has_baseline else {}
        release_hashes = _load_prev_hashes(release_dir) if reuse_active and os.path.isdir(release_dir) else {}
        copied = []
        added = []
        updated = []
        skipped = []
        to_copy = []
        expected = set(rel for _, rel in entries)
        existing = set()
        if reuse_active and os.path.isdir(release_dir):
            for base, _, names in os.walk(release_dir):
                for name in names:
                    if name in (_PKG_NOTE_NAME, _PKG_LIST_NAME):
                        continue
                    abspath = os.path.join(base, name)
                    if not os.path.isfile(abspath):
                        continue
                    rel = os.path.relpath(abspath, release_dir)
                    existing.add(rel)
        curr_hashes = {}
        removed = set()
        prev_existing = set()
        if not reuse_active and prev_dir and os.path.isdir(prev_dir):
            for base, _, names in os.walk(prev_dir):
                for name in names:
                    if name in (_PKG_NOTE_NAME, _PKG_LIST_NAME):
                        continue
                    abspath = os.path.join(base, name)
                    if not os.path.isfile(abspath):
                        continue
                    rel = os.path.relpath(abspath, prev_dir)
                    prev_existing.add(rel)

        for src, rel in entries:
            baseline_hash = baseline_hashes.get(rel)
            try:
                curr_hash = checksums_module.sha256_of_file(src)
                curr_hashes[rel] = curr_hash
            except Exception as e:
                print("[update-pkg] failed to hash %s: %s" % (src, str(e)))
                continue
            if baseline_hash and baseline_hash == curr_hash:
                skipped.append(rel)
                continue
            release_hash = release_hashes.get(rel)
            if release_hash and release_hash == curr_hash:
                continue
            copied.append(rel)
            if release_hash:
                updated.append(rel)
            else:
                added.append(rel)
            to_copy.append((src, rel))

        if reuse_active:
            for rel in existing:
                if rel not in expected:
                    removed.add(rel)
                    continue
                baseline_hash = baseline_hashes.get(rel)
                curr_hash = curr_hashes.get(rel)
                if baseline_hash and curr_hash and baseline_hash == curr_hash:
                    removed.add(rel)
        else:
            if prev_existing:
                removed = prev_existing - expected
            elif not has_baseline:
                removed = existing - expected

        if (has_baseline or reuse_active) and not copied and not removed:
            print("[update-pkg] no changes for %s; skipping release" % root)
            continue

        note_payload = None
        if reuse_active and os.path.exists(release_dir):
            existing_note = os.path.join(release_dir, _PKG_NOTE_NAME)
            if os.path.exists(existing_note):
                try:
                    with open(existing_note, "r") as f:
                        note_payload = f.read()
                except Exception:
                    note_payload = None
        if not os.path.exists(release_dir):
            os.makedirs(release_dir)

        for src, rel in to_copy:
            dest = os.path.join(release_dir, rel)
            dest_parent = os.path.dirname(dest)
            if dest_parent and not os.path.exists(dest_parent):
                os.makedirs(dest_parent)
            shutil.copy2(src, dest)
        for rel in sorted(removed):
            abspath = os.path.join(release_dir, rel)
            if os.path.isfile(abspath):
                os.remove(abspath)
        for base, dirs, files in os.walk(release_dir, topdown=False):
            if files:
                continue
            if not dirs and base != release_dir:
                os.rmdir(base)

        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        note_path = os.path.join(release_dir, _PKG_NOTE_NAME)
        if note_payload is not None:
            with open(note_path, "w") as f:
                f.write(note_payload)
        elif not os.path.exists(note_path):
            with open(note_path, "w") as f:
                f.write(
                    "\n".join(
                        [
                            "Release root: %s" % root,
                            "Release: %s" % release_name,
                            "Created at: %s" % ts,
                            "",
                            "[ package note ]",
                            "",
                            "상세 PKG 항목은 PKG_LIST를 참조하세요.",
                            "",
                        ]
                    )
                )

        note_text = _read_note_text(note_path)

        all_files = []
        for base, _, names in os.walk(release_dir):
            for name in names:
                if name in (_PKG_NOTE_NAME, _PKG_LIST_NAME):
                    continue
                abspath = os.path.join(base, name)
                if not os.path.isfile(abspath):
                    continue
                rel = os.path.relpath(abspath, release_dir)
                all_files.append(rel)
        all_files.sort()

        change_parts = []
        if added:
            change_parts.append("+%d" % len(added))
        if updated:
            change_parts.append("~%d" % len(updated))
        if removed:
            change_parts.append("-%d" % len(removed))
        change_label = " ".join(change_parts) or "no changes"

        pkg_list_lines = [
            "Release root: %s" % root,
            "Release: %s" % release_name,
            "Created at: %s" % ts,
            "Base version: %s" % base_label,
            "Files changed: %s (skipped unchanged: %d)" % (change_label, len(skipped)),
            "",
            "Included files:",
        ]
        pkg_list_lines.extend(["  - %s" % f for f in all_files] or ["  (none)"])
        pkg_list_lines.append("")
        pkg_list_lines.append("Note: 상세 PKG 정보는 PKG_NOTE를 확인하세요.")

        pkg_list_path = os.path.join(release_dir, _PKG_LIST_NAME)
        with open(pkg_list_path, "w") as f:
            f.write("\n".join(pkg_list_lines))

        print(
            "[update-pkg] prepared %s (%s skipped=%d)"
            % (release_dir, change_label, len(skipped))
        )
        bundles.append(
            {
                "root": root,
                "release_dir": release_dir,
                "release_name": release_name,
                "created_at": ts,
                "files": all_files,
                "copied": copied,
                "skipped": skipped,
                "added": added,
                "updated": updated,
                "removed": sorted(removed),
                "prev_release": prev_dir,
                "note": note_text,
            }
        )

    return bundles


def _sync_baseline_root(root_dir, entries):
    baseline_dir = os.path.join(root_dir, "HISTORY", "BASELINE")
    if not os.path.exists(baseline_dir):
        os.makedirs(baseline_dir)
    expected = set(rel for _, rel in entries)

    for src, rel in entries:
        dest = os.path.join(baseline_dir, rel)
        dest_parent = os.path.dirname(dest)
        if dest_parent and not os.path.exists(dest_parent):
            os.makedirs(dest_parent)
        shutil.copy2(src, dest)

    for base, _, names in os.walk(baseline_dir):
        for name in names:
            abspath = os.path.join(base, name)
            if not os.path.isfile(abspath):
                continue
            rel = os.path.relpath(abspath, baseline_dir)
            if rel not in expected:
                os.remove(abspath)
    for base, dirs, files in os.walk(baseline_dir, topdown=False):
        if files:
            continue
        if not dirs and base != baseline_dir:
            os.rmdir(base)


def _finalize_release_root(root_dir):
    versions = _list_release_versions(root_dir, include_history=False)
    if not versions:
        print("[update-pkg] no active release dir under %s" % root_dir)
        return None
    latest_ver, latest_path = versions[-1]
    release_name = _format_version(latest_ver)
    tar_path = os.path.join(root_dir, "%s.tar" % release_name)

    with tarfile.open(tar_path, "w") as tar:
        tar.add(latest_path, arcname=release_name)

    history_dir = os.path.join(root_dir, "HISTORY")
    if not os.path.exists(history_dir):
        os.makedirs(history_dir)
    history_target = os.path.join(history_dir, release_name)
    if os.path.exists(history_target):
        print("[update-pkg] history already contains %s; skipping move" % history_target)
    else:
        shutil.move(latest_path, history_target)
    print("[update-pkg] finalized %s (tar=%s)" % (history_target, tar_path))
    return tar_path


def list_active_release_roots(cfg, pkg_id):
    pkg_dir = _pkg_dir(cfg, pkg_id)
    if not os.path.exists(pkg_dir):
        return []
    release_root = os.path.join(pkg_dir, "release")
    roots = []
    if not os.path.isdir(release_root):
        return roots
    for name in os.listdir(release_root):
        root_dir = os.path.join(release_root, name)
        if not os.path.isdir(root_dir) or name == "HISTORY":
            continue
        if _list_release_versions(root_dir, include_history=False):
            roots.append(name)
    return sorted(roots)


def finalize_pkg_release(cfg, pkg_id, roots=None):
    """Finalize latest release bundle by moving to HISTORY and creating tar."""
    pkg_dir = _pkg_dir(cfg, pkg_id)
    if not os.path.exists(pkg_dir):
        raise RuntimeError("pkg dir not found: %s" % pkg_dir)
    pkg_cfg_path = os.path.join(pkg_dir, "pkg.yaml")
    pkg_cfg = config.load_pkg_config(pkg_cfg_path)
    release_root = os.path.join(pkg_dir, "release")
    active_roots = list_active_release_roots(cfg, pkg_id)
    if not active_roots:
        print("[update-pkg] no active release; run `pkgmgr update-pkg %s` first" % pkg_id)
        return []
    roots_filter = set(roots) if roots else set(active_roots)
    source_files = _collect_release_sources(pkg_dir, pkg_cfg)
    grouped = {}
    for src, rel in source_files:
        parts = rel.split("/", 1)
        if len(parts) == 2:
            root, subrel = parts[0], parts[1]
        else:
            root, subrel = "root", rel
        grouped.setdefault(root, []).append((src, subrel))
    finalized = []

    if not os.path.isdir(release_root):
        print("[update-pkg] release root missing: %s" % release_root)
        return finalized

    for name in sorted(os.listdir(release_root)):
        root_dir = os.path.join(release_root, name)
        if not os.path.isdir(root_dir):
            continue
        if name == "HISTORY":
            continue
        if name not in roots_filter:
            continue
        tar_path = _finalize_release_root(root_dir)
        if tar_path:
            release_name = os.path.basename(tar_path).rsplit(".tar", 1)[0]
            history_target = os.path.join(root_dir, "HISTORY", release_name)
            note_path = os.path.join(history_target, _PKG_NOTE_NAME)
            note_text = _read_note_text(note_path) if os.path.isfile(note_path) else ""
            _update_release_history_note(pkg_id, name, release_name, note_text)
            _sync_baseline_root(root_dir, grouped.get(name, []))
            finalized.append(tar_path)

    baseline_synced = False
    if not finalized:
        for name in sorted(os.listdir(release_root)):
            root_dir = os.path.join(release_root, name)
            if not os.path.isdir(root_dir):
                continue
            if name == "HISTORY":
                continue
            if name not in roots_filter:
                continue
            baseline_dir = os.path.join(root_dir, "HISTORY", "BASELINE")
            if os.path.isdir(baseline_dir):
                continue
            _sync_baseline_root(root_dir, grouped.get(name, []))
            baseline_synced = True
            print("[update-pkg] baseline synced for %s" % root_dir)

    if not finalized and not baseline_synced:
        print("[update-pkg] no release bundles finalized")
    return finalized


def _normalize_release_name(release_name):
    name = (release_name or "").strip()
    if not name:
        raise RuntimeError("release_name required")
    if not name.startswith("release."):
        if not name.startswith("v"):
            name = "v" + name
        name = "release." + name
    return name


def list_cancel_targets(cfg, pkg_id, release_name):
    pkg_dir = _pkg_dir(cfg, pkg_id)
    if not os.path.exists(pkg_dir):
        raise RuntimeError("pkg dir not found: %s" % pkg_dir)
    release_root = os.path.join(pkg_dir, "release")
    if not os.path.isdir(release_root):
        raise RuntimeError("release root missing: %s" % release_root)

    name = _normalize_release_name(release_name)
    roots = []
    for root_name in os.listdir(release_root):
        root_dir = os.path.join(release_root, root_name)
        if not os.path.isdir(root_dir) or root_name == "HISTORY":
            continue
        history_dir = os.path.join(root_dir, "HISTORY", name)
        tar_path = os.path.join(root_dir, "%s.tar" % name)
        if os.path.isdir(history_dir) or os.path.exists(tar_path):
            roots.append(root_name)
    return name, roots


def _release_history_dir_for_pkg(pkg_id):
    return os.path.join(config.DEFAULT_STATE_DIR, "pkg", str(pkg_id), "release")


def _load_release_history_payload(path):
    payload = {}
    try:
        raw = open(path, "rb").read()
    except Exception:
        raw = None
    if raw:
        for enc in ("utf-8", "cp949", "euc-kr", "latin1"):
            try:
                payload = json.loads(raw.decode(enc))
                break
            except Exception:
                payload = {}
    return payload


def _remove_release_history_entries(pkg_id, release_name, roots):
    history_dir = _release_history_dir_for_pkg(pkg_id)
    if not os.path.isdir(history_dir):
        return 0
    removed = 0
    for path in sorted(glob.glob(os.path.join(history_dir, "release-*.json"))):
        payload = _load_release_history_payload(path)
        bundles = payload.get("bundles") or []
        kept = []
        for bundle in bundles:
            if bundle.get("release_name") == release_name and bundle.get("root") in roots:
                removed += 1
                continue
            kept.append(bundle)
        if len(kept) != len(bundles):
            if kept:
                payload["bundles"] = kept
                payload["generated_at"] = _timestamp()
                with open(path, "w") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
            else:
                os.remove(path)
    return removed


def _find_release_bundles(pkg_id, release_name, roots):
    history_dir = _release_history_dir_for_pkg(pkg_id)
    bundles = []
    if not os.path.isdir(history_dir):
        return bundles
    for path in sorted(glob.glob(os.path.join(history_dir, "release-*.json"))):
        payload = _load_release_history_payload(path)
        for bundle in payload.get("bundles") or []:
            if bundle.get("release_name") != release_name:
                continue
            root = bundle.get("root") or "root"
            if root in roots:
                bundles.append(bundle)
    return bundles


def _prune_empty_dirs(base_dir):
    for base, dirs, files in os.walk(base_dir, topdown=False):
        if files:
            continue
        if not dirs and base != base_dir:
            os.rmdir(base)


def _reset_baseline_from_active(root_dir, release_name):
    baseline_dir = os.path.join(root_dir, "HISTORY", "BASELINE")
    active_dir = os.path.join(root_dir, release_name)
    if not os.path.isdir(active_dir):
        print("[cancel] active release missing; skip baseline reset for %s" % root_dir)
        return
    if os.path.isdir(baseline_dir):
        shutil.rmtree(baseline_dir)
    os.makedirs(baseline_dir, exist_ok=True)
    for base, dirs, files in os.walk(active_dir):
        rel_base = os.path.relpath(base, active_dir)
        dest_base = baseline_dir if rel_base == "." else os.path.join(baseline_dir, rel_base)
        if not os.path.exists(dest_base):
            os.makedirs(dest_base)
        for name in files:
            if name in (_PKG_NOTE_NAME, _PKG_LIST_NAME):
                continue
            src = os.path.join(base, name)
            dest = os.path.join(dest_base, name)
            shutil.copy2(src, dest)
    print("[cancel] baseline reset from active for %s" % root_dir)


def _revert_baseline_for_bundles(release_root, bundles):
    by_root = {}
    for bundle in bundles:
        root = bundle.get("root") or "root"
        by_root.setdefault(root, []).append(bundle)
    for root, items in by_root.items():
        baseline_dir = os.path.join(release_root, root, "HISTORY", "BASELINE")
        if not os.path.isdir(baseline_dir):
            print("[cancel] baseline missing for %s; skip revert" % root)
            continue
        for bundle in items:
            prev_release = bundle.get("prev_release")
            release_name = bundle.get("release_name") or ""
            added = bundle.get("added") or []
            updated = bundle.get("updated") or []
            removed = bundle.get("removed") or []
            if prev_release and not os.path.isdir(prev_release):
                prev_release = None
            if not prev_release and release_name:
                _reset_baseline_from_active(os.path.join(release_root, root), release_name)
                continue
            for rel in added:
                target = os.path.join(baseline_dir, rel)
                if os.path.isfile(target):
                    os.remove(target)
            if prev_release:
                for rel in list(set(updated + removed)):
                    src = os.path.join(prev_release, rel)
                    if not os.path.isfile(src):
                        continue
                    dest = os.path.join(baseline_dir, rel)
                    dest_parent = os.path.dirname(dest)
                    if dest_parent and not os.path.exists(dest_parent):
                        os.makedirs(dest_parent)
                    shutil.copy2(src, dest)
            _prune_empty_dirs(baseline_dir)
        print("[cancel] baseline reverted for %s" % root)


def cancel_pkg_release(cfg, pkg_id, release_name, root_name=None, force=False, clean_history=False):
    pkg_dir = _pkg_dir(cfg, pkg_id)
    if not os.path.exists(pkg_dir):
        raise RuntimeError("pkg dir not found: %s" % pkg_dir)
    release_root = os.path.join(pkg_dir, "release")
    if not os.path.isdir(release_root):
        raise RuntimeError("release root missing: %s" % release_root)

    name = _normalize_release_name(release_name)

    found = False
    touched_roots = []
    if root_name:
        roots = [root_name]
    else:
        _, roots = list_cancel_targets(cfg, pkg_id, name)
    roots = sorted(set(roots))
    precheck_errors = {}
    for root in roots:
        root_dir = os.path.join(release_root, root)
        if not os.path.isdir(root_dir) or root == "HISTORY":
            continue
        active_versions = _list_release_versions(root_dir, include_history=False)
        if active_versions and not force:
            precheck_errors.setdefault(root, []).append("active release exists")
        history_dir = os.path.join(root_dir, "HISTORY", name)
        tar_path = os.path.join(root_dir, "%s.tar" % name)
        if not clean_history and not os.path.isdir(history_dir) and not os.path.exists(tar_path):
            precheck_errors.setdefault(root, []).append("cancel target missing")
    if precheck_errors:
        detail = "; ".join(
            ["%s (%s)" % (root, ", ".join(sorted(set(reasons)))) for root, reasons in sorted(precheck_errors.items())]
        )
        raise RuntimeError(
            "cancel precheck failed: %s; use --cancel-force or --cancel-clean-history" % detail
        )
    for root in roots:
        root_dir = os.path.join(release_root, root)
        if not os.path.isdir(root_dir) or root == "HISTORY":
            continue
        active_versions = _list_release_versions(root_dir, include_history=False)
        history_dir = os.path.join(root_dir, "HISTORY", name)
        active_dir = os.path.join(root_dir, name)
        tar_path = os.path.join(root_dir, "%s.tar" % name)
        has_history = os.path.isdir(history_dir)
        has_tar = os.path.exists(tar_path)
        if active_versions and force and has_history:
            for _, active_path in active_versions:
                if os.path.isdir(active_path):
                    shutil.rmtree(active_path)
                    print("[cancel] removed active %s" % active_path)
        if os.path.isdir(history_dir):
            if os.path.exists(active_dir):
                raise RuntimeError("active release already exists: %s" % active_dir)
            shutil.move(history_dir, active_dir)
            print("[cancel] restored %s -> %s" % (history_dir, active_dir))
            found = True
            touched_roots.append(root)
        if has_tar:
            os.remove(tar_path)
            print("[cancel] removed tar %s" % tar_path)
            found = True

    if not found:
        if not clean_history:
            raise RuntimeError("release not found: %s" % name)
        print("[cancel] nothing to restore; history cleanup only")
    if clean_history:
        bundles = _find_release_bundles(pkg_id, name, touched_roots or roots)
        if bundles:
            _revert_baseline_for_bundles(release_root, bundles)
        removed = _remove_release_history_entries(pkg_id, name, touched_roots or roots)
        print("[cancel] cleaned history bundles: %d" % removed)


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

    main_git_cfg = cfg.get("git") or {}
    git_info, git_files = _collect_git_hits(pkg_cfg, pkg_dir, main_git_cfg)
    repo_url = main_git_cfg.get("repo_url")
    if repo_url:
        git_info["repo_url"] = repo_url
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
    _write_release_history(pkg_id, ts, release_bundle)
    _update_pkg_summary(pkg_id)
    return out_path
