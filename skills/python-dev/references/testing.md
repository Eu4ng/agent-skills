# 테스트

## 방법 고르기

| 상황 | 방법 |
| :--- | :--- |
| 입력과 기대 출력이 분명한 로직(파서, 변환, 이름 규칙, 계산, 스키마 매핑) | **TDD**: 테스트부터 |
| 사용자가 말로 준 동작 요구("이미 있으면 건너뛴다", "이름이 규칙에 안 맞으면 기록하지 않는다") | **BDD 방식**: Given/When/Then 테스트 |
| 입력 공간이 넓고 성질로 말할 수 있는 로직(왕복 변환, 정렬, 정규화) | **속성 기반**: Hypothesis |
| 외부 시스템에 붙는 코드 | 경계에서 주입·모의 + 실제 환경에서 `--dry-run` |
| 일회성 조사 스크립트 | 테스트 생략 가능. 대신 `--help`·`--dry-run` 실행으로 확인 |

## TDD

1. **Red**: 원하는 동작 하나를 테스트로 쓰고, 실행해서 **실패하는 것을 확인**한다. 처음부터 통과하면 테스트가
   아무것도 검사하지 않는 것이다.
2. **Green**: 테스트를 통과하는 가장 단순한 코드를 쓴다.
3. **Refactor**: 테스트가 통과하는 상태를 유지하면서 중복과 이름을 정리한다.
4. 다음 동작으로 넘어간다. 버그를 고칠 때도 그 버그를 재현하는 테스트부터 쓴다.

## BDD 방식

대부분은 pytest 테스트의 이름과 본문 구조만으로 충분하다.

```python
def test_given_existing_target_when_renaming_then_skips_and_warns(tmp_path, caplog):
    # Given
    (tmp_path / "a b.txt").write_text("x")
    (tmp_path / "a-b.txt").write_text("y")
    # When
    changes = plan(tmp_path)
    # Then
    assert changes == []
    assert "이미 있음" in caplog.text
```

사용자가 비개발자와 공유할 명세 문서를 원하거나 이미 `.feature` 파일이 있을 때만 Gherkin 과 pytest-bdd 를 쓴다.

## pytest 패턴

- **표로 여러 경우**: `@pytest.mark.parametrize(("입력", "기대"), [...])`. 경계값(빈 값, 최댓값, 유니코드)을 넣는다.
- **파일**: `tmp_path` 고정구로 임시 폴더를 쓴다. 실제 홈이나 저장소 파일을 건드리지 않는다.
- **환경 변수·함수 바꾸기**: `monkeypatch.setenv`, `monkeypatch.delenv`, `monkeypatch.setattr(module, "fn", fake)`.
- **출력 확인**: `capsys.readouterr().out` 을 `json.loads` 해서 비교한다. 로그는 `caplog`.
- **예외**: `with pytest.raises(ValueError, match="..."):`
- **외부 명령**: `subprocess.run` 을 부르는 함수를 인자로 받게 하거나(`runner=subprocess.run`), `monkeypatch.setattr`
  로 가짜를 넣어 넘어간 인자 리스트를 검사한다.
- **네트워크**: 요청 함수를 주입하거나 `unittest.mock.patch` 로 바꾼다. 테스트가 실제 네트워크에 의존하지 않게 한다.
- **공통 준비**: 여러 테스트가 쓰는 준비는 `conftest.py` 의 fixture 로 옮긴다.
- **단일 파일 스크립트 테스트**: 같은 폴더의 `test_<스크립트>.py` 에서 `importlib.util.spec_from_file_location` 으로
  불러온다(`assets/test_script.py` 참고). 파일 이름에 하이픈이 있어도 불러올 수 있다.
- **doctest**: 짧은 순수 함수의 사용 예는 docstring 에 `>>>` 로 쓰고 `python3 -m doctest <파일>` 로 확인한다.

## 속성 기반 (Hypothesis)

```python
from hypothesis import given, strategies as st


@given(st.text())
def test_slugify_is_idempotent(name):
    once = slugify(name)
    assert slugify(once) == once
```

- 왕복(`decode(encode(x)) == x`), 멱등(`f(f(x)) == f(x)`), 불변식(길이, 정렬, 허용 문자)을 성질로 쓴다.
- 찾은 실패 사례는 `@example(...)` 이나 parametrize 에 고정해 회귀 테스트로 남긴다.
- 의존성이 늘어나므로 성질로 말할 수 있는 핵심 로직에만 쓴다.

## 프로젝트 설정

`pyproject.toml`:

```toml
[dependency-groups]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = ["--import-mode=importlib"]
```

실행은 `uv run pytest`, 특정 테스트만 돌릴 때는 `uv run pytest tests/test_x.py -k 이름 -x` 를 쓴다.

## 참고

- pytest 문서: Good Integration Practices, fixtures, parametrize, monkeypatch: https://docs.pytest.org/en/stable/
- unittest.mock: https://docs.python.org/3/library/unittest.mock.html
- doctest: https://docs.python.org/3/library/doctest.html
- Hypothesis: https://hypothesis.readthedocs.io/
- pytest-bdd: https://pytest-bdd.readthedocs.io/
