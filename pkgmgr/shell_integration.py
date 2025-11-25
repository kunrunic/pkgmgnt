from __future__ import print_function
"""Shell integration helpers: add PATH/alias to common shell rc files.

Designed to be conservative and idempotent:
- Only appends when marker text is absent.
- Creates rc files if they do not exist.
- Supports bash/zsh/csh/tcsh/fish.
"""

import os


def ensure_path_and_alias(script_dir, alias_name="pkg", command="pkgmgr"):
    """
    Append PATH export and alias to the user's shell rc file when possible.
    script_dir: directory where the pkgmgr console script lives (e.g. venv/bin).
    """
    if not script_dir:
        print("[install] script_dir not provided; skip shell integration")
        return
    shell = os.environ.get("SHELL", "")
    shell_name = os.path.basename(shell) if shell else ""

    handlers = {
        "bash": _update_bash_zsh,
        "zsh": _update_bash_zsh,
        "csh": _update_csh,
        "tcsh": _update_csh,
        "fish": _update_fish,
    }

    handler = handlers.get(shell_name)
    if not handler:
        print("[install] unknown shell '%s'; skipping rc update" % (shell_name or ""))
        return

    try:
        handler(script_dir, alias_name, command)
    except Exception as e:
        print("[install] shell integration failed for %s: %s" % (shell_name, str(e)))


# -------- rc updaters --------

def _ensure_lines(path, marker, lines):
    """
    Append lines to file if marker not present.
    """
    exists = os.path.exists(path)
    content = ""
    if exists:
        try:
            f = open(path, "r")
            try:
                content = f.read()
            finally:
                f.close()
        except Exception:
            content = ""

    if marker in content:
        return False

    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent)

    f = open(path, "a")
    try:
        if content and not content.endswith("\n"):
            f.write("\n")
        f.write("# %s\n" % marker)
        for line in lines:
            f.write(line + "\n")
    finally:
        f.close()
    return True


def _update_bash_zsh(script_dir, alias_name, command):
    rc_path = os.path.expanduser("~/.bashrc")
    shell = os.path.basename(os.environ.get("SHELL", ""))
    if shell == "zsh":
        rc_path = os.path.expanduser("~/.zshrc")
    marker = "added by pkgmgr (sh)"
    lines = [
        'export PATH="%s:$PATH"' % script_dir,
        'alias %s="%s"' % (alias_name, command),
    ]
    changed = _ensure_lines(rc_path, marker, lines)
    if changed:
        print("[install] updated %s with PATH/alias" % rc_path)


def _update_csh(script_dir, alias_name, command):
    rc_path = os.path.expanduser("~/.cshrc")
    shell = os.path.basename(os.environ.get("SHELL", ""))
    if shell == "tcsh":
        rc_path = os.path.expanduser("~/.tcshrc")
    marker = "added by pkgmgr (csh)"
    lines = [
        "set path = (%s $path)" % script_dir,
        "alias %s %s" % (alias_name, command),
    ]
    changed = _ensure_lines(rc_path, marker, lines)
    if changed:
        print("[install] updated %s with PATH/alias" % rc_path)


def _update_fish(script_dir, alias_name, command):
    rc_path = os.path.expanduser("~/.config/fish/config.fish")
    marker = "added by pkgmgr (fish)"
    lines = [
        "set -U fish_user_paths %s $fish_user_paths" % script_dir,
        "alias %s %s" % (alias_name, command),
    ]
    changed = _ensure_lines(rc_path, marker, lines)
    if changed:
        print("[install] updated %s with PATH/alias" % rc_path)
