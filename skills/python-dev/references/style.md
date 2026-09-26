# 스타일 요점 (PEP 8·257·484·604)

오프라인에서도 볼 수 있게 자주 쓰는 규칙만 옮겼다. 포매터(`ruff format`)가 맞춰 주는 공백·줄바꿈은 적지 않았다.

## 이름 (PEP 8)

| 대상 | 형식 | 예 |
| :--- | :--- | :--- |
| 모듈·패키지 | 소문자, 필요하면 `_` | `ha_registry.py`, `wiki_papers` |
| 함수·변수·인자 | `snake_case` | `count_errors`, `max_depth` |
| 클래스·예외 | `CapWords`, 예외는 `Error` 로 끝냄 | `Client`, `ConfigError` |
| 상수 | `UPPER_SNAKE` | `EXIT_USAGE`, `MAX_TOOL_OUTPUT` |
| 내부용 | 앞에 `_` 하나 | `_unquote` |

- 명령줄로 부르는 스크립트 파일 이름은 하이픈을 써도 되지만, import 할 모듈은 `_` 를 쓴다.

## import (PEP 8)

- 한 줄에 하나씩 쓴다: `import os` 다음 줄에 `import sys`. `from x import a, b` 는 괜찮다.
- 순서: 표준 라이브러리 → 서드파티 → 로컬. 묶음 사이는 빈 줄로 나눈다.
- `from x import *` 는 쓰지 않는다.
- 파일 맨 위 docstring 과 `from __future__ import ...` 다음에 둔다.

## 비교와 관용구 (PEP 8)

- `None` 비교는 `is None`, `is not None` 으로 한다.
- 빈 시퀀스 검사는 `if not items:` 로 한다. `len(items) == 0` 은 쓰지 않는다.
- 타입 검사는 `isinstance(x, T)` 로 한다. `type(x) == T` 는 쓰지 않는다.
- 예외는 구체적으로 잡는다. 맨 `except:` 와 `except Exception:` 로 삼키지 않는다. 다시 던질 때는 `raise ... from exc`.
- 파일·연결은 `with` 로 연다. 텍스트 파일은 `encoding="utf-8"` 을 명시한다.
- 문자열 조립은 f-string 을 쓴다. 로깅은 `log.info("%s 개", n)` 처럼 인자로 넘긴다.

## docstring (PEP 257)

- 큰따옴표 세 개로 쓴다. 첫 줄은 한 문장 요약으로 쓰고 마침표로 끝낸다.
- 더 쓸 게 있으면 빈 줄 하나 뒤에 이어 쓴다. 인자·반환값·예외 중 이름만으로 드러나지 않는 것을 설명한다.
- 모듈 docstring 에는 이 파일의 용도를 쓴다. 사용법의 원본은 `--help` 다.

```python
def slugify(name: str) -> str:
    """파일 이름의 확장자를 뺀 부분을 소문자·숫자·하이픈으로 바꾼다.

    확장자는 소문자로만 바꾼다. 빈 결과는 "untitled" 가 된다.
    """
```

## 타입 힌트 (PEP 484·585·604)

- 공개 함수의 인자와 반환값에 단다.
- 내장 제네릭을 쓴다: `list[str]`, `dict[str, int]`, `tuple[int, ...]`. `typing.List` 는 쓰지 않는다.
- 선택 값은 `str | None` 으로 쓴다. `Optional[str]` 은 쓰지 않는다.
- 3.9 이하를 지원해야 하면 파일 맨 위에 `from __future__ import annotations` 를 둔다.
- 호출 가능한 것과 이터러블은 `collections.abc` 에서 가져온다: `from collections.abc import Callable, Iterator`.

## 로컬에서 확인하기

인터넷 없이 표준 라이브러리 문서를 본다.

```bash
python3 -m pydoc argparse            # 모듈 문서
python3 -m pydoc subprocess.run      # 함수 하나
python3 -m pydoc -k timeout          # 키워드로 찾기
python3 -c "import os; help(os.process_cpu_count)"
python3 --version                    # 대상 런타임 버전 확인
```

## 참고

- PEP 8: https://peps.python.org/pep-0008/
- PEP 257: https://peps.python.org/pep-0257/
- PEP 484: https://peps.python.org/pep-0484/
- PEP 604: https://peps.python.org/pep-0604/
