from __future__ import print_function
"""Shell integration helpers: print PATH/alias instructions per shell."""

import os

from . import config


def ensure_path_and_alias(script_dir, alias_name="pkg", command="pkgmgr"):
    """
    Print PATH/alias instructions for the current shell.
    script_dir: directory where the pkgmgr console script lives (e.g. venv/bin).
    """
    if not script_dir:
        print("[install] script_dir not provided; skip shell integration")
        return
    shell = os.environ.get("SHELL", "")
    shell_name = os.path.basename(shell) if shell else ""

    try:
        lines = _instructions_for_shell(shell_name, script_dir, alias_name, command)
    except Exception as e:
        print("[install] shell integration failed for %s: %s" % (shell_name, str(e)))
        return

    if not lines:
        print("[install] unknown shell '%s'; skipping rc update" % (shell_name or ""))
        return

    if not _path_contains_dir(script_dir):
        print("[install] PATH missing: %s" % script_dir)
        print("[install] add to PATH, for example:")
        for line in _path_only_instructions(shell_name, script_dir):
            print("  " + line)

    header = "[install] To use pkgmgr, add these lines to your shell rc:"
    for line in _emit_lines_with_header(header, lines):
        print(line)
    readme_path = _write_readme(_emit_lines_with_header(header, lines))
    if readme_path:
        print("[install] Reference saved to: %s" % readme_path)


def _instructions_for_shell(shell_name, script_dir, alias_name, command):
    if shell_name == "bash":
        lines = [
            'export PATH="%s:$PATH"' % script_dir,
            'alias %s="%s"' % (alias_name, command),
        ]
        return lines
    if shell_name == "zsh":
        lines = [
            'export PATH="%s:$PATH"' % script_dir,
            'alias %s="%s"' % (alias_name, command),
        ]
        return lines
    if shell_name in ("csh", "tcsh"):
        lines = [
            "set path = (%s $path)" % script_dir,
            "alias %s %s" % (alias_name, command),
        ]
        return lines
    if shell_name == "fish":
        lines = [
            "set -U fish_user_paths %s $fish_user_paths" % script_dir,
            "alias %s %s" % (alias_name, command),
        ]
        return lines
    return None


def _path_only_instructions(shell_name, script_dir):
    if shell_name == "bash":
        return ['export PATH="%s:$PATH"' % script_dir]
    if shell_name == "zsh":
        return ['export PATH="%s:$PATH"' % script_dir]
    if shell_name in ("csh", "tcsh"):
        return ["set path = (%s $path)" % script_dir]
    if shell_name == "fish":
        return ["set -U fish_user_paths %s $fish_user_paths" % script_dir]
    return ['export PATH="%s:$PATH"' % script_dir]


def _path_contains_dir(path):
    if not path:
        return False
    try:
        target = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
    except Exception:
        target = path
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        try:
            entry_path = os.path.realpath(os.path.abspath(os.path.expanduser(entry)))
        except Exception:
            entry_path = entry
        if entry_path == target:
            return True
    return False


def _emit_lines_with_header(header, lines):
    out = [header]
    out.extend(lines)
    return out


def _write_readme(lines):
    readme_path = os.path.join(config.BASE_DIR, "README.txt")
    try:
        base_dir = os.path.dirname(readme_path)
        if base_dir and not os.path.exists(base_dir):
            os.makedirs(base_dir)
        with open(readme_path, "w") as f:
            for line in lines:
                f.write(line + "\n")
        return readme_path
    except Exception:
        return None
