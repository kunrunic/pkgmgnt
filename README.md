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
설정 파일은 기본적으로 `~/pkmgr/pkgmgr.yaml`에 생성/저장되며, `~/pkmgr/` 또는 `~/pkmgr/config/` 아래의 `pkgmgr*.yaml`을 자동 탐색합니다. 하나만 있으면 자동 사용, 여러 개면 선택을 요구합니다(`--config`로 미리 지정 가능).

1) 메인 설정 템플릿 생성  
```
python -m pkgmgr.cli make-config 
python -m pkgmgr.cli make-config -o ~/pkmgr/config/pkgmgr-alt.yaml  # 필요 시 추가/분리용
```
`pkgmgr.yaml`에서 소스 경로, 설치 타깃(bin/lib/data 등), release 루트, Git 키워드, 감시 주기, 기본 컬렉터 목록 등을 편집합니다. 기본 생성 위치는 `~/pkmgr/pkgmgr.yaml`이며, `-o --output`로 추가/분리된 설정을 만들 수 있습니다(자동 탐색 대상). 상태/캐시 데이터는 추후 `~/pkmgr/local/state`, `~/pkmgr/cache`에 둘 예정입니다.

2) 환경 준비 + 초기 베이스라인 수집  
```
python -m pkgmgr.cli install              # config 자동 선택(1개) 또는 프롬프트
python -m pkgmgr.cli install --config <path>
```
- 셸 PATH/alias 자동 등록 후, 선택된 설정을 읽어 초기 베이스라인 스냅샷을 저장 (`~/pkmgr/local/state/baseline.json`).
- 추후 의존성/경로 체크 추가 예정.

3) 포인트(Checkpoint) 생성  
```
python -m pkgmgr.cli point --pkg <pkg-id> --label "after-static-scan"
# 복수 설정 시: --config <path>
```
`pkg.yaml`에 정의된 include 기준으로 스냅샷을 찍고, 실행한 액션 목록(`--actions-run` 반복 지정 가능)을 메타와 함께 저장합니다. 저장 위치:  
- `~/pkmgr/local/state/pkg/<id>/points/<timestamp>/meta.json` (label, actions, 생성시각 등)  
- `~/pkmgr/local/state/pkg/<id>/points/<timestamp>/snapshot.json`  
이후 감시는 “마지막 포인트 이후 변경” 기준으로 삼으면 됩니다(현재는 스텁 로그).

4) 스냅샷(수동) 갱신  
```
python -m pkgmgr.cli snapshot
# 복수 설정 시: python -m pkgmgr.cli snapshot --config <path>
```
설정된 소스/아티팩트/릴리스 루트를 기준으로 최신 스냅샷을 저장합니다 (`~/pkmgr/local/state/snapshot.json`). 이후 diff/감시에 사용할 예정입니다.

5) 패키지 생성  
```
python -m pkgmgr.cli create-pkg <pkg-id>
# 복수 설정 시: --config <path>
```
`<release_root>/<pkg-id>/pkg.yaml` 템플릿을 만들고, 초기 스냅샷/메타데이터를 붙이는 방향으로 확장됩니다.

6) 패키지 종료  
```
python -m pkgmgr.cli close-pkg <pkg-id>
# 복수 설정 시: --config <path>
```
감시 대상에서 제외하고 상태를 closed로 표시하는 용도로 사용합니다.
`~/pkmgr/local/state/pkg/<id>/state.json`에 open/closed 상태가 기록되며, closed인 패키지는 watch/collect에서 자동으로 건너뜁니다.

7) 감시(폴링)  
```
python -m pkgmgr.cli watch
python -m pkgmgr.cli watch --once  # 한 번만 폴링
python -m pkgmgr.cli watch --pkg <pkg-id> --auto-point --point-label "after-scan"
# 복수 설정 시: --config <path>
```
`watch`는 이전 포인트(없으면 baseline) 대비 스냅샷을 찍고 diff가 있으면 `watch.on_change` 액션을 실행합니다. `--auto-point` 사용 시 실행 결과를 포함해 새 포인트를 생성합니다. (감시 로직은 여전히 단순 폴링 스텁이며, include 규칙/포인트 스냅샷을 기준으로 동작하도록 확장 예정)

8) 수집(컬렉터)  
```
python -m pkgmgr.cli collect --pkg <pkg-id>
python -m pkgmgr.cli collect --pkg <pkg-id> --collector checksums
# 복수 설정 시: --config <path>
```
체크섬/정적/동적/EDR/백신 등 컬렉터를 플러그인 형태로 추가할 수 있도록 확장 예정입니다. (현재는 스텁 로그만 출력)

9) 내보내기  
```
python -m pkgmgr.cli export --pkg <pkg-id> --format excel
# 복수 설정 시: --config <path>
```
엑셀/워드/JSON 등의 산출물을 생성하는 후크를 붙일 계획입니다. (현재는 스텁 로그만 출력)

10) 액션 실행  
```
python -m pkgmgr.cli actions <action-name> [<action-name> ...]
# 복수 설정 시: --config <path>
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
- 감시/포인트 고도화: watchdog/inotify 연동, 에러/로그 처리, watch diff 결과를 포인트 메타에 더 풍부하게 남기기.
- 설정/템플릿 보강: 필드 설명 확장, 샘플 템플릿을 최신 스키마/기본값에 맞춰 업데이트, 설정 검증 오류 메시지 친절화.
- 패키지 상태 활용: open/closed 상태를 리스트/리포트에 노출하고, closed 패키지 무시 외에 필터링 옵션 추가.
- Git 수집: `gitcollect.py`에 키워드/정규식 로그 수집, `state/pkg/<id>/commits.json` 저장, 포인트와 연계.
- 컬렉터 파이프라인: 체크섬 포함 collector 등록/선택/실행 로직, include 기준 실행, 정적/동적/EDR/AV 훅 자리 마련.
- Export/산출물: `export` 기본 JSON 덤프 구현, excel/word 후크 설계, 포인트 단위 산출물 묶기.
- 테스트/CI: watch diff/포인트/라이프사이클 단위 테스트 추가, pytest 의존성 포함, CI 스크립트 추가.
- 문서/샘플: README와 `templates/*.sample`를 최신 스키마/포인트 흐름에 맞게 보강.
