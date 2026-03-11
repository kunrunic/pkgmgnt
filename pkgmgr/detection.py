from __future__ import print_function
"""Detection engine: baseline vs current workspace changes."""

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import time

from . import config, snapshot


STATUS_CHANGED_NOT_UPDATED = "CHANGED_NOT_UPDATED"
STATUS_DELETED_NOT_UPDATED = "DELETED_NOT_UPDATED"
STATUS_TRACKED_CHANGED_NOT_IN_PKG = "TRACKED_CHANGED_NOT_IN_PKG"
STATUS_UNTRACKED_NOT_IN_PKG = "UNTRACKED_NOT_IN_PKG"
STATUS_CHANGED_BUT_UNUSED_CHECK_REQUIRED = "CHANGED_BUT_UNUSED_CHECK_REQUIRED"
STATUS_GIT_UNTRACKED = "GIT_UNTRACKED"
STATUS_GIT_CHANGED = "GIT_CHANGED"
STATUS_GIT_DELETED = "GIT_DELETED"
STATUS_AMBIGUOUS_PKG = "AMBIGUOUS_PKG"
REASON_DESC_KO = {
    STATUS_CHANGED_NOT_UPDATED: "open pkg 매핑 대상 파일이 baseline 대비 변경되었지만 pkg update에 반영되지 않음",
    STATUS_DELETED_NOT_UPDATED: "open pkg 매핑 대상 파일이 baseline 대비 삭제되었지만 pkg update에 반영되지 않음",
    STATUS_TRACKED_CHANGED_NOT_IN_PKG: "baseline 대비 변경되었으나 현재 open pkg 어디에도 매핑되지 않음",
    STATUS_UNTRACKED_NOT_IN_PKG: "baseline에 없던 신규 파일이며 현재 open pkg 어디에도 매핑되지 않음",
    STATUS_CHANGED_BUT_UNUSED_CHECK_REQUIRED: "변경은 감지되었으나 pkg 관리 대상 근거가 없어 사용 여부 확인이 필요함",
    STATUS_AMBIGUOUS_PKG: "둘 이상의 open pkg에 동시에 매핑되어 대상 pkg를 단정할 수 없음",
    STATUS_GIT_UNTRACKED: "git에서 untracked 상태로 감지됨",
    STATUS_GIT_CHANGED: "git에서 tracked 변경 상태로 감지됨",
    STATUS_GIT_DELETED: "git에서 삭제 상태로 감지됨",
}
LEGACY_STATUS_ALIASES = {
    "GIT_TRACKED_CHANGED_NOT_IN_PKG": STATUS_TRACKED_CHANGED_NOT_IN_PKG,
    "GIT_UNTRACKED_NOT_IN_PKG": STATUS_UNTRACKED_NOT_IN_PKG,
}


def _parse_ts(value):
    if not value:
        return 0
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y%m%dT%H%M%S"):
        try:
            return int(time.mktime(time.strptime(str(value), fmt)))
        except Exception:
            continue
    return 0


def _load_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _norm_abs(path):
    return os.path.normpath(os.path.abspath(os.path.expanduser(path)))


def _display_path(path, cwd=None):
    base = _norm_abs(cwd or os.getcwd())
    ap = _norm_abs(path)
    try:
        rel = os.path.relpath(ap, base)
        if not rel.startswith(".."):
            return rel.replace("\\", "/")
    except Exception:
        pass
    return ap.replace("\\", "/")


def _path_in_scope(path, scope):
    ap = _norm_abs(path)
    sp = _norm_abs(scope)
    if ap == sp:
        return True
    return ap.startswith(sp + os.sep)


def _load_baseline_entries():
    baseline_path = os.path.join(snapshot.STATE_DIR, "baseline.json")
    data = _load_json(baseline_path) or {}
    out = {}
    for section in ("sources", "artifacts"):
        sec = data.get(section) or {}
        for root, root_entries in sec.items():
            root_abs = _norm_abs(root)
            for rel, meta in (root_entries or {}).items():
                meta_out = {
                    "hash": (meta or {}).get("hash"),
                    "size": (meta or {}).get("size"),
                    "mtime": (meta or {}).get("mtime"),
                }
                out[_norm_abs(os.path.join(root_abs, rel))] = meta_out
    return out


def _load_baseline_paths():
    return set(_load_baseline_entries().keys())


def _sha256(path, chunk=1024 * 1024):
    h = hashlib.sha256()
    f = open(path, "rb")
    try:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    finally:
        f.close()
    return h.hexdigest()


def _scan_current_entries(cfg):
    entries = {}
    scopes = _configured_scan_scopes(cfg)
    for spec in scopes:
        root = _norm_abs(spec.get("root") or "")
        excludes = spec.get("exclude") or []
        if not root or not os.path.exists(root):
            continue
        for base, _, files in os.walk(root):
            for name in files:
                abspath = _norm_abs(os.path.join(base, name))
                rel = os.path.relpath(abspath, root).replace("\\", "/")
                if any(fnmatch.fnmatch(rel, p) for p in excludes):
                    continue
                try:
                    st = os.stat(abspath)
                    entries[abspath] = {
                        "hash": _sha256(abspath),
                        "size": int(st.st_size),
                        "mtime": int(st.st_mtime),
                    }
                except Exception:
                    continue
    return entries


def _collect_scope_diffs(cfg):
    baseline_entries = _load_baseline_entries()
    current_entries = _scan_current_entries(cfg)
    paths = set(baseline_entries.keys()) | set(current_entries.keys())
    items = []
    for path in sorted(paths):
        bmeta = baseline_entries.get(path)
        cmeta = current_entries.get(path)
        if bmeta and cmeta:
            if bmeta.get("hash") == cmeta.get("hash"):
                continue
            kind = "modified"
        elif cmeta and not bmeta:
            kind = "added"
        else:
            kind = "deleted"
        items.append({"path": path, "kind": kind, "baseline": bmeta, "current": cmeta})
    return baseline_entries, items


def _git_toplevel(path):
    try:
        out = subprocess.check_output(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        ).strip()
        if out:
            return _norm_abs(out)
    except Exception:
        return None
    return None


def _discover_git_roots(cfg):
    roots = []
    seen = set()
    candidates = []
    git_cfg = cfg.get("git") or {}
    repo_root = git_cfg.get("repo_root")
    if repo_root:
        candidates.append(repo_root)
    candidates.extend(cfg.get("sources") or [])
    candidates.append(os.getcwd())
    for c in candidates:
        cpath = _norm_abs(c)
        top = _git_toplevel(cpath)
        if not top:
            continue
        if top in seen:
            continue
        seen.add(top)
        roots.append(top)
    return roots


def _configured_scan_scopes(cfg):
    scopes = []
    seen = set()
    src_exclude = ((cfg.get("source") or {}).get("exclude") or [])
    for src in (cfg.get("sources") or []):
        ap = _norm_abs(src)
        if ap not in seen:
            seen.add(ap)
            scopes.append({"root": ap, "exclude": list(src_exclude)})

    artifacts_cfg = cfg.get("artifacts") or {}
    art_root = artifacts_cfg.get("root")
    targets = artifacts_cfg.get("targets") or []
    art_exclude = artifacts_cfg.get("exclude") or []
    base_root = _norm_abs(art_root) if art_root else None
    for t in targets:
        t = str(t)
        if base_root and not os.path.isabs(t):
            ap = _norm_abs(os.path.join(base_root, t))
        else:
            ap = _norm_abs(t)
        if ap not in seen:
            seen.add(ap)
            scopes.append({"root": ap, "exclude": list(art_exclude)})
    return scopes


def _iter_git_changes(repo_root):
    try:
        out = subprocess.check_output(
            ["git", "-C", repo_root, "status", "--porcelain=1", "-z", "--untracked-files=all"],
            stderr=subprocess.STDOUT,
        )
    except Exception:
        return []

    records = out.split(b"\x00")
    if records and records[-1] == b"":
        records = records[:-1]

    items = []
    i = 0
    while i < len(records):
        rec = records[i].decode("utf-8", errors="replace")
        if len(rec) < 3:
            i += 1
            continue
        xy = rec[:2]
        path = rec[3:]
        if "R" in xy or "C" in xy:
            if i + 1 < len(records):
                i += 1
                path = records[i].decode("utf-8", errors="replace")
        i += 1

        if xy == "!!":
            continue
        if xy == "??":
            kind = "untracked"
        elif "D" in xy:
            kind = "deleted"
        else:
            kind = "tracked"

        ap = _norm_abs(os.path.join(repo_root, path))
        items.append({"repo_root": repo_root, "path": ap, "xy": xy, "kind": kind})
    return items


def _dedupe_changes(items):
    rank = {"deleted": 3, "untracked": 2, "tracked": 1}
    by_path = {}
    for it in items:
        key = _norm_abs(it["path"])
        prev = by_path.get(key)
        if not prev or rank.get(it["kind"], 0) >= rank.get(prev["kind"], 0):
            by_path[key] = it
    return [by_path[k] for k in sorted(by_path.keys())]


def _is_excluded_under_root(path, root, patterns):
    rel = os.path.relpath(_norm_abs(path), _norm_abs(root)).replace("\\", "/")
    for pat in patterns or []:
        if fnmatch.fnmatch(rel, pat):
            return True
    return False


def _filter_changes_by_scopes(items, scopes):
    if not scopes:
        return items
    filtered = []
    for it in items:
        path = _norm_abs(it["path"])
        keep = False
        for spec in scopes:
            root = spec.get("root")
            if not root:
                continue
            if _path_in_scope(path, root):
                if _is_excluded_under_root(path, root, spec.get("exclude") or []):
                    keep = False
                    break
                keep = True
                break
        if keep:
            filtered.append(it)
    return filtered


def _latest_update_meta(pkg_id):
    updates_dir = os.path.join(config.DEFAULT_STATE_DIR, "pkg", str(pkg_id), "updates")
    if not os.path.isdir(updates_dir):
        return {"ts_raw": None, "ts": 0, "files": set()}
    latest_name = None
    latest_score = 0
    for name in os.listdir(updates_dir):
        if not name.startswith("update-") or not name.endswith(".json"):
            continue
        ts_raw = name[len("update-"):-len(".json")]
        score = _parse_ts(ts_raw)
        if score >= latest_score:
            latest_score = score
            latest_name = name
    files = set()
    if latest_name:
        data = _load_json(os.path.join(updates_dir, latest_name)) or {}
        checksums = data.get("checksums") or {}
        for group in ("git_files", "release_files"):
            for path in (checksums.get(group) or {}).keys():
                files.add(_norm_abs(path))
    return {
        "ts_raw": latest_name[len("update-"):-len(".json")] if latest_name else None,
        "ts": latest_score,
        "files": files,
    }


def _discover_open_pkgs(cfg):
    root = _norm_abs(cfg.get("pkg_release_root") or "")
    if not root or not os.path.isdir(root):
        return []
    pkgs = []
    for name in sorted(os.listdir(root)):
        pkg_dir = os.path.join(root, name)
        if not os.path.isdir(pkg_dir):
            continue
        pkg_cfg_path = os.path.join(pkg_dir, "pkg.yaml")
        if not os.path.isfile(pkg_cfg_path):
            continue
        try:
            pkg_cfg = config.load_pkg_config(pkg_cfg_path) or {}
        except Exception as exc:
            print("[detection] skip invalid pkg config %s: %s" % (pkg_cfg_path, str(exc)))
            continue
        status = ((pkg_cfg.get("pkg") or {}).get("status") or "").strip().lower()
        if status != "open":
            continue
        include_releases = ((pkg_cfg.get("include") or {}).get("releases") or [])
        scopes = []
        for rel in include_releases:
            scopes.append(_norm_abs(os.path.join(pkg_dir, str(rel))))
        update_meta = _latest_update_meta(name)
        pkgs.append(
            {
                "pkg_id": str(name),
                "pkg_dir": _norm_abs(pkg_dir),
                "scopes": scopes,
                "latest_update_ts": update_meta["ts"],
                "latest_update_ts_raw": update_meta["ts_raw"],
                "latest_update_files": update_meta["files"],
            }
        )
    return pkgs


def _candidates_for_path(path, open_pkgs):
    ap = _norm_abs(path)
    cands = []
    for p in open_pkgs:
        matched = False
        for scope in p["scopes"]:
            if _path_in_scope(ap, scope):
                matched = True
                break
        if not matched and ap in p["latest_update_files"]:
            matched = True
        if matched:
            cands.append(p)
    return cands


def _pick_pkg(candidates):
    if not candidates:
        return None, None
    ordered = sorted(
        candidates,
        key=lambda c: (c.get("latest_update_ts") or 0, c.get("pkg_id")),
        reverse=True,
    )
    top = ordered[0]
    top_ts = top.get("latest_update_ts") or 0
    if top_ts == 0:
        return None, ordered
    ties = [c for c in ordered if (c.get("latest_update_ts") or 0) == top_ts]
    if len(ties) > 1:
        return None, ties
    return top, None


def _artifact_target(path):
    jam_class, jam_name = _artifact_target_from_jam(path)
    if jam_class and jam_name:
        return jam_class, jam_name
    ap = _norm_abs(path)
    norm = ap.replace("\\", "/")
    parts = [p for p in norm.split("/") if p]
    base = os.path.basename(ap)
    lower = base.lower()

    for label in ("bin", "lib", "data"):
        if label in parts:
            idx = parts.index(label)
            name = parts[idx + 1] if idx + 1 < len(parts) else base
            return label, name
    if lower.endswith(".lua"):
        return "lua", base
    if lower.endswith(".sh"):
        return "sh", base
    if lower.endswith(".sql"):
        return "sql", base
    if lower.endswith((".csv", ".dat", ".json", ".xml", ".yaml", ".yml", ".txt")):
        return "data", base
    return "etc", base


def _artifact_target_from_jam(path):
    """
    Best-effort Jamfile parser:
    - finds nearest Jamfile/Jamrules upwards
    - matches statements that mention current source filename
    - infers class/name from rule keyword
    """
    ap = _norm_abs(path)
    base = os.path.basename(ap)
    if not base:
        return None, None
    rules = {
        "library": "lib",
        "sharedlibrary": "lib",
        "main": "bin",
        "program": "bin",
        "executable": "bin",
    }
    cur = os.path.dirname(ap)
    stop = _norm_abs(os.path.expanduser("~"))
    while cur and len(cur) >= len(stop):
        jam_path = os.path.join(cur, "Jamfile")
        if not os.path.isfile(jam_path):
            jam_path = os.path.join(cur, "Jamrules")
        if os.path.isfile(jam_path):
            parsed = _parse_jam_for_source(jam_path, base, rules)
            if parsed:
                return parsed
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None, None


def _parse_jam_for_source(jam_path, source_basename, rules):
    try:
        with open(jam_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception:
        return None
    text = re.sub(r"#.*", "", text)
    statements = [s.strip() for s in text.split(";") if s.strip()]

    vars_map = {}
    assign_re = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(\+?=)\s*(.*)$", re.S)
    var_only_re = re.compile(r"^\$\(([A-Za-z_][A-Za-z0-9_]*)\)$")
    var_ref_re = re.compile(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)")

    def _tokenize(raw):
        return [t for t in re.split(r"\s+", str(raw or "").strip()) if t]

    def _expand_token(tok, depth=0):
        if depth > 6:
            return [tok]
        t = str(tok or "").strip()
        if not t:
            return []
        m = var_only_re.match(t)
        if m:
            key = m.group(1)
            vals = vars_map.get(key) or []
            out = []
            for v in vals:
                out.extend(_expand_token(v, depth + 1))
            return out
        # Handle mixed patterns like "$(LIB_NAME)$(SUFLIB)" or "pre_$(X)_post".
        if "$(" in t:
            spans = []
            pos = 0
            for mref in var_ref_re.finditer(t):
                if mref.start() > pos:
                    spans.append(("lit", t[pos:mref.start()]))
                spans.append(("var", mref.group(1)))
                pos = mref.end()
            if pos < len(t):
                spans.append(("lit", t[pos:]))

            results = [""]
            unresolved = False
            for kind, val in spans:
                if kind == "lit":
                    results = [r + val for r in results]
                    continue
                vals = vars_map.get(val)
                if not vals:
                    unresolved = True
                    literal = "$(%s)" % val
                    results = [r + literal for r in results]
                    continue
                expanded_vals = []
                for v in vals:
                    expanded_vals.extend(_expand_token(v, depth + 1))
                next_results = []
                for r in results:
                    for ev in expanded_vals:
                        next_results.append(r + str(ev))
                results = next_results or results
            if unresolved and not results:
                return [t]
            return results
        return [t]

    # Pass 1: collect variable assignments.
    for st in statements:
        st_norm = str(st).lstrip("} \t\r\n")
        m = assign_re.match(st_norm)
        if not m:
            continue
        key = m.group(1)
        op = m.group(2)
        raw = m.group(3) or ""
        vals = _tokenize(raw)
        if op == "+=":
            vars_map.setdefault(key, [])
            vars_map[key].extend(vals)
        else:
            vars_map[key] = vals

    def _is_unresolved_target(token):
        t = str(token or "").strip()
        if not t:
            return True
        return ("$(" in t) or t.startswith("<") or t.startswith("[")

    def _best_effort_target(token):
        t = str(token or "").strip()
        if not t:
            return ""
        # Keep resolved literal part if mixed unresolved vars remain, e.g. libcdrdb$(SUFLIB) -> libcdrdb
        t = re.sub(r"\$\([^)]+\)", "", t).strip()
        t = t.strip(".-_ ")
        return t

    def _rule_to_class(rule):
        r = str(rule or "").lower()
        if r in ("library", "sharedlibrary"):
            return "lib"
        if r in ("main", "program", "executable"):
            return "bin"
        if r.startswith("install"):
            if "lib" in r:
                return "lib"
            if "lua" in r:
                return "lua"
            if "sql" in r:
                return "sql"
            if "script" in r or "sh" in r:
                return "sh"
            if "data" in r or "file" in r:
                return "data"
            if "bin" in r or "exec" in r:
                return "bin"
            return "data"
        return None

    candidates = []
    stmt_re = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+([^\s:;]+)\s*:(.*)$", re.S)
    for st in statements:
        st_norm = str(st).lstrip("} \t\r\n")
        if assign_re.match(st_norm):
            continue
        m = stmt_re.match(st_norm)
        if not m:
            continue
        rule = (m.group(1) or "").strip().lower()
        target_raw = (m.group(2) or "").strip()
        body_raw = (m.group(3) or "").strip()
        cls = _rule_to_class(rule) or rules.get(rule)
        if not cls:
            continue

        body_tokens = []
        for tok in _tokenize(body_raw):
            body_tokens.extend(_expand_token(tok))
        body_basenames = set([os.path.basename(t) for t in body_tokens])
        if source_basename not in body_basenames:
            continue

        target_tokens = _expand_token(target_raw)
        if not target_tokens:
            target_tokens = [target_raw]
        for t in target_tokens:
            t = str(t).strip()
            if not t:
                continue
            if _is_unresolved_target(t):
                best = _best_effort_target(t)
                t = best if best else os.path.splitext(source_basename)[0]
            candidates.append((cls, os.path.basename(t)))

    if not candidates:
        return None

    # Keep all matching names in same class to avoid arbitrary loss when multiple targets exist.
    by_class = {}
    for cls, name in candidates:
        by_class.setdefault(cls, set()).add(name)
    class_order = ["bin", "lib", "lua", "sh", "sql", "data", "etc"]
    selected_class = sorted(by_class.keys(), key=lambda c: class_order.index(c) if c in class_order else 99)[0]
    names = sorted(by_class.get(selected_class) or [])
    return selected_class, ",".join(names)


def _should_ignore(path, patterns):
    ap = _norm_abs(path)
    rel = _display_path(ap)
    for pat in patterns or []:
        if fnmatch.fnmatch(ap, pat) or fnmatch.fnmatch(rel, pat):
            return True
    return False


def _classify(change, open_pkgs, baseline_paths):
    path = _norm_abs(change["path"])
    candidates = _candidates_for_path(path, open_pkgs)
    selected_pkg, ties = _pick_pkg(candidates)
    if ties:
        return {
            "status": STATUS_AMBIGUOUS_PKG,
            "pkg_id": "AMBIGUOUS",
            "path": path,
            "kind": change["kind"],
            "candidates": [c["pkg_id"] for c in ties],
            "tie_ts": ties[0].get("latest_update_ts_raw"),
            "in_baseline": path in baseline_paths,
        }

    if selected_pkg:
        if change["kind"] == "deleted":
            status = STATUS_DELETED_NOT_UPDATED
        elif change["kind"] == "added":
            status = STATUS_UNTRACKED_NOT_IN_PKG
        else:
            status = STATUS_CHANGED_NOT_UPDATED
        return {
            "status": status,
            "pkg_id": selected_pkg["pkg_id"],
            "path": path,
            "kind": change["kind"],
            "in_baseline": path in baseline_paths,
        }

    if change["kind"] == "added":
        status = STATUS_UNTRACKED_NOT_IN_PKG
    else:
        status = STATUS_TRACKED_CHANGED_NOT_IN_PKG
    return {
        "status": status,
        "pkg_id": "NO_PKG",
        "path": path,
        "kind": change["kind"],
        "in_baseline": path in baseline_paths,
    }


def _group_results(items, cwd=None):
    grouped = {}
    for it in items:
        pkg = it["pkg_id"]
        cls, name = _artifact_target(it["path"])
        target = "%s=%s" % (cls, name)
        reason = it["status"]
        path_disp = _display_path(it["path"], cwd=cwd)
        pkg_map = grouped.setdefault(pkg, {})
        target_map = pkg_map.setdefault(target, {})
        target_map.setdefault(reason, [])
        if path_disp not in target_map[reason]:
            target_map[reason].append(path_disp)
    for pkg_map in grouped.values():
        for target_map in pkg_map.values():
            for reason in target_map:
                target_map[reason] = sorted(target_map[reason])
    return grouped


def _split_scope_git_items(items):
    managed_items = []
    unmanaged_items = []
    for it in items:
        path = it.get("path")
        target_cls, _ = _artifact_target(path)
        is_unmanaged = (
            str(it.get("pkg_id") or "") == "NO_PKG"
            and not bool(it.get("in_baseline"))
            and target_cls == "etc"
        )
        if is_unmanaged:
            unmanaged = dict(it)
            unmanaged["status"] = STATUS_CHANGED_BUT_UNUSED_CHECK_REQUIRED
            unmanaged_items.append(unmanaged)
        else:
            managed_items.append(it)
    return managed_items, unmanaged_items


def _normalize_status_list(values):
    normalized = []
    for v in (values or []):
        key = str(v).strip()
        if not key:
            continue
        mapped = LEGACY_STATUS_ALIASES.get(key, key)
        normalized.append(mapped)
    return normalized


def _count_by_reason(items):
    out = {}
    for item in items:
        key = item.get("status")
        out[key] = out.get(key, 0) + 1
    return out


def _merge_counts(*counts):
    merged = {}
    for m in counts:
        for k, v in (m or {}).items():
            merged[k] = merged.get(k, 0) + int(v)
    return merged


def _format_reason_line(reason, count):
    desc = REASON_DESC_KO.get(str(reason), "")
    if desc:
        return "  %s: %d (%s)" % (reason, count, desc)
    return "  %s: %d" % (reason, count)


def _format_open_pkg_ids(open_pkgs, max_count=8, max_chars=120):
    ids = sorted([str(p.get("pkg_id")) for p in (open_pkgs or []) if p.get("pkg_id")])
    if not ids:
        return "none"
    shown = []
    for pkg_id in ids:
        candidate = ",".join(shown + [pkg_id])
        if len(shown) >= int(max_count) or len(candidate) > int(max_chars):
            break
        shown.append(pkg_id)
    skipped = len(ids) - len(shown)
    if skipped > 0:
        return "%s ...(+%d skipped)" % (",".join(shown), skipped)
    return ",".join(shown)


def _git_status_to_reason(kind):
    if kind == "untracked":
        return STATUS_GIT_UNTRACKED
    if kind == "deleted":
        return STATUS_GIT_DELETED
    return STATUS_GIT_CHANGED


def _map_pkg_id_for_path(path, open_pkgs):
    candidates = _candidates_for_path(path, open_pkgs)
    selected_pkg, ties = _pick_pkg(candidates)
    if ties:
        return "AMBIGUOUS"
    if selected_pkg:
        return selected_pkg["pkg_id"]
    return "NO_PKG"


def _collect_git_view(cfg, open_pkgs, ignore_patterns):
    git_roots = _discover_git_roots(cfg)
    allowed_scopes = _configured_scan_scopes(cfg)
    all_changes = []
    for root in git_roots:
        all_changes.extend(_iter_git_changes(root))
    all_changes = _dedupe_changes(all_changes)
    scoped = _filter_changes_by_scopes(all_changes, allowed_scopes)
    filtered = [c for c in scoped if not _should_ignore(c["path"], ignore_patterns)]
    items = []
    for c in filtered:
        items.append(
            {
                "pkg_id": _map_pkg_id_for_path(c["path"], open_pkgs),
                "path": c["path"],
                "status": _git_status_to_reason(c.get("kind")),
                "kind": c.get("kind"),
            }
        )
    return {
        "all_changes": all_changes,
        "scoped": scoped,
        "filtered": filtered,
        "items": items,
    }


def run(cfg, emit=True):
    detection_cfg = cfg.get("detection") or {}
    run_at = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime())
    system_name = str(detection_cfg.get("system") or "").strip()
    if not detection_cfg.get("enabled", True):
        if emit:
            print("[detection] disabled by config (detection.enabled=false)")
        return {"exit_code": 0, "items": [], "run_at": run_at, "system": system_name}

    ignore_patterns = detection_cfg.get("ignore") or []
    fail_on = set(_normalize_status_list(detection_cfg.get("fail_on") or []))
    warn_on = set(_normalize_status_list(detection_cfg.get("warn_on") or []))

    baseline_entries, all_scope_changes = _collect_scope_diffs(cfg)
    baseline_paths = set(baseline_entries.keys())
    open_pkgs = _discover_open_pkgs(cfg)
    filtered = [c for c in all_scope_changes if not _should_ignore(c["path"], ignore_patterns)]
    classified = [_classify(c, open_pkgs, baseline_paths) for c in filtered]

    managed_items, unmanaged_items = _split_scope_git_items(classified)
    git_collect = _collect_git_view(cfg, open_pkgs, ignore_patterns)
    git_items = git_collect["items"]
    managed_by_reason = _count_by_reason(managed_items)
    unmanaged_by_reason = _count_by_reason(unmanaged_items)
    by_reason = _merge_counts(managed_by_reason, unmanaged_by_reason)
    git_by_reason = _count_by_reason(git_items)
    fail_count = sum(by_reason.get(k, 0) for k in fail_on)
    warn_count = sum(by_reason.get(k, 0) for k in warn_on) + len(git_items)
    managed_view = _group_results(managed_items)
    unmanaged_view = _group_results(unmanaged_items)
    git_view = _group_results(git_items)
    ambiguous = [it for it in classified if it["status"] == STATUS_AMBIGUOUS_PKG]

    exit_code = 2 if fail_count > 0 else 0
    if emit:
        print("[detection] summary")
        if system_name:
            print("  system: %s" % system_name)
        print("  run_at: %s" % run_at)
        print("  scanned_changes: %d" % len(all_scope_changes))
        print("  scoped_changes: %d" % len(all_scope_changes))
        print("  considered_changes: %d" % len(filtered))
        print("  baseline_files: %d" % len(baseline_paths))
        print("  open_pkgs: %d" % len(open_pkgs))
        print("  open_pkg_ids: %s" % _format_open_pkg_ids(open_pkgs))
        fail_policy = ",".join(sorted(fail_on)) if fail_on else "none"
        warn_policy = ",".join(sorted(warn_on)) if warn_on else "none"
        print("  fail: %d (policy: detection.fail_on=%s)" % (fail_count, fail_policy))
        print(
            "  warn: %d (policy: detection.warn_on=%s + git_by_reason)"
            % (warn_count, warn_policy)
        )

        print("")
        print("[detection] managed_by_reason")
        if not managed_by_reason:
            print("  none: 0")
        else:
            for key in sorted(managed_by_reason.keys()):
                print(_format_reason_line(key, managed_by_reason[key]))

        print("")
        print("[detection] unmanaged_by_reason")
        if not unmanaged_by_reason:
            print("  none: 0")
        else:
            for key in sorted(unmanaged_by_reason.keys()):
                print(_format_reason_line(key, unmanaged_by_reason[key]))

        print("")
        print("[detection] by_reason")
        if not by_reason:
            print("  none: 0")
        else:
            for key in sorted(by_reason.keys()):
                print(_format_reason_line(key, by_reason[key]))

        print("")
        print("[detection] git_by_reason")
        if not git_by_reason:
            print("  none: 0")
        else:
            for key in sorted(git_by_reason.keys()):
                print(_format_reason_line(key, git_by_reason[key]))

        print("")
        print("[detection] managed_view")
        if not managed_view:
            print("  no changes")
            print("")
        else:
            for pkg in sorted(managed_view.keys()):
                print("  pkg=%s" % pkg)
                targets = managed_view[pkg]
                for target in sorted(targets.keys()):
                    print("    %s" % target)
                    reasons = targets[target]
                    for reason in sorted(reasons.keys()):
                        print("      %s" % reason)
                        for p in reasons[reason]:
                            print("        - %s" % p)
                print("")

        print("[detection] unmanaged_view")
        if not unmanaged_view:
            print("  no changes")
            print("")
        else:
            for pkg in sorted(unmanaged_view.keys()):
                print("  pkg=%s" % pkg)
                targets = unmanaged_view[pkg]
                for target in sorted(targets.keys()):
                    print("    %s" % target)
                    reasons = targets[target]
                    for reason in sorted(reasons.keys()):
                        print("      %s" % reason)
                        for p in reasons[reason]:
                            print("        - %s" % p)
                print("")

        print("[detection] git_view")
        if not git_view:
            print("  no changes")
        else:
            for pkg in sorted(git_view.keys()):
                print("  pkg=%s" % pkg)
                targets = git_view[pkg]
                for target in sorted(targets.keys()):
                    print("    %s" % target)
                    reasons = targets[target]
                    for reason in sorted(reasons.keys()):
                        print("      %s" % reason)
                        for p in reasons[reason]:
                            print("        - %s" % p)
                print("")

        if ambiguous:
            print("[detection] ambiguous_only")
            for it in ambiguous:
                print(
                    "  - file=%s candidates=%s latest_update_tie=%s"
                    % (
                        _display_path(it["path"]),
                        "[" + ",".join(it.get("candidates") or []) + "]",
                        it.get("tie_ts"),
                    )
                )
            print("")

        print("[detection] result")
        print("  exit_code: %d" % exit_code)
    return {
        "exit_code": exit_code,
        "run_at": run_at,
        "system": system_name,
        "items": classified,
        "managed_items": managed_items,
        "unmanaged_items": unmanaged_items,
        "by_reason": by_reason,
        "managed_by_reason": managed_by_reason,
        "unmanaged_by_reason": unmanaged_by_reason,
        "git_by_reason": git_by_reason,
        "managed_view": managed_view,
        "unmanaged_view": unmanaged_view,
        "scope_view": managed_view,
        "git_view": git_view,
        "grouped": managed_view,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "scanned_changes": len(all_scope_changes),
        "considered_changes": len(filtered),
        "git_considered_changes": len(git_collect["filtered"]),
    }
