#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""폴더 안 파일 이름을 소문자·하이픈 형식(slug)으로 바꾼다.

단일 파일 스크립트 뼈대다. 새 스크립트를 만들 때 복사한 뒤 설명, 인자, 순수 함수, 적용 함수를 바꾼다.
구조: 순수 함수(slugify, plan) → 부작용 함수(apply) → CLI(build_parser, main).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import unicodedata
from pathlib import Path

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

log = logging.getLogger(Path(__file__).stem)


def slugify(name: str) -> str:
    """파일 이름의 확장자를 뺀 부분을 소문자·숫자·하이픈으로 바꾼다.

    >>> slugify("My Report (Final).PDF")
    'my-report-final.pdf'
    """
    stem, dot, suffix = name.rpartition(".")
    if not dot or not stem:
        stem, suffix = name, ""
    text = unicodedata.normalize("NFKC", stem).lower()
    text = re.sub(r"[^\w]+", "-", text).strip("-_")
    text = re.sub(r"-{2,}", "-", text) or "untitled"
    return f"{text}.{suffix.lower()}" if suffix else text


def plan(directory: Path) -> list[dict[str, str]]:
    """바꿀 파일 목록을 만든다. 숨김 파일, 이미 slug 인 파일, 이름이 겹치는 파일은 건너뛴다."""
    changes: list[dict[str, str]] = []
    taken = {p.name for p in directory.iterdir()}
    for path in sorted(
        p for p in directory.iterdir() if p.is_file() and not p.name.startswith(".")
    ):
        target = slugify(path.name)
        if target == path.name:
            continue
        if target in taken:
            log.warning("건너뜀: %s → %s 이미 있음", path.name, target)
            continue
        taken.add(target)
        changes.append({"from": path.name, "to": target})
    return changes


def apply(directory: Path, changes: list[dict[str, str]]) -> None:
    """계획대로 이름을 바꾼다."""
    for change in changes:
        (directory / change["from"]).rename(directory / change["to"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="폴더 안 파일 이름을 소문자·하이픈 형식으로 바꾼다.",
        epilog=(
            "예:\n"
            "  uv run script.py ~/Downloads --dry-run\n"
            "  SLUG_DIR=~/Downloads uv run script.py\n\n"
            '출력: stdout 에 {"dry_run": bool, "changes": [{"from", "to"}]} JSON\n'
            "exit code: 0 성공, 1 이름 바꾸기 실패, 2 사용법 오류"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        default=os.environ.get("SLUG_DIR"),
        help="대상 폴더 (없으면 환경 변수 SLUG_DIR)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="바꾸지 않고 계획만 출력한다"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="진단을 자세히 출력한다"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
        stream=sys.stderr,
    )
    if args.directory is None:
        parser.print_usage(sys.stderr)
        log.error("대상 폴더가 필요하다: 인자로 주거나 SLUG_DIR 를 설정한다")
        return EXIT_USAGE
    directory = Path(args.directory).expanduser()
    if not directory.is_dir():
        log.error("폴더가 아니다: %s", directory)
        return EXIT_USAGE

    changes = plan(directory)
    if not args.dry_run:
        try:
            apply(directory, changes)
        except OSError as exc:
            log.error("이름 바꾸기 실패: %s", exc)
            return EXIT_FAILED
    json.dump(
        {"dry_run": args.dry_run, "changes": changes}, sys.stdout, ensure_ascii=False
    )
    sys.stdout.write("\n")
    log.info("%d개 %s", len(changes), "예정" if args.dry_run else "변경")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
