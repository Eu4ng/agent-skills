#!/usr/bin/env python3
"""에이전트 세션 기록(JSONL)에서 사람이 입력한 메시지만 뽑는다.

도구 호출 결과, 시스템이 끼워 넣은 문장(`<...>` 태그로 시작), 스킬 본문 주입 같은 메타 메시지는 뺀다.
여러 도구의 형식을 휴리스틱으로 읽는다: `{"type": "user", "message": {...}}` 형태,
`{"type": "response_item", "payload": {"type": "message", "role": "user", ...}}` 형태,
그리고 최상위 `{"role": "user", "content": ...}` 형태. 결과는 한 줄에 JSON 하나씩 stdout 으로 낸다.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections.abc import Iterator
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 2

CORRECTION_RE = re.compile(
    r"^(아니|아냐|그게 아니|그 의미가 아니)|이미 |잖아|했어야|말고|왜 .*(안|없|있)|틀렸|다시 해"
    r"|\bno[,.!]|\bactually\b|\binstead\b|\bshould have\b|\bwrong\b|\bwhy did\b",
    re.IGNORECASE,
)
INJECTED_PREFIXES = (
    "<",
    "[Request interrupted",
    "Base directory for this skill",
    "Caveat:",
)

log = logging.getLogger("user_messages")


def texts_of(content: object) -> list[str]:
    """메시지 content 에서 사람이 쓴 텍스트 조각만 모은다. 도구 결과는 뺀다."""
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") in {
            "text",
            "input_text",
            "output_text",
        }:
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return parts


def normalize(obj: dict[str, object]) -> tuple[str, list[str], str] | None:
    """JSONL 한 줄을 (역할, 텍스트 목록, 시각)으로 바꾼다. 메시지가 아니거나 메타 메시지면 None."""
    if obj.get("isMeta") or obj.get("isSidechain"):
        return None
    time = str(obj.get("timestamp", ""))
    message = obj.get("message")
    if obj.get("type") in {"user", "assistant"} and isinstance(message, dict):
        return (
            str(message.get("role", obj["type"])),
            texts_of(message.get("content")),
            time,
        )
    payload = obj.get("payload")
    if (
        obj.get("type") == "response_item"
        and isinstance(payload, dict)
        and payload.get("type") == "message"
    ):
        return (
            str(payload.get("role", "")),
            texts_of(payload.get("content")),
            time or str(payload.get("timestamp", "")),
        )
    if isinstance(obj.get("role"), str) and "content" in obj:
        return str(obj["role"]), texts_of(obj.get("content")), time
    return None


def iter_messages(path: Path, context: bool) -> Iterator[dict[str, object]]:
    """파일 하나에서 사용자 메시지를 순서대로 낸다."""
    last_assistant = ""
    with path.open(encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, start=1):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                log.debug("%s:%d JSON 이 아니다", path, number)
                continue
            if not isinstance(obj, dict):
                continue
            normalized = normalize(obj)
            if normalized is None:
                continue
            role, parts, time = normalized
            text = "\n".join(p for p in parts if p.strip()).strip()
            if not text:
                continue
            if role == "assistant":
                last_assistant = text
                continue
            if role != "user" or text.startswith(INJECTED_PREFIXES):
                continue
            record: dict[str, object] = {
                "file": str(path),
                "line": number,
                "time": time,
                "text": text,
            }
            if context:
                record["before"] = last_assistant[:300]
            yield record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="에이전트 세션 기록(JSONL)에서 사람이 입력한 메시지만 뽑아 JSON Lines 로 낸다.",
        epilog=(
            "예:\n"
            "  python3 scripts/user_messages.py ~/.claude/projects/<폴더>/*.jsonl --corrections\n"
            "  python3 scripts/user_messages.py sessions/*.jsonl --grep '토큰|secret' --context 1 --limit 50\n\n"
            "출력: 한 줄에 {file, line, time, text[, before]}\n"
            "exit code: 0 성공, 2 사용법 오류(파일 없음, 잘못된 정규식)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("files", nargs="+", type=Path, help="JSONL 세션 기록 파일")
    parser.add_argument(
        "--corrections", action="store_true", help="교정 신호가 있는 메시지만 남긴다"
    )
    parser.add_argument(
        "--grep",
        metavar="REGEX",
        help="이 정규식에 맞는 메시지만 남긴다(대소문자 무시)",
    )
    parser.add_argument(
        "--context",
        type=int,
        choices=[0, 1],
        default=0,
        help="1 이면 직전 에이전트 응답 앞부분을 붙인다",
    )
    parser.add_argument(
        "--min-length", type=int, default=2, help="이보다 짧은 메시지는 뺀다 (기본 2)"
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=600,
        help="메시지를 이 길이로 자른다 (기본 600)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="최대 출력 개수 (기본 200, 0 이면 제한 없음)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="진단을 stderr 에 자세히 낸다"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        stream=sys.stderr,
    )
    missing = [str(p) for p in args.files if not p.is_file()]
    if missing:
        log.error("오류: 파일이 없다: %s", ", ".join(missing))
        return EXIT_USAGE
    try:
        pattern = re.compile(args.grep, re.IGNORECASE) if args.grep else None
    except re.error as exc:
        log.error("오류: --grep 정규식이 잘못됐다: %s", exc)
        return EXIT_USAGE

    count = 0
    for path in args.files:
        for record in iter_messages(path, bool(args.context)):
            text = str(record["text"])
            if len(text) < args.min_length:
                continue
            if args.corrections and not CORRECTION_RE.search(text):
                continue
            if pattern and not pattern.search(text):
                continue
            record["text"] = text[: args.max_chars]
            sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
            if args.limit and count >= args.limit:
                log.info("--limit %d 에 도달해 멈췄다", args.limit)
                return EXIT_OK
    log.info("메시지 %d개", count)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
