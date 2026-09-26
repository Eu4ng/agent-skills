"""assets/script.py 의 테스트 뼈대. 순수 함수는 표로, CLI 는 Given/When/Then 으로 검증한다.

실행: uvx pytest test_script.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("script.py")
spec = importlib.util.spec_from_file_location("script", SCRIPT)
assert spec and spec.loader
script = importlib.util.module_from_spec(spec)
sys.modules["script"] = script
spec.loader.exec_module(script)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("My Report (Final).PDF", "my-report-final.pdf"),
        ("already-slug.txt", "already-slug.txt"),
        ("공백 있는 이름.md", "공백-있는-이름.md"),
        ("!!!.txt", "untitled.txt"),
    ],
)
def test_slugify(name: str, expected: str) -> None:
    assert script.slugify(name) == expected


def test_given_mixed_names_when_dry_run_then_nothing_is_renamed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given
    (tmp_path / "A B.txt").write_text("x")
    # When
    code = script.main([str(tmp_path), "--dry-run"])
    # Then
    out = json.loads(capsys.readouterr().out)
    assert code == script.EXIT_OK
    assert out == {"dry_run": True, "changes": [{"from": "A B.txt", "to": "a-b.txt"}]}
    assert (tmp_path / "A B.txt").exists()


def test_given_renamed_folder_when_run_again_then_no_changes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: 한 번 적용한 폴더
    (tmp_path / "A B.txt").write_text("x")
    script.main([str(tmp_path)])
    capsys.readouterr()
    # When: 다시 실행
    code = script.main([str(tmp_path)])
    # Then: 멱등
    assert code == script.EXIT_OK
    assert json.loads(capsys.readouterr().out)["changes"] == []
    assert (tmp_path / "a-b.txt").exists()


def test_given_no_directory_when_run_then_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SLUG_DIR", raising=False)
    assert script.main([]) == script.EXIT_USAGE
