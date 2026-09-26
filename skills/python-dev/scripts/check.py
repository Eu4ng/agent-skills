#!/usr/bin/env python3
"""파이썬 파일의 검증(포맷·린트·문법·테스트·--help)을 한 번에 돌리고 결과를 JSON 으로 낸다.

검증 명령을 하나씩 부르다 빠뜨리는 일을 막으려고 만들었다. 도구가 없거나 오프라인이면 표준 라이브러리로 할 수 있는
검사로 대신하고, 하지 못한 검사는 skipped 로 알린다. 표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
TAIL = 1500


def run(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    """명령을 실행해 (exit code, 출력 끝부분)을 돌려준다. 명령이 없거나 시간이 넘으면 127/124."""
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError:
        return 127, f"명령이 없다: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"시간 초과({timeout}초): {' '.join(cmd)}"
    return proc.returncode, (proc.stdout + proc.stderr)[-TAIL:]


def is_offline_failure(output: str) -> bool:
    """uvx 가 패키지를 내려받지 못해 실패했는지."""
    markers = (
        "Failed to fetch",
        "failed to lookup address",
        "Could not connect",
        "network",
        "dns error",
    )
    return any(m.lower() in output.lower() for m in markers)


def tool(name: str, args: list[str], cwd: Path, timeout: int) -> dict[str, object]:
    """uvx 로 도구를 돌린다. uvx 가 없거나 내려받지 못하면 설치된 모듈(python3 -m)로 대신한다."""
    if shutil.which("uvx"):
        code, out = run(["uvx", name, *args], cwd, timeout)
        if not (code != 0 and is_offline_failure(out)):
            return {"code": code, "output": out, "via": "uvx"}
    code, out = run([sys.executable, "-m", name, *args], cwd, timeout)
    if code != 0 and "No module named" in out:
        return {
            "code": None,
            "output": f"{name} 없음(오프라인이거나 설치 안 됨)",
            "via": None,
        }
    return {"code": code, "output": out, "via": "python -m"}


def step(name: str, result: dict[str, object]) -> dict[str, object]:
    code = result["code"]
    status = "skipped" if code is None else ("ok" if code == 0 else "failed")
    return {
        "step": name,
        "status": status,
        "via": result.get("via"),
        "output": result["output"],
    }


def has_main(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="replace")
    return "__name__" in text and "__main__" in text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="파이썬 파일의 포맷·린트·문법·테스트·--help 검증을 한 번에 돌린다.",
        epilog=(
            "예:\n"
            "  python3 scripts/check.py count_errors.py test_count_errors.py\n"
            "  python3 scripts/check.py src tests --no-format\n\n"
            "단계: format(ruff format, 파일을 고친다) → lint(ruff check) → compile(py_compile)\n"
            "      → test(pytest, test_*.py 가 있을 때) → help(__main__ 이 있는 파일의 --help)\n"
            '출력: {"ok": bool, "steps": [{"step", "status": ok|failed|skipped, "via", "output"}]}\n'
            "exit code: 0 모든 단계 ok 또는 skipped, 1 실패한 단계 있음, 2 사용법 오류.\n"
            "실패하면 output 을 읽고 고친 뒤 다시 실행한다. 모두 ok 가 되기 전에는 끝났다고 보고하지 않는다."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("paths", nargs="+", type=Path, help="검사할 .py 파일이나 폴더")
    parser.add_argument(
        "--no-format", action="store_true", help="ruff format 으로 파일을 고치지 않는다"
    )
    parser.add_argument(
        "--timeout", type=int, default=300, help="단계별 제한 시간(초, 기본 300)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    missing = [str(p) for p in args.paths if not p.exists()]
    if missing:
        print(f"오류: 없는 경로: {', '.join(missing)}", file=sys.stderr)
        return EXIT_USAGE
    cwd = Path.cwd()
    files = sorted(
        {
            f
            for p in args.paths
            for f in ([p] if p.is_file() else p.rglob("*.py"))
            if "__pycache__" not in f.parts
        }
    )
    targets = [str(p) for p in args.paths]
    steps = []
    if not args.no_format:
        steps.append(
            step("format", tool("ruff", ["format", *targets], cwd, args.timeout))
        )
    steps.append(step("lint", tool("ruff", ["check", *targets], cwd, args.timeout)))
    code, out = run(
        [sys.executable, "-m", "py_compile", *map(str, files)], cwd, args.timeout
    )
    steps.append(step("compile", {"code": code, "output": out, "via": "python -m"}))
    tests = [str(f) for f in files if f.name.startswith("test_")]
    if tests:
        steps.append(
            step(
                "test",
                tool(
                    "pytest",
                    ["-q", "-p", "no:cacheprovider", *tests],
                    cwd,
                    args.timeout,
                ),
            )
        )
    for f in files:
        if not f.name.startswith("test_") and has_main(f):
            code, out = run([sys.executable, str(f), "--help"], cwd, 60)
            steps.append(
                step(f"help:{f.name}", {"code": code, "output": out, "via": "python"})
            )
    ok = all(s["status"] != "failed" for s in steps)
    json.dump({"ok": ok, "steps": steps}, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return EXIT_OK if ok else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
