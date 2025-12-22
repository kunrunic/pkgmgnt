# pkgmgr

패키지 관리/배포 워크플로를 위한 Python 패키지입니다. 현재는 스캐폴드 상태이며, CLI와 설정 템플릿, 릴리스 번들링까지 제공됩니다.

## 디자인/Use case
- 흐름 요약과 Mermaid 시퀀스 다이어그램은 `design/mermaid/use-cases.md`에 있습니다(깃헙에서 바로 렌더링됨).
- 주 명령별 설정/동작 요약과 make-config/install/create-pkg/update-pkg/close-pkg 시퀀스를 포함합니다.

## 구성
- `pkgmgr/cli.py` : CLI 엔트리 (아래 명령어 참조)
- `pkgmgr/config.py` : `pkgmgr.yaml` / `pkg.yaml` 템플릿 생성 및 로더 (PyYAML 필요)
- `pkgmgr/snapshot.py`, `pkgmgr/release.py`, `pkgmgr/gitcollect.py`, `pkgmgr/watch.py` : 스냅샷/패키지 수명주기/깃 수집/감시/릴리스 번들
- `pkgmgr/collectors/` : 컬렉터 인터페이스 및 체크섬 컬렉터 스텁
- 템플릿: `pkgmgr/templates/pkgmgr.yaml.sample`, `pkgmgr/templates/pkg.yaml.sample`

## 필요 사항
- Python 3.8 이상
- 의존성(PyYAML 등)은 `pip install pkgmgr-kunrunic` 시 자동 설치됩니다.

## 설치 (PyPI/로컬)
- PyPI(권장): `python -m pip install pkgmgr-kunrunic` (또는 `pipx install pkgmgr-kunrunic`으로 전역 CLI 설치).
- 로컬/개발: 리포지토리 클론 후 `python -m pip install .` 또는 빌드 산출물(`dist/pkgmgr_kunrunic-<버전>-py3-none-any.whl`)을 `python -m pip install dist/<파일>`로 설치.
- 확인: `pkgmgr --version` 혹은 `python -m pkgmgr.cli --version`.

## 기본 사용 흐름 (스캐폴드)
아래 명령은 `pkgmgr ...` 또는 `python -m pkgmgr.cli ...` 형태로 실행합니다.  
설정 파일 기본 위치는 `~/pkgmgr/pkgmgr.yaml`이며, `~/pkgmgr/pkgmgr*.yaml`과 `~/pkgmgr/config/pkgmgr*.yaml`을 자동 탐색합니다(여러 개면 선택 필요, `--config`로 강제 지정 가능). 상태/릴리스 데이터는 `~/pkgmgr/local/state` 아래에 기록됩니다.

### 1) make-config — 메인 설정 템플릿 생성
```
pkgmgr make-config
pkgmgr make-config -o ~/pkgmgr/config/pkgmgr-alt.yaml  # 위치 지정 가능
```
편집할 주요 필드: `pkg_release_root`, `sources`, `source.exclude`, `artifacts.targets/exclude`, `git.keywords/repo_root`, `collectors.enabled`, `actions`.

### 2) install — PATH/alias 등록 + 초기 baseline(한 번만)
```
pkgmgr install [--config <path>]
```
- 사용 쉘을 감지해 rc 파일에 PATH/alias 추가.
- `~/pkgmgr/local/state/baseline.json`이 없을 때만 초기 스냅샷 생성(있으면 건너뜀).

### 3) create-pkg — 패키지 디렉터리/설정 생성
```
pkgmgr create-pkg <pkg-id> [--config <path>]
```
- `<pkg_release_root>/<pkg-id>/pkg.yaml`을 실제 값으로 채워 생성(기존 파일이 있으면 덮어쓰기 여부 확인).
- 메인 설정의 `git.keywords/repo_root`, `collectors.enabled`를 기본값으로 반영.
- baseline이 없는 경우에만 baseline 생성.

### 4) update-pkg — Git/체크섬 수집 + 릴리스 번들 생성
```
pkgmgr update-pkg <pkg-id> [--config <path>]
```
- Git: `git.repo_root`(상대/절대)에서 `git.keywords` 매칭 커밋을 모아 `message/author/subject/files/keywords` 저장.
- 체크섬: 키워드에 걸린 파일 + `include.releases` 경로의 파일 해시 수집.
- 릴리스 번들: `include.releases` 최상위 디렉터리별로 `release/<root>/release.vX.Y.Z/`를 자동 증가 버전으로 생성. 이전 버전과 해시가 동일한 파일은 스킵, 달라진 파일만 복사. 각 버전 폴더에 README.txt(포함/스킵 수, tar 예시, TODO) 작성. tar는 만들지 않음.
- 실행 결과는 `~/pkgmgr/local/state/pkg/<id>/updates/update-<ts>.json`에 기록(`git`, `checksums`, `release` 메타 포함).

### (기타) watch / collect / actions / export / point
기능은 여전히 스텁 혹은 최소 구현 상태입니다. 필요 시 `pkgmgr watch`, `pkgmgr collect`, `pkgmgr actions`, `pkgmgr point`, `pkgmgr export`를 이용할 수 있으며, 추후 강화 예정입니다.

## PATH/alias 자동 추가
- PyPI/로컬 설치 후 `python -m pkgmgr.cli install`을 실행하면 현재 파이썬의 `bin` 경로(예: venv/bin, ~/.local/bin 등)를 감지해 사용 중인 쉘의 rc 파일에 PATH/alias를 추가합니다.
- 지원 쉘: bash(`~/.bashrc`), zsh(`~/.zshrc`), csh/tcsh(`~/.cshrc`/`~/.tcshrc`), fish(`~/.config/fish/config.fish`).
- 추가 내용:
  - PATH: `export PATH="<script_dir>:$PATH"` 또는 쉘별 동등 구문
  - alias: `alias pkg="pkgmgr"` (csh/fish 문법 사용)
- 이미 추가된 경우(marker로 확인) 중복 삽입하지 않습니다. rc 파일이 없으면 새로 만듭니다.

## 템플릿 개요
- `pkgmgr/templates/pkgmgr.yaml.sample` : 메인 설정 샘플  
  - `pkg_release_root`: 패키지 릴리스 루트  
  - `sources`: 관리할 소스 경로 목록  
  - `source.exclude`: 소스 스캔 제외 패턴 (glob 지원)  
  - `artifacts.targets` / `artifacts.exclude`: 배포 대상 포함/제외 규칙 (glob 지원: `tmp/**`, `*.bak`, `**/*.tmp` 등)  
  - `watch.interval_sec`: 감시 폴링 주기  
  - `watch.on_change`: 변경 시 실행할 action 이름 리스트  
  - `collectors.enabled`: 기본 활성 컬렉터
  - `actions`: action 이름 → 실행할 커맨드 목록 (각 항목에 `cmd` 필수, `cwd`/`env` 선택)

- `pkgmgr/templates/pkg.yaml.sample` : 패키지별 설정 샘플  
  - `pkg.id` / `pkg.root` / `pkg.status(open|closed)`  
  - `include.releases`: 릴리스에 포함할 경로(최상위 디렉터리별로 묶여 `release/<root>/release.vX.Y.Z` 생성)  
  - `git.repo_root/keywords/since/until`: 커밋 수집 범위  
  - `collectors.enabled`: 패키지별 컬렉터 설정

## 주의
- 아직 핵심 로직(스냅샷/감시/수집/내보내기)은 스텁입니다. 추후 단계적으로 구현/교체 예정입니다.

## TODO (우선순위)
- 감시/포인트 고도화: watchdog/inotify 연동, diff 결과를 포인트 메타에 기록, 에러/로그 처리.
- baseline/릴리스 알림: baseline 대비 변경 감지 시 알림/확인 흐름 추가(README/README.txt TODO 반영).
- Git 수집: `gitcollect.py` 확장(키워드/정규식 수집, state/pkg/<id>/commits.json 저장).
- 컬렉터 파이프라인: 체크섬 외 collector 등록/선택/실행 로직, include 기준 실행, 정적/동적/EDR/AV 훅 자리 마련.
- Export/산출물: `export` 기본 JSON 덤프, excel/word 후크 설계, 포인트 단위 산출물 묶기.
- 테스트/CI: watch diff/포인트/라이프사이클 단위 테스트 추가, pytest/CI 스크립트 보강.
