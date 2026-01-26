# PyPI 배포 절차 (예시: pkgmgr_kunrunic)

## 사전 준비
- Python 3.8+ 환경, 가상환경 권장: `python3 -m venv .venv && source .venv/bin/activate`
- 툴 설치: `python -m pip install --upgrade pip build twine`
- 프로젝트 이름은 PyPI 전역에서 유일해야 함 (`[project].name` 확인)
- 버전은 매 업로드마다 증가(PEP 440). `pkgmgr/__init__.py`의 `__version__` 수정 후 진행
- (선택) `.pypirc` 설정: 계정/프로젝트 토큰을 구분해 두면 `--repository`로 선택 업로드 가능

`.pypirc` 예시 (프로젝트 토큰 사용):
```
[distutils]
index-servers =
    pkgmgr_kunrunic

[pkgmgr_kunrunic]
repository = https://upload.pypi.org/legacy/
username = __token__
password = pypi-<프로젝트 토큰>
```

## 빌드/검증/업로드
```
rm -rf dist
python -m build
twine check dist/*
twine upload --repository pkgmgr_kunrunic dist/pkgmgr_kunrunic-*
```
- `--repository`는 `.pypirc` 섹션 이름. `.pypirc` 없이 환경변수를 써도 됨:
  - `TWINE_USERNAME=__token__`
  - `TWINE_PASSWORD=pypi-<프로젝트 토큰>`
  - `TWINE_REPOSITORY_URL=https://upload.pypi.org/legacy/` (생략 시 기본)
- TestPyPI 사용 시: test.pypi.org에서 토큰 발급 → `--repository-url https://test.pypi.org/legacy/`

## 설치/동작 테스트 (권장)
```
python -m pip install --force-reinstall dist/pkgmgr_kunrunic-<버전>-py3-none-any.whl
python -m pkgmgr.cli --help
pkgmgr --help  # console_script 확인
```
필요하면 sdist 설치도 확인: `python -m pip install --force-reinstall dist/pkgmgr_kunrunic-<버전>.tar.gz`

## update-pkg 옵션 예시
```
pkgmgr update-pkg TEST --release
```
실행 시 active root가 여러 개면 아래처럼 확인을 요청:
```
[release] active roots: SYS_1, SYS_2. Proceed finalize all? [y/N]:
[release] skipped; use --root to finalize a single root
```

단일 root만 release:
```
pkgmgr update-pkg TEST --release --root SYS_2
```

cancel + root 지정:
```
pkgmgr update-pkg TEST --cancel v0.0.1 --root SYS_2
```

cancel (history 정리/BASELINE 복원 포함):
```
pkgmgr update-pkg TEST --cancel v0.0.1 --root SYS_2 --cancel-clean-history
```

## 업로드 실패 시 대처
- 403 (권한 없음): 이름이 선점됨 → `[project].name`을 고유하게 변경 후 다시 빌드/업로드
- 400 File already exists: 같은 버전의 파일이 이미 올라감 → `__version__`을 올리고 dist를 새로 빌드
- PEP 668 externally-managed: 전역 pip 설치 차단 → venv 사용 또는 pipx로 설치

## 배포 후 점검
- `pip install pkgmgr_kunrunic`로 설치 확인, `python -m pkgmgr.cli --help` 실행
- README/메타데이터가 최신인지 PyPI 페이지에서 확인

## 새 패키지를 만들 때
- 새 이름을 먼저 정하고 `[project].name` 반영
- 내부 import 패키지명이 다르면 디렉터리/네임스페이스도 맞게 준비
- 위 빌드/업로드 절차는 동일. 첫 업로드 후 프로젝트 스코프 토큰을 새로 만들어 두고 계정 토큰은 회수 권장
