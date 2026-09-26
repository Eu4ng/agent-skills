#!/usr/bin/env python3
"""새 스킬 폴더를 템플릿으로 만든다. 이미 있으면 건드리지 않는다.

만든 뒤 SKILL.md 의 `TODO(...)` 자리를 모두 채우고, 필요 없는 선택 절(환경 정보, 스크립트)을 지운다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_EXISTS = 3

TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "SKILL.template.md"
NAME_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="새 스킬 폴더(<부모 폴더>/<이름>/SKILL.md)를 템플릿으로 만든다.",
        epilog=(
            "예:\n"
            "  python3 scripts/new_skill.py ~/github/org/agent-skills/skills release-tagging\n"
            "  python3 scripts/new_skill.py <저장소>/.agents/skills deploy-check\n\n"
            "이름: 영어 소문자·숫자·하이픈, 64자 이내. 작업을 나타내는 짧은 이름을 스스로 정한다.\n"
            '출력: {"skill_dir": ..., "skill_md": ..., "todo": 채울 자리 수}\n'
            "exit code: 0 만듦, 2 사용법 오류(잘못된 이름), 3 이미 있음(고치려면 그 파일을 편집한다)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "parent", type=Path, help="스킬 폴더들을 담을 폴더 (예: skills, .agents/skills)"
    )
    parser.add_argument("name", help="스킬 이름 = 폴더 이름")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if len(args.name) > 64 or not NAME_RE.fullmatch(args.name):
        print(
            f"오류: 이름 '{args.name}' 은 영어 소문자·숫자·하이픈만, 64자 이내로 쓴다. 예: release-tagging",
            file=sys.stderr,
        )
        return EXIT_USAGE
    skill_dir = args.parent.expanduser() / args.name
    skill_md = skill_dir / "SKILL.md"
    if skill_md.exists():
        print(
            f"이미 있다: {skill_md}. 새로 만들지 말고 이 파일을 고친다.",
            file=sys.stderr,
        )
        return EXIT_EXISTS
    text = TEMPLATE.read_text(encoding="utf-8").replace("TODO(이름)", args.name, 1)
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md.write_text(text, encoding="utf-8")
    result = {
        "skill_dir": str(skill_dir.resolve()),
        "skill_md": str(skill_md.resolve()),
        "todo": text.count("TODO("),
    }
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
