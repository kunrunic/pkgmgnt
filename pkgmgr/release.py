from __future__ import print_function
"""Release/package lifecycle scaffolding."""

import os
import sys
import subprocess

from . import config, snapshot, shell_integration


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


def create_pkg(cfg, pkg_id):
    """Create pkg directory and write pkg.yaml template."""
    dest = _pkg_dir(cfg, pkg_id)
    if not os.path.exists(dest):
        os.makedirs(dest)
    template_path = os.path.join(dest, "pkg.yaml")
    config.write_pkg_template(template_path)
    # initial snapshot placeholder
    snapshot.create_baseline(cfg)
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
    print("[close-pkg] marked closed: %s" % dest)


def collect_for_pkg(cfg, pkg_id, collectors=None):
    """Run collector hooks (stub)."""
    print(
        "[collect] pkg=%s collectors=%s (stub; wire to collectors.checksums etc.)"
        % (pkg_id, collectors or "default")
    )


def export_pkg(cfg, pkg_id, fmt):
    """Export pkg data placeholder."""
    print("[export] pkg=%s format=%s (stub)" % (pkg_id, fmt))


def run_actions(cfg, names):
    """Run configured actions by name."""
    actions = cfg.get("actions", {}) or {}
    if not names:
        print("[actions] no action names provided")
        return
    for name in names:
        entries = actions.get(name)
        if not entries:
            print("[actions] unknown action: %s" % name)
            continue
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, (list, tuple)):
            print("[actions] invalid action format for %s" % name)
            continue
        print("[actions] running %s (%d command(s))" % (name, len(entries)))
        for idx, entry in enumerate(entries):
            cmd, cwd, env = _parse_action_entry(entry)
            if not cmd:
                print("[actions] skip empty cmd for %s #%d" % (name, idx + 1))
                continue
            _run_cmd(cmd, cwd=cwd, env=env, label="%s #%d" % (name, idx + 1))


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
