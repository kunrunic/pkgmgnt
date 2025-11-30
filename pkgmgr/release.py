from __future__ import print_function
"""Release/package lifecycle scaffolding."""

import json
import os
import sys
import time
import subprocess

from . import config, snapshot, shell_integration, points


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
    config.write_pkg_template(template_path)
    # initial snapshot placeholder
    snapshot.create_baseline(cfg)
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
