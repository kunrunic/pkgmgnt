# pkgmgr

패키지 관리/배포 워크플로를 위한 Python 패키지입니다. 현재는 스캐폴드 상태이며, CLI와 설정 템플릿이 준비돼 있습니다.

## 구성
- `pkgmgr/cli.py` : CLI 엔트리 (아래 명령어 참조)
- `pkgmgr/config.py` : `pkgmgr.yaml` / `pkg.yaml` 템플릿 생성 및 로더 (PyYAML 필요)
- `pkgmgr/snapshot.py`, `pkgmgr/release.py`, `pkgmgr/gitcollect.py`, `pkgmgr/watch.py` : 스냅샷/패키지 수명주기/깃 수집/감시 스텁
- `pkgmgr/collectors/` : 컬렉터 인터페이스 및 체크섬 컬렉터 스텁
- 템플릿: `pkgmgr/templates/pkgmgr.yaml.sample`, `pkgmgr/templates/pkg.yaml.sample`

## 필요 사항
- Python 3.8 이상
- PyYAML 6.x (의존성에 포함되어 일반 설치 시 자동 설치)

## 기본 사용 흐름 (스캐폴드)
아래 명령은 `python -m pkgmgr.cli ...` 형태로 실행합니다.  
설정 파일 기본 경로는 `~/pkmgr/config/pkgmgr.yaml`이며, `--config`로 다른 경로를 지정할 수 있습니다.

1) 메인 설정 템플릿 생성  
```
python -m pkgmgr.cli make-config -o pkgmgr.yaml
```
`pkgmgr.yaml`에서 소스 경로, 설치 타깃(bin/lib/data 등), release 루트, Git 키워드, 감시 주기, 기본 컬렉터 목록 등을 편집합니다. 기본 생성 위치는 `~/pkmgr/config/pkgmgr.yaml`이며, `--config`로 다른 경로를 지정할 수 있습니다. 상태/캐시 데이터는 추후 `~/pkmgr/local/state`, `~/pkmgr/cache`에 둘 예정입니다.

2) 환경 준비 + 초기 베이스라인 수집  
```
python -m pkgmgr.cli install
```
- 셸 PATH/alias 자동 등록 후, 기본 설정(`~/pkmgr/config/pkgmgr.yaml`)을 읽어 초기 베이스라인 스냅샷을 저장 (`~/pkmgr/local/state/baseline.json`).
- 추후 의존성/경로 체크 추가 예정.

3) 스냅샷 갱신  
```
python -m pkgmgr.cli snapshot --config pkgmgr.yaml
```
설정된 소스/아티팩트/릴리스 루트를 기준으로 최신 스냅샷을 저장합니다 (`~/pkmgr/local/state/snapshot.json`). 이후 diff/감시에 사용할 예정입니다.

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
설정된 interval로 변경을 감시하는 로직을 연결할 예정입니다. (현재는 스텁 로그만 출력)

7) 수집(컬렉터)  
```
python -m pkgmgr.cli collect --pkg <pkg-id> --config pkgmgr.yaml
python -m pkgmgr.cli collect --pkg <pkg-id> --collector checksums --config pkgmgr.yaml
```
체크섬/정적/동적/EDR/백신 등 컬렉터를 플러그인 형태로 추가할 수 있도록 확장 예정입니다. (현재는 스텁 로그만 출력)

8) 내보내기  
```
python -m pkgmgr.cli export --pkg <pkg-id> --format excel --config pkgmgr.yaml
```
엑셀/워드/JSON 등의 산출물을 생성하는 후크를 붙일 계획입니다. (현재는 스텁 로그만 출력)

9) 액션 실행  
```
python -m pkgmgr.cli actions <action-name> [<action-name> ...] --config pkgmgr.yaml
```
`actions` 설정에 등록된 커맨드를 순서대로 실행합니다(`cmd` 필수, `cwd`/`env` 선택). (실제 실행 로직은 포함되어 있음)

## 설치·PATH/alias 자동 추가
- `python -m pip install .` 후 `python -m pkgmgr.cli install`을 실행하면 현재 파이썬의 `bin` 경로(예: venv/bin, ~/.local/bin 등)를 감지해 사용 중인 쉘의 rc 파일에 PATH/alias를 추가합니다.
- 지원 쉘: bash(`~/.bashrc`), zsh(`~/.zshrc`), csh/tcsh(`~/.cshrc`/`~/.tcshrc`), fish(`~/.config/fish/config.fish`).
- 추가 내용:
  - PATH: `export PATH="<script_dir>:$PATH"` 또는 쉘별 동등 구문
  - alias: `alias pkg="pkgmgr"` (csh/fish 문법 사용)
- 이미 추가된 경우(marker로 확인) 중복 삽입하지 않습니다. rc 파일이 없으면 새로 만듭니다.

## 배포(초도 PyPI 업로드) 체크리스트
- 메타데이터: `pyproject.toml`에서 이름/설명/라이선스/클래시파이어를 관리합니다. 버전은 `pkgmgr/__init__.py`의 `__version__`에서 읽습니다(PEP 440 형식).
- 빌드 준비: `python -m pip install --upgrade build twine`.
- 빌드: `python -m build` → `dist/`에 sdist+wheel 생성.
- 검증: `twine check dist/*` 후 `python -m pip install dist/pkgmgr-<버전>-py3-none-any.whl` 로컬 설치 테스트.
- 업로드: `TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-*** twine upload dist/*`.
- 업로드 전 README/라이선스/템플릿이 최신인지 확인하고, 필요시 rc 업데이트 안내를 유지합니다.

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
  - `include.sources/artifacts/pkg_dir`: 포함 대상  
  - `git.keywords/since/until`: 커밋 수집 범위  
  - `collectors.enabled`: 패키지별 컬렉터 설정

## 주의
- 아직 핵심 로직(스냅샷/감시/수집/내보내기)은 스텁입니다. 추후 단계적으로 구현/교체 예정입니다.

## TODO (우선순위)
- 스냅샷/디프 구현: `pkgmgr/snapshot.py`에 해시/mtime/size 스캔, baseline/latest 저장(`state/...`), diff 작성. CLI `snapshot`/`watch` 연결.
- 설정 스키마 검증: `pkgmgr/config.py` 필수 필드 확인, 기본값 주입, PyYAML 체크, 템플릿 필드 설명 보강.
- 패키지 라이프사이클: `release.py`에서 `create-pkg` 시 `pkg.yaml` 초기화, `close-pkg` 상태 저장, 상태 파일 표준화.
- Git 수집: `gitcollect.py`에 키워드/정규식 로그 수집, `state/pkg/<id>/commits.json` 저장, `collect_for_pkg`에서 호출.
- 컬렉터 파이프라인: 체크섬 collector를 include 목록 기반 실행, collector 등록/선택 로직 추가, 정적/동적/EDR/AV 훅 자리 마련.
- 감시 루프: `watch.py` 폴링 tick 구현(스냅샷→디프→state), pkg status(open/closed) 고려, interval 적용.
- Export 인터페이스: `release.py`의 `export_pkg`에서 기본 JSON 덤프, excel/word는 외부 후크 설계.
- 문서/샘플: README와 `templates/*.sample`를 최신 스키마에 맞춰 보강.
