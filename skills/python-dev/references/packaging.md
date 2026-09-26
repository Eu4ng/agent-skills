# 프로젝트 구성과 실행

## 단일 파일 스크립트

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "httpx>=0.27",
# ]
# ///
```

| 할 일 | 명령 |
| :--- | :--- |
| 새 스크립트 | `uv init --script tool.py --python 3.12` |
| 의존성 추가 | `uv add --script tool.py 'httpx>=0.27'` |
| 실행 | `uv run tool.py ...`, 또는 실행 권한을 주고 `./tool.py ...` |
| 잠금(재현성이 중요할 때) | `uv lock --script tool.py` |

- 메타데이터 블록은 `# /// script` 와 `# ///` 사이의 TOML 이다. `uv run` 처럼 이를 읽는 도구로 실행할 때만
  의존성이 설치된다.
- 셔뱅을 쓰면 `chmod +x` 한다(린터가 실행 권한 없는 셔뱅을 경고한다).

## 프로젝트

```
<프로젝트>/
├── pyproject.toml
├── uv.lock
├── src/<패키지>/__init__.py
├── src/<패키지>/cli.py
└── tests/test_<모듈>.py
```

- `uv init --package <이름>` 으로 만든다. 배포하지 않는 앱이라도 `src/` 레이아웃을 쓰면, 테스트가 설치된
  패키지를 import 하게 되어 "로컬 폴더라서 우연히 되는" 문제를 막는다.
- 명령줄 진입점은 `[project.scripts]` 에 둔다: `tool = "<패키지>.cli:main"`. 실행은 `uv run tool ...` 이다.
- 모듈 실행이 필요하면 `src/<패키지>/__main__.py` 를 두고 `uv run python -m <패키지>` 로 부른다.

```toml
[project]
name = "tool"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["httpx>=0.27"]

[project.scripts]
tool = "tool.cli:main"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

| 할 일 | 명령 |
| :--- | :--- |
| 의존성 추가·제거 | `uv add <패키지>`, `uv remove <패키지>` |
| 개발 의존성 | `uv add --dev pytest` (`[dependency-groups] dev`) |
| 환경 맞추기 | `uv sync` (잠금 파일 기준) |
| 실행 | `uv run <명령>` (필요하면 자동으로 sync) |
| 잠금 갱신 | `uv lock`, 특정 패키지만 `uv lock --upgrade-package <패키지>` |

- `uv.lock` 은 커밋한다.
- `requires-python` 은 실제로 실행할 런타임 중 가장 낮은 버전에 맞춘다. 올리면 그 런타임에서 설치가 거부된다.
- 버전 범위는 하한만 두는 것이 기본이다(`>=`). 상한은 알려진 비호환이 있을 때만 둔다.

## 린트·포맷

- 설정이 없으면 기본값으로 `uvx ruff format` 과 `uvx ruff check` 를 쓴다. 자동 수정은 `uvx ruff check --fix` 이다.
- 규칙을 넓히고 싶으면 프로젝트에 `[tool.ruff.lint] select = ["E", "F", "I", "UP", "B", "SIM"]` 정도를 둔다.
  이미 있는 설정은 바꾸지 않는다.
- 타입 검사는 저장소에 이미 설정이 있을 때만 돌린다.

## uv 가 없을 때

- 단일 스크립트: 표준 라이브러리만 쓰고 `python3 tool.py` 로 실행한다.
- 프로젝트:
  - 가상 환경을 만든다: `python3 -m venv .venv`
  - 설치한다: `.venv/bin/pip install -e . pytest`
  - 테스트한다: `.venv/bin/python -m pytest`
- 시스템 파이썬에 전역 설치하지 않는다. 배포판 파이썬은 PEP 668 로 막혀 있기도 하다.

## 참고

- Python Packaging User Guide: Writing your pyproject.toml, src layout vs flat layout, Inline script metadata: https://packaging.python.org/
- PEP 621: https://peps.python.org/pep-0621/
- PEP 723: https://peps.python.org/pep-0723/
- PEP 735: https://peps.python.org/pep-0735/
- uv 문서: https://docs.astral.sh/uv/
- Ruff 문서: https://docs.astral.sh/ruff/
