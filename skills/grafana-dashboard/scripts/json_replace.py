#!/usr/bin/env python3
"""JSON 파일 안의 문자열 값에서 한 문자열을 다른 문자열로 바꾼다. 원문 서식(들여쓰기·키 순서)은 그대로 둔다.

대시보드 JSON 의 쿼리처럼 따옴표·역슬래시가 이스케이프된 값을 sed 로 고치면 틀리기 쉽다. 이 스크립트는 바꿀 문자열을
JSON 과 같은 방식으로 이스케이프해 원문에서 찾고, 바꾼 뒤 JSON 이 여전히 올바른지 확인하고 저장한다. 예:
  python3 json_replace.py dashboards/home.json 'room = $room' 'room = ${room:sqlstring}'
출력: {"file", "replaced": <바꾼 개수>}. exit code: 0 바꿈, 1 찾지 못함, 2 사용법·JSON 오류.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_NOT_FOUND = 1
EXIT_USAGE = 2


def encode(text: str) -> str:
    """JSON 문자열 값 안에 들어갈 때의 모양(양쪽 따옴표 제외)."""
    return json.dumps(text, ensure_ascii=False)[1:-1]


def replace(source: str, old: str, new: str) -> tuple[str, int]:
    """원문에서 old 를 new 로 바꾼 결과와 바꾼 개수. ensure_ascii 로 저장된 파일(\\uXXXX)도 찾는다."""
    for enc_old, enc_new in (
        (encode(old), encode(new)),
        (json.dumps(old)[1:-1], json.dumps(new)[1:-1]),
    ):
        count = source.count(enc_old)
        if count:
            return source.replace(enc_old, enc_new), count
    return source, 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="JSON 파일의 문자열 값에서 문자열을 바꾼다(서식 유지).",
        epilog=__doc__.split("예:", 1)[1] if __doc__ else None,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("file", type=Path)
    parser.add_argument(
        "old", help="바꿀 문자열(파일에 보이는 이스케이프 없이, 값 그대로)"
    )
    parser.add_argument("new", help="새 문자열")
    parser.add_argument(
        "--dry-run", action="store_true", help="바꿀 개수만 보고 저장하지 않는다"
    )
    args = parser.parse_args(argv)
    try:
        source = args.file.read_text(encoding="utf-8")
        json.loads(source)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"오류: JSON 파일을 읽을 수 없다: {exc}", file=sys.stderr)
        return EXIT_USAGE
    result, count = replace(source, args.old, args.new)
    try:
        json.loads(result)
    except json.JSONDecodeError as exc:
        print(f"오류: 바꾸면 JSON 이 깨진다: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if count and not args.dry_run:
        args.file.write_text(result, encoding="utf-8")
    print(
        json.dumps(
            {"file": str(args.file), "replaced": count, "dry_run": args.dry_run},
            ensure_ascii=False,
        )
    )
    if not count:
        print(
            "찾지 못했다. 검사 결과의 raw_sql 에 보이는 문자열 그대로 넘긴다.",
            file=sys.stderr,
        )
    return EXIT_OK if count else EXIT_NOT_FOUND


if __name__ == "__main__":
    sys.exit(main())
