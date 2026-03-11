import sys
from importlib import import_module, reload
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

detection = import_module("pkgmgr.detection")
reload(detection)


def test_detection_groups_and_exit_code(monkeypatch):
    cfg = {
        "detection": {
            "enabled": True,
            "ignore": [],
            "fail_on": ["TRACKED_CHANGED_NOT_IN_PKG", "UNTRACKED_NOT_IN_PKG"],
            "warn_on": ["CHANGED_NOT_UPDATED", "DELETED_NOT_UPDATED"],
        }
    }
    open_pkgs = [
        {
            "pkg_id": "R680",
            "scopes": ["/repo/release/R680/bin"],
            "latest_update_ts": 200,
            "latest_update_ts_raw": "20260305T120000",
            "latest_update_files": set(),
        }
    ]
    changes = [
        {"path": "/repo/release/R680/bin/billingd", "kind": "modified"},
        {"path": "/repo/release/R680/bin/old.bin", "kind": "deleted"},
        {"path": "/repo/scripts/new_tool.sh", "kind": "added"},
    ]

    monkeypatch.setattr(detection, "_collect_scope_diffs", lambda _cfg: ({}, changes))
    monkeypatch.setattr(detection, "_discover_open_pkgs", lambda _cfg: open_pkgs)
    monkeypatch.setattr(
        detection,
        "_collect_git_view",
        lambda _cfg, _open_pkgs, _ignore: {
            "all_changes": [{"path": "/repo/scripts/new_tool.sh", "kind": "untracked"}],
            "scoped": [{"path": "/repo/scripts/new_tool.sh", "kind": "untracked"}],
            "filtered": [{"path": "/repo/scripts/new_tool.sh", "kind": "untracked"}],
            "items": [
                {
                    "pkg_id": "NO_PKG",
                    "path": "/repo/scripts/new_tool.sh",
                    "status": "GIT_UNTRACKED",
                    "kind": "untracked",
                }
            ],
        },
    )

    result = detection.run(cfg)
    assert result["by_reason"]["CHANGED_NOT_UPDATED"] == 1
    assert result["by_reason"]["DELETED_NOT_UPDATED"] == 1
    assert result["by_reason"]["UNTRACKED_NOT_IN_PKG"] == 1
    assert result["managed_by_reason"]["UNTRACKED_NOT_IN_PKG"] == 1
    assert result["unmanaged_by_reason"] == {}
    assert result["git_by_reason"]["GIT_UNTRACKED"] == 1
    git_paths = result["git_view"]["NO_PKG"]["sh=new_tool.sh"]["GIT_UNTRACKED"]
    assert len(git_paths) == 1
    assert git_paths[0].endswith("/repo/scripts/new_tool.sh")
    assert result["exit_code"] == 2


def test_detection_keeps_untracked_in_scope_when_baseline_has_path(monkeypatch):
    cfg = {
        "detection": {
            "enabled": True,
            "ignore": [],
            "fail_on": ["TRACKED_CHANGED_NOT_IN_PKG"],
            "warn_on": [],
        }
    }
    changes = [
        {"path": "/repo/existing/generated.c", "kind": "modified"},
    ]
    monkeypatch.setattr(
        detection,
        "_collect_scope_diffs",
        lambda _cfg: ({"/repo/existing/generated.c": {"hash": "aaa"}}, changes),
    )
    monkeypatch.setattr(detection, "_discover_open_pkgs", lambda _cfg: [])
    monkeypatch.setattr(
        detection,
        "_collect_git_view",
        lambda _cfg, _open_pkgs, _ignore: {
            "all_changes": [],
            "scoped": [],
            "filtered": [],
            "items": [],
        },
    )

    result = detection.run(cfg, emit=False)
    assert result["by_reason"]["TRACKED_CHANGED_NOT_IN_PKG"] == 1
    assert result["git_by_reason"] == {}
    assert result["exit_code"] == 2


def test_detection_marks_etc_untracked_as_unmanaged(monkeypatch):
    cfg = {
        "detection": {
            "enabled": True,
            "ignore": [],
            "fail_on": ["CHANGED_BUT_UNUSED_CHECK_REQUIRED"],
            "warn_on": [],
        }
    }
    changes = [
        {"path": "/repo/misc/README.unknown", "kind": "added"},
    ]
    monkeypatch.setattr(detection, "_collect_scope_diffs", lambda _cfg: ({}, changes))
    monkeypatch.setattr(detection, "_discover_open_pkgs", lambda _cfg: [])
    monkeypatch.setattr(
        detection,
        "_collect_git_view",
        lambda _cfg, _open_pkgs, _ignore: {
            "all_changes": [{"path": "/repo/misc/README.unknown", "kind": "untracked"}],
            "scoped": [{"path": "/repo/misc/README.unknown", "kind": "untracked"}],
            "filtered": [{"path": "/repo/misc/README.unknown", "kind": "untracked"}],
            "items": [
                {
                    "pkg_id": "NO_PKG",
                    "path": "/repo/misc/README.unknown",
                    "status": "GIT_UNTRACKED",
                    "kind": "untracked",
                }
            ],
        },
    )

    result = detection.run(cfg, emit=False)
    assert result["managed_by_reason"] == {}
    assert result["unmanaged_by_reason"]["CHANGED_BUT_UNUSED_CHECK_REQUIRED"] == 1
    assert result["git_by_reason"]["GIT_UNTRACKED"] == 1
    assert result["exit_code"] == 2


def test_detection_marks_ambiguous_when_latest_timestamp_tie(monkeypatch):
    cfg = {
        "detection": {
            "enabled": True,
            "ignore": [],
            "fail_on": ["AMBIGUOUS_PKG"],
            "warn_on": [],
        }
    }
    open_pkgs = [
        {
            "pkg_id": "R680",
            "scopes": ["/repo/shared"],
            "latest_update_ts": 100,
            "latest_update_ts_raw": "20260305T120000",
            "latest_update_files": set(),
        },
        {
            "pkg_id": "R681",
            "scopes": ["/repo/shared"],
            "latest_update_ts": 100,
            "latest_update_ts_raw": "20260305T120000",
            "latest_update_files": set(),
        },
    ]
    changes = [
        {"path": "/repo/shared/version.h", "kind": "modified"},
    ]

    monkeypatch.setattr(detection, "_collect_scope_diffs", lambda _cfg: ({}, changes))
    monkeypatch.setattr(detection, "_discover_open_pkgs", lambda _cfg: open_pkgs)
    monkeypatch.setattr(
        detection,
        "_collect_git_view",
        lambda _cfg, _open_pkgs, _ignore: {
            "all_changes": [],
            "scoped": [],
            "filtered": [],
            "items": [],
        },
    )

    result = detection.run(cfg)
    assert result["by_reason"]["AMBIGUOUS_PKG"] == 1
    assert result["exit_code"] == 2


def test_git_differences_affect_warn_only(monkeypatch):
    cfg = {
        "detection": {
            "enabled": True,
            "ignore": [],
            "fail_on": ["TRACKED_CHANGED_NOT_IN_PKG"],
            "warn_on": [],
        }
    }
    monkeypatch.setattr(detection, "_collect_scope_diffs", lambda _cfg: ({}, []))
    monkeypatch.setattr(detection, "_discover_open_pkgs", lambda _cfg: [])
    monkeypatch.setattr(
        detection,
        "_collect_git_view",
        lambda _cfg, _open_pkgs, _ignore: {
            "all_changes": [{"path": "/repo/a.c", "kind": "tracked"}],
            "scoped": [{"path": "/repo/a.c", "kind": "tracked"}],
            "filtered": [{"path": "/repo/a.c", "kind": "tracked"}],
            "items": [
                {
                    "pkg_id": "NO_PKG",
                    "path": "/repo/a.c",
                    "status": "GIT_CHANGED",
                    "kind": "tracked",
                }
            ],
        },
    )

    result = detection.run(cfg, emit=False)
    assert result["fail_count"] == 0
    assert result["warn_count"] == 1
    assert result["git_by_reason"]["GIT_CHANGED"] == 1
    assert result["exit_code"] == 0


def test_detection_applies_ignore_patterns(monkeypatch):
    cfg = {
        "detection": {
            "enabled": True,
            "ignore": ["**/unit_test/**"],
            "fail_on": ["TRACKED_CHANGED_NOT_IN_PKG", "UNTRACKED_NOT_IN_PKG"],
            "warn_on": [],
        },
    }
    changes = [
        {"path": "/repo/in_scope/src/main.c", "kind": "modified"},
        {"path": "/repo/in_scope/src/unit_test/test_main.c", "kind": "modified"},
    ]
    monkeypatch.setattr(detection, "_collect_scope_diffs", lambda _cfg: ({}, changes))
    monkeypatch.setattr(detection, "_discover_open_pkgs", lambda _cfg: [])
    monkeypatch.setattr(
        detection,
        "_collect_git_view",
        lambda _cfg, _open_pkgs, _ignore: {
            "all_changes": [],
            "scoped": [],
            "filtered": [],
            "items": [],
        },
    )

    result = detection.run(cfg, emit=False)
    assert len(result["items"]) == 1
    assert result["items"][0]["path"].endswith("/repo/in_scope/src/main.c")


def test_collect_scope_diffs_detects_added_modified_deleted(tmp_path, monkeypatch):
    cfg = {
        "sources": [str(tmp_path / "src")],
        "source": {"exclude": []},
        "artifacts": {"root": None, "targets": [], "exclude": []},
        "detection": {"enabled": True, "ignore": [], "fail_on": [], "warn_on": []},
    }
    src = tmp_path / "src"
    src.mkdir()
    keep = src / "keep.c"
    keep.write_text("same\n")
    mod = src / "mod.c"
    mod.write_text("after\n")
    added = src / "added.c"
    added.write_text("new\n")

    baseline = {
        "sources": {
            str(src): {
                "keep.c": {"hash": detection._sha256(str(keep)), "size": 5, "mtime": 1},
                "mod.c": {"hash": "before-hash", "size": 6, "mtime": 1},
                "del.c": {"hash": "del-hash", "size": 3, "mtime": 1},
            }
        },
        "artifacts": {},
    }
    monkeypatch.setattr(detection, "_load_json", lambda _p: baseline)

    baseline_entries, diffs = detection._collect_scope_diffs(cfg)
    kinds = {d["path"]: d["kind"] for d in diffs}
    assert str(mod) in kinds and kinds[str(mod)] == "modified"
    assert str(added) in kinds and kinds[str(added)] == "added"
    assert str(src / "del.c") in kinds and kinds[str(src / "del.c")] == "deleted"
    assert str(keep) not in kinds
    assert str(src / "keep.c") in baseline_entries


def test_artifact_target_from_jamfile(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    jam = src / "Jamfile"
    jam.write_text("Main billingd : tax_rule.c helper.c ;\n")
    f = src / "tax_rule.c"
    f.write_text("int main(){return 0;}\n")

    cls, name = detection._artifact_target(str(f))
    assert cls == "bin"
    assert name == "billingd"


def test_artifact_target_from_jamfile_with_variables(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    jam = src / "Jamfile"
    jam.write_text("SRCS = tax_rule.c helper.c ;\nLibrary libbilling : $(SRCS) ;\n")
    f = src / "tax_rule.c"
    f.write_text("int x;\n")

    cls, name = detection._artifact_target(str(f))
    assert cls == "lib"
    assert name == "libbilling"


def test_artifact_target_from_install_rule(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    jam = src / "Jamfile"
    jam.write_text("InstallBin $(BINDIR) : tax_rule.c ;\n")
    f = src / "tax_rule.c"
    f.write_text("int y;\n")

    cls, name = detection._artifact_target(str(f))
    assert cls == "bin"
    assert name == "tax_rule"


def test_artifact_target_expands_sources_dot_c_pattern(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    jam = src / "Jamfile"
    jam.write_text(
        "\n".join(
            [
                "SOURCES = cib_main cib_tcp ;",
                "TARGET2 = ibrssnd ;",
                "Main $(TARGET2) : $(SOURCES).c ;",
                "InstallBin $(UASYS_HOME)/bin : $(TARGET2) ;",
            ]
        )
        + "\n"
    )
    f = src / "cib_main.c"
    f.write_text("int z;\n")
    cls, name = detection._artifact_target(str(f))
    assert cls == "bin"
    assert name == "ibrssnd"


def test_artifact_target_expands_concatenated_target_vars(tmp_path):
    src = tmp_path / "libsrc"
    src.mkdir()
    jam = src / "Jamfile"
    jam.write_text(
        "\n".join(
            [
                "LIB_NAME = libcdrdb ;",
                "SUFLIB = .a ;",
                "SRCS = udbc_init cdr_tbl ;",
                "Library $(LIB_NAME)$(SUFLIB) : $(SRCS).c ;",
            ]
        )
        + "\n"
    )
    f = src / "udbc_init.c"
    f.write_text("int a;\n")
    cls, name = detection._artifact_target(str(f))
    assert cls == "lib"
    assert name == "libcdrdb.a"
