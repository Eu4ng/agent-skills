"""json_replace.py 테스트. 실행: uvx pytest -q -p no:cacheprovider scripts/test_json_replace.py"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import json_replace as jr


def test_replaces_escaped_query_and_keeps_formatting(tmp_path: Path) -> None:
    doc = {
        "panels": [
            {"targets": [{"rawSql": 'SELECT time AS "time" FROM r WHERE room = $room'}]}
        ]
    }
    path = tmp_path / "d.json"
    original = json.dumps(doc, ensure_ascii=False, indent=4) + "\n"
    path.write_text(original, encoding="utf-8")
    assert (
        jr.main(
            [
                str(path),
                'AS "time" FROM r WHERE room = $room',
                'AS "time" FROM r WHERE room = ${room:sqlstring}',
            ]
        )
        == 0
    )
    text = path.read_text(encoding="utf-8")
    assert json.loads(text)["panels"][0]["targets"][0]["rawSql"].endswith(
        "room = ${room:sqlstring}"
    )
    assert text.count("\n") == original.count("\n")  # 들여쓰기·줄 수 유지


def test_not_found_and_dry_run_leave_file(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    path.write_text('{"q": "a = $a", "t": "방"}', encoding="utf-8")
    assert jr.main([str(path), "nothing", "x"]) == 1
    assert jr.main([str(path), "$a", "${a:sqlstring}", "--dry-run"]) == 0
    assert path.read_text(encoding="utf-8") == '{"q": "a = $a", "t": "방"}'


def test_finds_ascii_escaped_text() -> None:
    source = json.dumps({"t": "방 온도"})  # ensure_ascii 기본값: \uXXXX
    result, count = jr.replace(source, "방 온도", "방 습도")
    assert count == 1 and json.loads(result)["t"] == "방 습도"
