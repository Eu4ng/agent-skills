# 명령줄 스크립트 규칙

에이전트와 사람이 같이 부르는 스크립트의 규칙이다. 예시는 `assets/script.py` 에 모두 들어 있다.

## 구조

```python
def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ...
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
```

- `argv` 를 받게 해 두면 테스트에서 `main(["--dry-run", ...])` 로 바로 부를 수 있다.
- 로직은 순수 함수(입력 → 값)와 부작용 함수(파일·네트워크·프로세스)로 나눈다. 순수 함수는 테스트하기 쉽고,
  부작용 함수는 `--dry-run` 으로 건너뛰기 쉽다.
- 모듈을 import 할 때 아무 일도 일어나지 않게 한다. 인자 해석, 로깅 설정, 네트워크 연결은 `main` 안에서 한다.

## 인자와 입력

- `argparse` 를 쓴다. `description`, `epilog`(예시 2개 이상, 출력 형식, exit code), 각 인자의 `help` 를 채운다.
  줄바꿈을 살리려면 `formatter_class=argparse.RawDescriptionHelpFormatter` 를 쓴다.
- 여러 작업을 한 스크립트에 담으면 하위 명령(`add_subparsers`)을 쓴다. 서로 독립적인 여러 작업을 한 번에
  돌리는 플래그 모음이 필요할 때만 플래그 여러 개를 허용한다.
- 선택지가 정해진 값은 `choices=` 로 막는다. 모호한 입력은 추측하지 말고 오류로 돌려준다.
- 기본값을 환경 변수에서 읽을 때는 `default=os.environ.get("NAME")` 처럼 `build_parser` 안에서 읽는다.
- **대화형 입력 금지.** `input()`, `getpass.getpass()` 는 에이전트가 응답할 수 없어 멈춘다. 필요한 값이 없으면
  무엇을 어떻게 넘기면 되는지 stderr 에 쓰고 `EXIT_USAGE` 로 끝낸다.
- **비밀값**: 환경 변수나 파일 경로로 받는다. 인자로 받으면 프로세스 목록과 셸 기록에 남는다. 로그와 예외
  메시지에 값을 넣지 않는다. 여러 경로를 받으면 우선순위는 `--<이름>-file` 인자 → `<이름>_FILE` 환경 변수 →
  `<이름>` 환경 변수 순이고, `--help` 에 적는다.

## 출력

- 결과 데이터는 stdout 에 JSON 하나 또는 JSON Lines(`\n` 으로 구분된 레코드)로 낸다. `ensure_ascii=False` 로
  한글을 그대로 낸다.
- 사람이 읽는 진행 상황, 경고, 오류는 `logging` 으로 stderr 에 낸다. `logging.basicConfig(stream=sys.stderr)`
  (기본값)와 `-v/--verbose` 로 수준을 바꾼다.
- 출력이 커질 수 있으면 요약이나 `--limit` 을 기본으로 하고, 전부 필요하면 `--output <파일>` 로 받게 한다.
- 표 형식 출력이 필요하면 `--format json|table` 로 고르게 하고 기본값은 json 으로 둔다.

## exit code

argparse 는 사용법 오류에 2 를 쓰므로 여기에 맞춘다. `--help` 의 `epilog` 에 적는다.

| 코드 | 뜻 |
| :--- | :--- |
| 0 | 성공(할 일이 없었던 경우 포함) |
| 1 | 실행 실패(외부 명령·네트워크·파일 오류) |
| 2 | 사용법 오류(인자, 입력 누락) |
| 3 이상 | 스크립트 고유 상태(예: 검사 실패, 찾지 못함). 쓰면 반드시 문서화한다 |

## 부작용

- 상태를 바꾸는 스크립트는 `--dry-run` 을 둔다. 읽기만 하는 스크립트에는 두지 않는다. dry-run 과 실제 실행이 **같은 계획 함수**를 거치게 해서,
  dry-run 결과가 실제로 할 일과 어긋나지 않게 한다.
- 멱등으로 만든다: "없으면 만든다", "이미 같으면 건너뛴다". 에이전트는 실패하면 다시 실행한다.
- 지우기처럼 되돌릴 수 없는 작업은 명시적 플래그(`--delete`, `--force`)가 있을 때만 한다.
- 외부 명령:

  ```python
  result = subprocess.run(
      ["kubectl", "get", "pods", "-o", "json"],
      check=True,
      capture_output=True,
      text=True,
      timeout=60,
  )
  ```

  - 인자는 리스트로 넘기고 `shell=True` 는 쓰지 않는다. 셸 해석 때문에 공백과 따옴표가 깨지고, 주입 위험이 생긴다.
  - `CalledProcessError` 와 `TimeoutExpired` 를 잡아 stderr 에 원인을 쓰고 1 로 끝낸다.
- 네트워크: 모든 요청에 timeout 을 준다. 표준 라이브러리 `urllib.request.urlopen(req, timeout=30)` 으로
  충분하면 의존성을 더하지 않는다.
- 파일 쓰기는 임시 파일에 쓴 뒤 `Path.replace()` 로 바꿔 넣어, 중간에 끊겨도 반쯤 쓴 파일이 남지 않게 한다.

## 원격·컨테이너 안에서 실행

- `ssh host 'python3 -' < script.py` 나 `kubectl exec -i ... -- python3 - < script.py` 처럼 stdin 으로 넘기면
  복사 없이 실행된다. 이때 stdin 은 스크립트가 쓰므로 데이터는 환경 변수·인자로 넘긴다. 인자는 `python3 - --flag`
  처럼 `-` 뒤에 붙인다.
- 그 런타임에 있는 파이썬 버전과 패키지만 쓴다. 먼저 `python3 --version` 과 필요한 모듈 import 가 되는지 확인한다.

## 참고

- argparse: https://docs.python.org/3/library/argparse.html
- logging HOWTO: https://docs.python.org/3/howto/logging.html
- subprocess: https://docs.python.org/3/library/subprocess.html
- json: https://docs.python.org/3/library/json.html
- pathlib: https://docs.python.org/3/library/pathlib.html
- `__main__`: https://docs.python.org/3/library/__main__.html
