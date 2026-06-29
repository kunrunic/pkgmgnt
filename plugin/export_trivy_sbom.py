#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import os
import re
import shutil
import subprocess
import sys
import time

from pkgmgr import config


def _resolve_pkg_dir(pkg_id, config_path=None):
    try:
        if config_path:
            main_cfg = config.load_main(path=config_path, allow_interactive=False)
        else:
            main_cfg = config.load_main(allow_interactive=False)
    except Exception:
        return None
    release_root = main_cfg.get("pkg_release_root")
    if not release_root:
        return None
    return os.path.abspath(os.path.expanduser(os.path.join(release_root, str(pkg_id))))


def _resolve_default_output_root(pkg_id, config_path=None):
    pkg_dir = _resolve_pkg_dir(pkg_id, config_path=config_path)
    if not pkg_dir:
        return None
    if not os.path.isdir(pkg_dir):
        raise RuntimeError("pkg not found: %s" % pkg_dir)
    return os.path.join(pkg_dir, "export", "trivy_sbom")


def _normalize_output_template(output_arg, output_root):
    path_template = output_arg or "bom_{pkg_id}_{YYYYMMDD}"
    path_template = os.path.expanduser(str(path_template))
    if os.sep not in path_template:
        path_template = os.path.join(output_root, path_template)
    if not path_template.lower().endswith(".cdx.json"):
        if path_template.lower().endswith(".json"):
            path_template = path_template[: -len(".json")] + ".cdx.json"
        else:
            path_template = path_template + ".cdx.json"
    return os.path.abspath(path_template)


def _normalize_report_template(report_arg, output_template):
    if report_arg:
        path_template = os.path.expanduser(str(report_arg))
        if os.sep not in path_template:
            path_template = os.path.join(os.path.dirname(output_template), path_template)
    else:
        if output_template.lower().endswith(".cdx.json"):
            path_template = output_template[: -len(".cdx.json")] + ".report.txt"
        else:
            path_template = output_template + ".report.txt"
    if not path_template.lower().endswith(".report.txt"):
        if path_template.lower().endswith(".txt"):
            path_template = path_template[: -len(".txt")] + ".report.txt"
        else:
            path_template = path_template + ".report.txt"
    return os.path.abspath(path_template)


def _render_static_tokens(path_template, pkg_id):
    if not path_template:
        return path_template
    return str(path_template).replace("{pkg_id}", str(pkg_id))


def _next_version(path_template):
    dir_path = os.path.dirname(path_template) or "."
    name_template = os.path.basename(path_template)
    regex = re.escape(name_template)
    regex = regex.replace(re.escape("{YYYYMMDD}"), r"\d{8}")
    regex = regex.replace(re.escape("{date}"), r"\d{8}")
    regex = regex.replace(re.escape("{datetime}"), r"\d{8}_\d{6}")
    regex = regex.replace(re.escape("{version}"), r"v(\d+)")
    regex = "^" + regex + "$"
    max_ver = 0
    if os.path.isdir(dir_path):
        for name in os.listdir(dir_path):
            m = re.match(regex, name)
            if not m:
                continue
            try:
                ver = int(m.group(1))
            except Exception:
                continue
            if ver > max_ver:
                max_ver = ver
    return max_ver + 1


def _resolve_template_path(path_template):
    date_str = time.strftime("%Y%m%d", time.localtime())
    datetime_str = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    base_dir = os.path.dirname(path_template) or "."
    name_template = os.path.basename(path_template)
    version = None
    if "{version}" in name_template:
        version = _next_version(os.path.join(base_dir, name_template))
    output_name = name_template.replace("{YYYYMMDD}", date_str).replace("{date}", date_str)
    output_name = output_name.replace("{datetime}", datetime_str)
    if version is not None:
        output_name = output_name.replace("{version}", "v%d" % version)
    return os.path.join(base_dir, output_name)


def _ensure_parent(path):
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent)


def _backup_existing(path):
    if not os.path.isfile(path):
        return None
    ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    backup_path = path + ".bak_" + ts
    shutil.copy2(path, backup_path)
    return backup_path


def _run_command(cmd):
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return {
        "cmd": cmd,
        "rc": proc.returncode,
        "stdout": proc.stdout.decode("utf-8", errors="replace"),
        "stderr": proc.stderr.decode("utf-8", errors="replace"),
    }


def _format_command(cmd):
    parts = []
    for item in cmd:
        text = str(item)
        if any(ch.isspace() for ch in text):
            parts.append('"%s"' % text.replace('"', '\\"'))
        else:
            parts.append(text)
    return " ".join(parts)


def _write_report(path, pkg_id, scan_path, sbom_path, rootfs_run, sbom_run):
    lines = [
        "[trivy_sbom] generated_at: %s" % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "[trivy_sbom] pkg_id: %s" % pkg_id,
        "[trivy_sbom] scan_path: %s" % scan_path,
        "[trivy_sbom] sbom_path: %s" % sbom_path,
        "",
        "## trivy rootfs",
        "command: %s" % _format_command(rootfs_run["cmd"]),
        "exit_code: %s" % rootfs_run["rc"],
        "",
        "### stdout",
        rootfs_run["stdout"].rstrip(),
        "",
        "### stderr",
        rootfs_run["stderr"].rstrip(),
        "",
        "## trivy sbom",
        "command: %s" % _format_command(sbom_run["cmd"]),
        "exit_code: %s" % sbom_run["rc"],
        "",
        "### stdout",
        sbom_run["stdout"].rstrip(),
        "",
        "### stderr",
        sbom_run["stderr"].rstrip(),
        "",
    ]
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(description="Export Trivy CycloneDX SBOM and viewer report.")
    parser.add_argument("--config", help="pkgmgr main config path")
    parser.add_argument("--pkg-id", required=True, help="pkg id (resolved via pkg_release_root)")
    parser.add_argument("--scan-path", help="rootfs path to scan (default: TRIVY_SBOM_SCAN_PATH)")
    parser.add_argument("--output", help="output template path (supports {YYYYMMDD}/{date}/{datetime} and {version})")
    parser.add_argument("--report", help="report template path (supports {YYYYMMDD}/{date}/{datetime} and {version})")
    args = parser.parse_args(argv)

    config_path = args.config or os.environ.get("PKGMGR_CONFIG")
    scan_path = args.scan_path or os.environ.get("TRIVY_SBOM_SCAN_PATH")
    if not scan_path:
        print("[export_trivy_sbom] scan path not specified; use --scan-path or TRIVY_SBOM_SCAN_PATH")
        return 1
    scan_path = os.path.abspath(os.path.expanduser(scan_path))

    output_root = os.environ.get("TRIVY_SBOM_OUTPUT_DIR")
    if output_root:
        output_root = os.path.abspath(os.path.expanduser(output_root))
    else:
        try:
            output_root = _resolve_default_output_root(args.pkg_id, config_path=config_path)
        except RuntimeError as exc:
            print("[export_trivy_sbom] %s" % str(exc))
            return 1
    if not output_root:
        print("[export_trivy_sbom] output root not found; set TRIVY_SBOM_OUTPUT_DIR or provide pkgmgr config")
        return 1

    output_template = _normalize_output_template(args.output, output_root)
    output_template = _render_static_tokens(output_template, args.pkg_id)
    report_template = _normalize_report_template(args.report, output_template)
    report_template = _render_static_tokens(report_template, args.pkg_id)
    output_path = _resolve_template_path(output_template)
    report_path = _resolve_template_path(report_template)

    _ensure_parent(output_path)
    _ensure_parent(report_path)

    output_backup = _backup_existing(output_path)
    report_backup = _backup_existing(report_path)
    if output_backup:
        print("[export_trivy_sbom] backup saved: %s" % output_backup)
    if report_backup:
        print("[export_trivy_sbom] backup saved: %s" % report_backup)

    rootfs_cmd = [
        "trivy",
        "rootfs",
        "--format",
        "cyclonedx",
        "--scanners",
        "vuln",
        "--output",
        output_path,
        scan_path,
    ]
    rootfs_run = _run_command(rootfs_cmd)

    sbom_cmd = ["trivy", "sbom", output_path]
    if rootfs_run["rc"] == 0:
        sbom_run = _run_command(sbom_cmd)
    else:
        sbom_run = {
            "cmd": sbom_cmd,
            "rc": rootfs_run["rc"],
            "stdout": "",
            "stderr": "skipped because trivy rootfs failed",
        }

    _write_report(report_path, args.pkg_id, scan_path, output_path, rootfs_run, sbom_run)
    print("[export_trivy_sbom] sbom saved: %s" % output_path)
    print("[export_trivy_sbom] report saved: %s" % report_path)

    if rootfs_run["rc"] != 0:
        return rootfs_run["rc"]
    return sbom_run["rc"]


if __name__ == "__main__":
    sys.exit(main())
