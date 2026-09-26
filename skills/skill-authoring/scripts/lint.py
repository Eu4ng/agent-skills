#!/usr/bin/env python3
"""Agent Skills 표준과 공용 스킬 작성 규칙으로 스킬 폴더를 검사한다.

오류(errors)는 표준 위반이나 깨진 링크처럼 반드시 고칠 것이고, 경고(warnings)는 규칙상 피해야 하지만 의도했다면
남겨도 되는 것이다. 결과는 stdout 에 JSON 으로 낸다.

파일 첫머리 근처에 `<!-- lint-allow: product, ip -->` 처럼 쓰면 그 파일에서 해당 경고 종류를 끈다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

EXIT_OK = 0
EXIT_ERRORS = 1
EXIT_USAGE = 2

ALLOWED_FIELDS = {
    "name",
    "description",
    "license",
    "allowed-tools",
    "metadata",
    "compatibility",
}
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500
MAX_BODY_LINES = 500
WARNING_KINDS = (
    "product",
    "tool",
    "skill-name",
    "secret",
    "ip",
    "length",
    "depth",
    "allowed-tools",
    "web",
)

PRODUCT_RE = re.compile(
    r"\b(Claude|Anthropic|OpenAI|ChatGPT|GPT-\d|Codex|Gemini|Copilot|Cursor|Opus|Sonnet|Haiku|Llama|Mistral)\b"
)
TOOL_RE = re.compile(
    r"\b(TodoWrite|AskUserQuestion|subagent_type|ExitPlanMode|NotebookEdit)\b"
    r"|\b(Bash|Read|Write|Edit|Grep|Glob|Task|Skill|Agent)\s*(tool|도구)"
)
SECRET_RE = re.compile(
    r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"
)
IP_RE = re.compile(
    r"\b(192\.168|10\.\d{1,3}|172\.(1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"
)
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
ALLOW_RE = re.compile(r"<!--\s*lint-allow:\s*([a-z,\s-]+?)\s*-->")
URL_RE = re.compile(r"https?://[^\s)>\]]+")
LOCAL_URL_RE = re.compile(r"https?://(localhost|127\.|0\.0\.0\.0|\[::1\]|<)")
FENCE_RE = re.compile(r"^(```|~~~)")


def parse_frontmatter(text: str) -> tuple[dict[str, object], str, int]:
    """SKILL.md 를 frontmatter 사전, 본문, 본문 시작 줄 번호로 나눈다.

    표준에 필요한 만큼만 해석한다: 최상위 `키: 값`, 블록 스칼라(`>`, `|`), 한 단계 매핑(metadata).
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md 가 '---' 로 시작하는 frontmatter 로 시작하지 않는다")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise ValueError("frontmatter 를 닫는 '---' 가 없다") from None

    data: dict[str, object] = {}
    key: str | None = None
    block: list[str] | None = None
    mapping: dict[str, str] | None = None
    for raw in lines[1:end]:
        if key and (raw.startswith((" ", "\t")) or not raw.strip()):
            stripped = raw.strip()
            if block is not None:
                block.append(stripped)
            elif mapping is not None and stripped:
                sub_key, _, sub_value = stripped.partition(":")
                mapping[sub_key.strip()] = _unquote(sub_value.strip())
            elif stripped:
                data[key] = f"{data[key]} {stripped}".strip()
            continue
        if key and block is not None:
            data[key] = " ".join(part for part in block if part)
        key, block, mapping = None, None, None
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", raw)
        if not match:
            raise ValueError(f"frontmatter 줄을 해석할 수 없다: {raw!r}")
        key, value = match.group(1), match.group(2).strip()
        if value in {">", "|", ">-", "|-"}:
            block = []
            data[key] = ""
        elif value == "":
            mapping = {}
            data[key] = mapping
        else:
            data[key] = _unquote(value)
    if key and block is not None:
        data[key] = " ".join(part for part in block if part)
    return data, "\n".join(lines[end + 1 :]), end + 2


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def check_frontmatter(data: dict[str, object], skill_dir: Path) -> list[str]:
    """표준 frontmatter 규칙 위반을 오류 문장 목록으로 돌려준다."""
    errors: list[str] = []
    extra = sorted(set(data) - ALLOWED_FIELDS)
    if extra:
        errors.append(
            f"표준에 없는 필드: {', '.join(extra)} (허용: {', '.join(sorted(ALLOWED_FIELDS))})"
        )

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("name 이 없거나 비어 있다")
    else:
        name = unicodedata.normalize("NFKC", name.strip())
        if len(name) > MAX_NAME:
            errors.append(f"name 이 {MAX_NAME}자를 넘는다 ({len(name)}자)")
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name):
            errors.append(
                f"name '{name}' 은 소문자·숫자·하이픈만 쓰고, 하이픈으로 시작·끝나거나 연달아 쓸 수 없다"
            )
        if unicodedata.normalize("NFKC", skill_dir.name) != name:
            errors.append(f"폴더명 '{skill_dir.name}' 이 name '{name}' 과 다르다")

    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append("description 이 없거나 비어 있다")
    elif len(description) > MAX_DESCRIPTION:
        errors.append(
            f"description 이 {MAX_DESCRIPTION}자를 넘는다 ({len(description)}자)"
        )

    compatibility = data.get("compatibility")
    if compatibility is not None and (
        not isinstance(compatibility, str) or len(compatibility) > MAX_COMPATIBILITY
    ):
        errors.append(f"compatibility 는 {MAX_COMPATIBILITY}자 이내 문자열이어야 한다")

    metadata = data.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        errors.append("metadata 는 문자열 키·값 매핑이어야 한다")
    return errors


def prose_lines(text: str) -> list[tuple[int, str, bool]]:
    """(줄 번호, 내용, 코드 블록 안인지) 목록을 돌려준다."""
    result: list[tuple[int, str, bool]] = []
    in_code = False
    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE_RE.match(line.strip()):
            in_code = not in_code
            result.append((number, line, True))
            continue
        result.append((number, line, in_code))
    return result


def lint_file(
    path: Path,
    skill_dir: Path,
    sibling_names: set[str],
    allow: set[str],
    line_offset: int = 0,
    text: str | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """마크다운·스크립트 파일 하나를 검사해 (오류, 경고) 목록을 돌려준다."""
    errors: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    if text is None:
        text = path.read_text(encoding="utf-8")
    head = "\n".join(text.splitlines()[:5])
    file_allow = set(allow)
    for match in ALLOW_RE.finditer(head):
        file_allow.update(
            part.strip() for part in match.group(1).split(",") if part.strip()
        )
    rel = path.relative_to(skill_dir).as_posix()
    is_markdown = path.suffix == ".md"

    def warn(kind: str, line: int, message: str) -> None:
        if kind not in file_allow:
            warnings.append(
                {
                    "file": rel,
                    "line": line + line_offset,
                    "kind": kind,
                    "message": message,
                }
            )

    section = ""
    for number, line, in_code in (
        prose_lines(text)
        if is_markdown
        else [(n, l, True) for n, l in enumerate(text.splitlines(), 1)]
    ):
        if is_markdown and not in_code and line.startswith("## "):
            section = line[3:].strip()
        if SECRET_RE.search(line):
            warn("secret", number, "비밀값처럼 보이는 문자열이 있다")
        if IP_RE.search(line):
            warn("ip", number, f"사설 IP 주소가 있다: {IP_RE.search(line).group(0)}")
        if not is_markdown:
            continue
        if (
            not in_code
            and section != "참고"
            and any(not LOCAL_URL_RE.match(u) for u in URL_RE.findall(line))
        ):
            warn(
                "web",
                number,
                "오프라인에서도 동작해야 한다. 필요한 내용은 로컬 문서로 두고, 웹 링크는 '## 참고' 절로 옮긴다",
            )
        if not in_code:
            for match in PRODUCT_RE.finditer(line):
                warn(
                    "product",
                    number,
                    f"제품·모델명 '{match.group(0)}' 대신 동작이나 일반 명칭으로 쓴다",
                )
            for match in TOOL_RE.finditer(line):
                warn(
                    "tool",
                    number,
                    f"도구 이름 '{match.group(0)}' 대신 동작('파일을 읽는다' 등)으로 쓴다",
                )
            for name in sibling_names:
                if re.search(
                    rf"`{re.escape(name)}`|\b{re.escape(name)}\s*(스킬|skill)", line
                ):
                    warn(
                        "skill-name",
                        number,
                        f"다른 스킬 '{name}' 을 이름으로 부른다. 할 일로 적는다",
                    )
        for match in LINK_RE.finditer(line):
            target = match.group(1).split("#", 1)[0]
            if (
                not target
                or re.match(r"^[a-z][a-z0-9+.-]*:", target)
                or target.startswith("/")
            ):
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                errors.append(
                    {
                        "file": rel,
                        "line": number + line_offset,
                        "message": f"링크 대상이 없다: {target}",
                    }
                )
            elif (
                path.name != "SKILL.md"
                and resolved.is_file()
                and resolved.suffix == ".md"
                and resolved != path.resolve()
                and skill_dir.resolve() in resolved.parents
            ):
                warn(
                    "depth",
                    number,
                    f"참조 파일이 다시 {target} 을 가리킨다. SKILL.md 에서 한 단계로 참조한다",
                )
    return errors, warnings


def lint_skill(skill_dir: Path, allow: set[str]) -> dict[str, object]:
    """스킬 폴더 하나를 검사한 결과 사전을 돌려준다."""
    result: dict[str, object] = {"skill": str(skill_dir), "errors": [], "warnings": []}
    skill_dir = skill_dir.resolve()
    errors: list[dict[str, object]] = result["errors"]  # type: ignore[assignment]
    warnings: list[dict[str, object]] = result["warnings"]  # type: ignore[assignment]
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        errors.append({"file": "SKILL.md", "line": 0, "message": "SKILL.md 가 없다"})
        return result
    text = skill_md.read_text(encoding="utf-8")
    try:
        data, body, body_start = parse_frontmatter(text)
    except ValueError as exc:
        errors.append({"file": "SKILL.md", "line": 1, "message": str(exc)})
        return result

    errors.extend(
        {"file": "SKILL.md", "line": 1, "message": m}
        for m in check_frontmatter(data, skill_dir)
    )
    if "allowed-tools" in data and "allowed-tools" not in allow:
        warnings.append(
            {
                "file": "SKILL.md",
                "line": 1,
                "kind": "allowed-tools",
                "message": "allowed-tools 는 실험 단계이고 도구마다 이름이 달라 쓰지 않는다",
            }
        )
    body_lines = len(body.splitlines())
    if body_lines >= MAX_BODY_LINES and "length" not in allow:
        warnings.append(
            {
                "file": "SKILL.md",
                "line": body_start,
                "kind": "length",
                "message": f"본문이 {body_lines}줄이다. {MAX_BODY_LINES}줄 미만으로 줄이고 references/ 로 옮긴다",
            }
        )

    siblings = {
        p.name
        for p in skill_dir.resolve().parent.iterdir()
        if p.is_dir()
        and p.name != skill_dir.resolve().name
        and (p / "SKILL.md").is_file()
    }
    description = str(data.get("description", ""))
    head_text = "\n".join(text.splitlines()[: body_start - 1])
    for kind, found in (
        ("product", PRODUCT_RE.findall(description)),
        ("secret", SECRET_RE.findall(head_text)),
        ("ip", IP_RE.findall(head_text)),
    ):
        if found and kind not in allow:
            warnings.append(
                {
                    "file": "SKILL.md",
                    "line": 1,
                    "kind": kind,
                    "message": f"frontmatter 에 {kind} 표현이 있다",
                }
            )

    for number, line in enumerate(text.splitlines(), start=1):
        if "TODO(" in re.sub(r"`[^`]*`", "", line):
            errors.append(
                {
                    "file": "SKILL.md",
                    "line": number,
                    "message": "채우지 않은 TODO( 자리가 남아 있다",
                }
            )
    file_errors, file_warnings = lint_file(
        skill_md, skill_dir, siblings, allow, body_start - 1, body
    )
    errors.extend(file_errors)
    warnings.extend(file_warnings)
    for path in sorted(skill_dir.rglob("*")):
        if (
            path == skill_md
            or not path.is_file()
            or any(part.startswith(".") for part in path.relative_to(skill_dir).parts)
        ):
            continue
        if path.suffix not in {
            ".md",
            ".py",
            ".sh",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".txt",
        }:
            continue
        file_errors, file_warnings = lint_file(path, skill_dir, siblings, allow)
        errors.extend(file_errors)
        warnings.extend(file_warnings)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Agent Skills 표준과 공용 스킬 작성 규칙으로 스킬 폴더를 검사한다.",
        epilog=(
            "예:\n"
            "  python3 scripts/lint.py skills/*\n"
            "  python3 scripts/lint.py my-skill --allow product --errors-only\n\n"
            f"경고 종류: {', '.join(WARNING_KINDS)}\n"
            "exit code: 0 오류 없음(경고는 있을 수 있음), 1 오류 있음, 2 사용법 오류"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("skills", nargs="+", type=Path, help="SKILL.md 가 든 스킬 폴더")
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="KIND",
        help="끌 경고 종류(여러 번, 쉼표 구분 가능)",
    )
    parser.add_argument(
        "--errors-only", action="store_true", help="경고를 출력에서 뺀다"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    allow = {
        kind.strip() for item in args.allow for kind in item.split(",") if kind.strip()
    }
    unknown = allow - set(WARNING_KINDS)
    if unknown:
        parser.print_usage(sys.stderr)
        print(
            f"오류: 알 수 없는 경고 종류 {sorted(unknown)}. 가능: {', '.join(WARNING_KINDS)}",
            file=sys.stderr,
        )
        return EXIT_USAGE
    missing = [str(p) for p in args.skills if not p.is_dir()]
    if missing:
        print(f"오류: 폴더가 아니다: {', '.join(missing)}", file=sys.stderr)
        return EXIT_USAGE

    results = [lint_skill(path, allow) for path in args.skills]
    if args.errors_only:
        for item in results:
            item.pop("warnings")
    total_errors = sum(len(item["errors"]) for item in results)  # type: ignore[arg-type]
    total_warnings = sum(len(item.get("warnings", [])) for item in results)  # type: ignore[arg-type]
    json.dump(
        {
            "ok": total_errors == 0,
            "errors": total_errors,
            "warnings": total_warnings,
            "skills": results,
        },
        sys.stdout,
        ensure_ascii=False,
        indent=2,
    )
    sys.stdout.write("\n")
    return EXIT_ERRORS if total_errors else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
