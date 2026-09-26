---
name: python-dev
description: 파이썬(.py) 코드를 새로 쓰거나 고칠 때 쓴다. .py 파일을 만들거나 고치기 전에는 작업이 간단해도 먼저 이 스킬을 켠다. 파이썬 자동화 스크립트, 명령줄 도구, 패키지 프로젝트, pytest 테스트가 해당하고, 사용자가 언어를 말하지 않고 스크립트를 부탁해 파이썬으로 짜기로 했을 때도 쓴다. 공식 문서(PEP 8·257·484·604·621·723, Python Packaging User Guide) 기준의 구조, 비대화형 CLI 규칙, uv 기반 실행·의존성 관리, TDD·BDD·속성 기반 테스트 방법, 검증 명령을 담고 있다. bash 스크립트, YAML·매니페스트, Dockerfile 처럼 파이썬이 아닌 파일 작업에는 쓰지 않는다.
compatibility: python3 가 필요하다. uv 가 있으면 쓰고, 없거나 오프라인이면 표준 라이브러리 방식으로 대신한다.
---

# 파이썬 개발

PEP 과 공식 문서를 기준으로 쓰고, 이미 있는 저장소에서는 그 저장소의 관례가 우선이다. 스크립트는 사람뿐 아니라
에이전트가 다시 부르는 도구다. 그래서 대화형 입력을 받지 않고, 기계가 읽을 수 있게 출력하는 것을 기본으로 한다.
필요한 규칙은 이 스킬의 파일에 모두 있다. 버전에 따라 달라지는 API 는 추측하지 말고 로컬 도움말로 확인한다
(`python3 -m pydoc <모듈>`, `<도구> --help`).

## 빠른 절차 (새 스크립트)

1. 뼈대를 **복사한다**: `cp <이 스킬 폴더>/assets/script.py <작업 폴더>/<이름>.py`
   처음부터 새로 쓰지 않는다. 뼈대에 argparse·`main()`·JSON 출력·exit code 구조가 이미 맞게 들어 있다.
2. 뼈대의 설명, 인자(`build_parser`), 순수 함수, 부작용 함수를 과제에 맞게 바꾼다. 구조와 출력 방식은 그대로 둔다.
3. 테스트는 **별도 파일** `test_<이름>.py` 에 쓴다. `<이 스킬 폴더>/assets/test_script.py` 를 복사해 바꾼다.
   스크립트 안에 테스트를 넣지 않는다.
4. 검증 스크립트를 실행한다: `python3 <이 스킬 폴더>/scripts/check.py <이름>.py test_<이름>.py`
   출력의 `ok` 가 `true` 가 될 때까지 고치고 다시 실행한다. **`ok` 가 `true` 가 되기 전에는 끝났다고 보고하지 않는다.**
   `skipped` 단계가 있으면(도구 없음·오프라인) 보고에 적는다.

기존 코드를 고칠 때는 1~3 대신 그 파일의 구조를 유지하며 고치고, 4는 똑같이 한다.

## 규칙

1. **관례를 읽는다.** `pyproject.toml`, `uv.lock`, 린터 설정, `tests/`, 기존 스크립트의 머리말을 먼저 본다.
   있으면 그 도구·레이아웃·테스트 방식·주석 언어를 따르고, 아래 기본값은 없을 때만 쓴다.
2. **형태를 정한다.**

   | 상황 | 기본 형태 |
   | :--- | :--- |
   | 파일 하나로 끝나는 자동화·CLI | 단일 파일 + PEP 723 인라인 메타데이터, `uv run <파일>` 로 실행 |
   | 모듈이 여럿이거나 재사용·배포할 코드 | `pyproject.toml` + `src/` 레이아웃 + uv + pytest |
   | 컨테이너·파드·원격 서버 안에서 돌릴 스크립트 | 그 런타임의 파이썬과 이미 설치된 패키지만 쓴다. 표준 라이브러리를 우선하고 `python3 - < 파일` 로 넘긴다 |

   의존성은 표준 라이브러리로 충분하면 추가하지 않는다. 프로젝트 구성과 uv 명령은 [references/packaging.md](references/packaging.md).
3. **CLI 규칙.** 이유와 예시는 [references/cli.md](references/cli.md).
   - `argparse` 로 인자를 받고 `--help` 에 설명·예시·exit code 를 적는다.
   - `def main(argv: list[str] | None = None) -> int` 와 `if __name__ == "__main__": sys.exit(main())` 구조로 쓴다.
   - 대화형 입력(`input`, `getpass`)을 쓰지 않는다. 값은 인자·환경 변수·stdin 으로 받고, 없으면 무엇이 필요한지
     stderr 에 쓰고 exit 2 로 끝낸다. 비밀값은 인자로 받지 않는다.
   - **결과 데이터는 stdout 에 JSON 으로** 낸다. 진행·경고·오류는 `logging` 으로 stderr 에 낸다.
   - 상태를 바꾸는 작업에는 `--dry-run` 을 두고, 다시 실행해도 같은 결과가 되게 만든다.
   - 외부 명령은 `subprocess.run([...], check=True, timeout=...)` 로 부르고 `shell=True` 는 쓰지 않는다.
     네트워크 호출에는 timeout 을 준다. 경로는 `pathlib.Path` 로 다룬다.
4. **스타일.** 요점은 [references/style.md](references/style.md).
   - PEP 8 을 따르고 import 는 한 줄에 하나씩 쓴다.
   - 공개 함수에는 docstring 을 단다.
   - 타입 힌트는 `list[str]`, `X | None` 으로 쓴다.
   - 주석과 메시지 언어는 저장소 관례를 따른다.
5. **테스트.** 방법 선택과 패턴은 [references/testing.md](references/testing.md).
   - 입력과 출력이 분명한 로직은 실패하는 테스트부터 쓴다(TDD).
   - 사용자가 말한 동작 요구는 Given/When/Then 테스트로 옮긴다(BDD 방식).
   - 외부 시스템은 `monkeypatch` 나 주입으로 바꿔 테스트한다.

## 검증

`scripts/check.py` 가 아래 명령을 모두 돌리고 없는 도구는 대신할 방법으로 바꾼다. 스크립트를 쓸 수 없을 때만
직접 실행한다. 온라인이고 uv 가 있을 때:

```bash
uvx ruff format <파일>
uvx ruff check <파일>
uvx pytest -q -p no:cacheprovider <테스트 파일>   # 프로젝트면 uv run pytest
python3 <스크립트> --help
python3 <스크립트> <예시 입력>                    # stdout 이 JSON 인지 확인. 상태를 바꾸면 --dry-run
```

오프라인이거나 도구가 없을 때(`uvx` 는 처음 한 번 내려받아야 한다):

```bash
python3 -m py_compile <파일>
python3 -m pytest -q <테스트 파일>      # pytest 가 설치돼 있을 때
python3 <스크립트> --help
```

## 주의

- pytest·ruff 가 없다고 `pip install` 하지 않는다. `uvx pytest`, `uvx ruff` 로 설치 없이 실행한다. uv 도 없고
  오프라인이면 "검증" 절의 대체 명령을 쓰고, 돌리지 못한 검사를 보고한다.
- 컨테이너 안에서 `os.cpu_count()` 는 호스트 전체 코어 수를 준다. 3.13 이상의 `os.process_cpu_count()` 는 CPU
  affinity 는 반영하지만 cgroup CPU 쿼터(`/sys/fs/cgroup/cpu.max`)는 반영하지 않는다. 스레드·프로세스 수는
  인자로 상한을 받거나 쿼터를 직접 읽어 정한다.
- 파일을 새로 쓰면 실행 권한이 없다. 첫 줄에 셔뱅(`#!`)이 있으면 `chmod +x <파일>` 한다. 안 하면 린터가 지적한다.
- 로그를 `print` 로 stdout 에 섞으면 JSON 출력이 깨진다. 진단은 모두 stderr 로 보낸다.
- 큰 캐시·다운로드·가상 환경은 메모리 기반일 수 있는 `/tmp` 대신 `XDG_CACHE_HOME`(기본 `~/.cache`) 아래에 둔다.
- `python3 - < 파일` 로 원격에 넘긴 스크립트는 stdin 을 이미 쓰고 있으므로 데이터를 stdin 으로 받을 수 없다.
  값은 환경 변수나 인자로 넘긴다.
- PEP 723 메타데이터의 `dependencies` 는 `uv run` 같은 지원 도구로 실행할 때만 설치된다. `python3 <파일>` 로 부르면
  무시된다.
- ruff 는 설정이 없을 때의 기본 규칙 세트가 버전마다 다를 수 있다. 설정 파일이 없는 곳에서는 나온 지적을 따르되,
  결과를 고정해야 하는 프로젝트에는 `[tool.ruff]` 설정을 둔다.
- 검증하면 `__pycache__`, `.pytest_cache`, `.ruff_cache` 가 생긴다. 저장소에서는 `.gitignore` 로 막고, 결과물만
  넘기는 폴더에서는 지운다.

## 스크립트

- `scripts/check.py`: 포맷·린트·문법·테스트·`--help` 검증을 한 번에 돌리고 JSON 으로 낸다. 표준 라이브러리만 쓴다. `--help` 참고.

## 하지 않는 것

- 비밀값을 인자, 로그, 출력 파일, 예외 메시지에 남기지 않는다.
- 시스템 파이썬에 `pip install` 하지 않는다. uv 의 프로젝트·스크립트 환경이나 가상 환경을 쓴다.
- 요청받지 않은 대규모 리팩터링이나 도구 교체(린터, 패키지 관리자)를 하지 않는다.

## 참고

온라인일 때 더 자세히 볼 원문이다. 위 규칙과 references/ 만으로 작업할 수 있어야 한다.

- Python 문서: https://docs.python.org/3/
- PEP 8, 257, 484, 604, 621, 723: https://peps.python.org/
- Python Packaging User Guide: https://packaging.python.org/
