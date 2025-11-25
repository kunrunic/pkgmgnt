# pkgmgr

패키지 관리/배포 워크플로를 위한 Python 패키지입니다. 현재는 스캐폴드 상태이며, CLI와 설정 템플릿이 준비돼 있습니다.

## 구성
- `pkgmgr/cli.py` : CLI 엔트리 (아래 명령어 참조)
- `pkgmgr/config.py` : `pkgmgr.yaml` / `pkg.yaml` 템플릿 생성 및 로더 (PyYAML 필요)
- `pkgmgr/snapshot.py`, `pkgmgr/release.py`, `pkgmgr/gitcollect.py`, `pkgmgr/watch.py` : 스냅샷/패키지 수명주기/깃 수집/감시 스텁
- `pkgmgr/collectors/` : 컬렉터 인터페이스 및 체크섬 컬렉터 스텁
- 템플릿: `templates/pkgmgr.yaml.sample`, `templates/pkg.yaml.sample`

## 필요 사항
- Python 2.6 이상 또는 3.x
- Python 2.6에서는 `pip install argparse` 필요 (표준에 없음)
- PyYAML (`pip install "pyyaml<6"` for Python 2.6) — 설정 파싱 시 필요

## 기본 사용 흐름 (스캐폴드)
아래 명령은 `python -m pkgmgr.cli ...` 형태로 실행합니다.

1) 메인 설정 템플릿 생성  
```
python -m pkgmgr.cli make-config -o pkgmgr.yaml
```
`pkgmgr.yaml`에서 소스 경로, 설치 타깃(bin/lib/data 등), release 루트, Git 키워드, 감시 주기, 기본 컬렉터 목록 등을 편집합니다.

2) 환경 준비  
```
python -m pkgmgr.cli install
```
(현재는 자리표시자; 추후 의존성/경로 체크를 수행)

3) 초기 스냅샷 생성  
```
python -m pkgmgr.cli init-snap --config pkgmgr.yaml
```
설정된 소스/설치/릴리스 루트를 기준으로 베이스라인을 기록하도록 확장 예정입니다.

4) 패키지 생성  
```
python -m pkgmgr.cli create-pkg <pkg-id> --config pkgmgr.yaml
```
`<release_root>/<pkg-id>/pkg.yaml` 템플릿을 만들고, 초기 스냅샷/메타데이터를 붙이는 방향으로 확장됩니다.

5) 패키지 종료  
```
python -m pkgmgr.cli close-pkg <pkg-id> --config pkgmgr.yaml
```
감시 대상에서 제외하고 상태를 closed로 표시하는 용도로 사용합니다.

6) 감시(폴링)  
```
python -m pkgmgr.cli watch --config pkgmgr.yaml
python -m pkgmgr.cli watch --config pkgmgr.yaml --once  # 한 번만 폴링
```
설정된 interval로 변경을 감시하는 로직을 연결할 예정입니다.

7) 수집(컬렉터)  
```
python -m pkgmgr.cli collect --pkg <pkg-id> --config pkgmgr.yaml
python -m pkgmgr.cli collect --pkg <pkg-id> --collector checksums --config pkgmgr.yaml
```
체크섬/정적/동적/EDR/백신 등 컬렉터를 플러그인 형태로 추가할 수 있도록 확장 예정입니다.

8) 내보내기  
```
python -m pkgmgr.cli export --pkg <pkg-id> --format excel --config pkgmgr.yaml
```
엑셀/워드/JSON 등의 산출물을 생성하는 후크를 붙일 계획입니다.

## 설치·PATH/alias 자동 추가
- `python -m pip install .` 후 `python -m pkgmgr.cli install`을 실행하면 현재 파이썬의 `bin` 경로(예: venv/bin, ~/.local/bin 등)를 감지해 사용 중인 쉘의 rc 파일에 PATH/alias를 추가합니다.
- 지원 쉘: bash(`~/.bashrc`), zsh(`~/.zshrc`), csh/tcsh(`~/.cshrc`/`~/.tcshrc`), fish(`~/.config/fish/config.fish`).
- 추가 내용:
  - PATH: `export PATH="<script_dir>:$PATH"` 또는 쉘별 동등 구문
  - alias: `alias pkg="pkgmgr"` (csh/fish 문법 사용)
- 이미 추가된 경우(marker로 확인) 중복 삽입하지 않습니다. rc 파일이 없으면 새로 만듭니다.

## 템플릿 개요
- `templates/pkgmgr.yaml.sample` : 메인 설정 샘플  
  - `version`: 스키마 버전  
  - `pkg_release_root`: 패키지 릴리스 루트  
  - `sources`: 관리할 소스 경로 목록  
  - `install.targets` / `install.exclude`: 설치 영역 포함/제외 규칙  
  - `watch.interval_sec`: 감시 폴링 주기  
  - `git.keywords`: 커밋 수집 키워드/정규식  
  - `collectors.enabled`: 기본 활성 컬렉터

- `templates/pkg.yaml.sample` : 패키지별 설정 샘플  
  - `pkg.id` / `pkg.root` / `pkg.status(open|closed)`  
  - `include.sources/install/pkg_dir`: 포함 대상  
  - `git.keywords/since/until`: 커밋 수집 범위  
  - `collectors.enabled`: 패키지별 컬렉터 설정

## 주의
- 아직 핵심 로직(스냅샷/감시/수집/내보내기)은 스텁입니다. 추후 단계적으로 구현/교체 예정입니다.

## TODO (우선순위)
- 스냅샷/디프 구현: `pkgmgr/snapshot.py`에 해시/mtime/size 스캔, baseline/latest 저장(`state/...`), diff 작성. CLI `init-snap`/`watch` 연결.
- 설정 스키마 검증: `pkgmgr/config.py` 필수 필드 확인, 기본값 주입, PyYAML 체크, 템플릿 필드 설명 보강.
- 패키지 라이프사이클: `release.py`에서 `create-pkg` 시 `pkg.yaml` 초기화, `close-pkg` 상태 저장, 상태 파일 표준화.
- Git 수집: `gitcollect.py`에 키워드/정규식 로그 수집, `state/pkg/<id>/commits.json` 저장, `collect_for_pkg`에서 호출.
- 컬렉터 파이프라인: 체크섬 collector를 include 목록 기반 실행, collector 등록/선택 로직 추가, 정적/동적/EDR/AV 훅 자리 마련.
- 감시 루프: `watch.py` 폴링 tick 구현(스냅샷→디프→state), pkg status(open/closed) 고려, interval 적용.
- Export 인터페이스: `release.py`의 `export_pkg`에서 기본 JSON 덤프, excel/word는 외부 후크 설계.
- 문서/샘플: README와 `templates/*.sample`를 최신 스키마에 맞춰 보강.
