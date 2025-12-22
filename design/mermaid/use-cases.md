# pkgmgr 흐름 (Mermaid)

## 명령별 설정/동작 요약 (현재 구현 기준)
- make-config: `pkgmgr.yaml` 템플릿 생성 → 편집: `pkg_release_root`, `sources`, `source.exclude`, `artifacts.targets/exclude`, `collectors.enabled`, `actions`, `git.keywords/repo_root`.
- install: `--config` 로딩 → 쉘 PATH/alias 추가 → baseline이 없을 때만 `~/pkgmgr/local/state/baseline.json` 생성.
- create-pkg: `<pkg_release_root>/<pkg-id>/pkg.yaml` 생성(실제 값 채움, 기존 파일 있으면 overwrite 여부 확인) → baseline 없을 때만 생성.
- update-pkg: `git.repo_root`에서 `git.keywords` 매칭 커밋 수집(message/author/files 등) + 키워드 파일/`include.releases` 체크섬 수집 + 릴리스 번들 생성(`release/<root>/release.vX.Y.Z/`, 이전 버전과 diff 후 변경분만 복사, README.txt 작성).
- close-pkg: `<pkg root>/.closed` 마커 생성 + `state.json` status=closed 기록.

## 시퀀스 다이어그램 (주요 명령 흐름)
```mermaid
%%{init: {'theme':'neutral'}}%%
sequenceDiagram
    participant U as User
    participant CLI as pkgmgr CLI
    participant CFG as config.py
    participant REL as release.py
    participant SNAP as snapshot.py

    U->>CLI: make-config [-o <path>]
    CLI->>CFG: write_template()
    CFG-->>U: pkgmgr.yaml 템플릿 작성\n편집: pkg_release_root, sources, exclude, artifacts, collectors, actions

    U->>CLI: install [--config <file>]
    CLI->>CFG: load_main()
    CFG-->>CLI: cfg 로드
    CLI->>REL: ensure_environment()
    CLI->>SNAP: create_baseline(cfg)
    SNAP-->>U: baseline.json 저장(~ /pkmgr/local/state)

    U->>CLI: create-pkg <pkg-id> [--config <file>]
    CLI->>CFG: load_main()
    CFG-->>CLI: cfg 로드
    CLI->>REL: create_pkg(cfg, id)
    REL->>CFG: write_pkg_template(<release_root>/<id>/pkg.yaml)
    note over REL,U: pkg.yaml 필드: pkg.id/root/status,\ninclude.releases,\ngit.repo_root/keywords/since/until,\ncollectors.enabled\n(기존 파일 있으면 overwrite 여부 확인)
    REL->>SNAP: create_baseline(cfg)  %% baseline이 없을 때만

    U-->>CLI: update-pkg <pkg-id> [--config <file>]
    CLI->>CFG: load_main()
    CFG-->>CLI: cfg 로드
    CLI->>REL: update_pkg(cfg, id)
    note over REL: git 키워드 커밋 수집(message/author/files/keywords),\n키워드 파일+include.releases 체크섬,\nrelease/<root>/release.vX.Y.Z 생성(변경분만 복사, README/tar 예시)

    U->>CLI: close-pkg <pkg-id> [--config <file>]
    CLI->>CFG: load_main()
    CLI->>REL: close_pkg(cfg, id)
    REL-->>U: state.json status=closed + <pkg root>/.closed 마커
```
