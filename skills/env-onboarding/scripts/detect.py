#!/usr/bin/env python3
"""이 PC 의 작업 환경을 감지해 JSON 으로 낸다. 비밀값(키 내용, 토큰)은 읽지 않는다.

감지 항목: OS·셸·사용자, 설치된 명령, ssh 설정의 Host 항목과 공개 키 이름, 홈 아래 git 저장소와 remote,
기본 게이트웨이와 이 PC 의 LAN 주소, 에이전트 지침·환경 파일 상태. `--probe` 로 준 호스트에는 비대화형 ssh
접속을 시험한다.
"""

from __future__ import annotations

import argparse
import configparser
import getpass
import json
import logging
import os
import platform
import shutil
import socket
import stat
import struct
import subprocess
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 2

TOOLS = (
    "git",
    "gh",
    "ssh",
    "uv",
    "python3",
    "kubectl",
    "helm",
    "node",
    "npx",
    "docker",
    "ansible",
)
SKIP_DIRS = {
    "node_modules",
    "vendor",
    "venv",
    ".venv",
    "__pycache__",
    "site-packages",
    "_site",
    "dist",
    "build",
}
INSTRUCTION_FILES = {
    "agents": "~/.agents/AGENTS.md",
    "claude-code": "~/.claude/CLAUDE.md",
    "codex": "~/.codex/AGENTS.md",
    "gemini": "~/.gemini/GEMINI.md",
}

log = logging.getLogger("detect")


def detect_system() -> dict[str, object]:
    """OS, 셸, 사용자, 파이썬 버전."""
    return {
        "hostname": socket.gethostname(),
        "os": platform.system(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "user": getpass.getuser(),
        "home": str(Path.home()),
        "shell": os.environ.get("SHELL") or os.environ.get("COMSPEC"),
        "python": platform.python_version(),
        "container": detect_container(),
    }


def detect_container() -> str | None:
    """컨테이너 종류(lxc, docker, podman 등). 컨테이너가 아니거나 알 수 없으면 None."""
    marker = Path("/run/systemd/container")
    if marker.is_file():
        return marker.read_text(encoding="utf-8", errors="replace").strip() or None
    if Path("/.dockerenv").exists():
        return "docker"
    if Path("/run/.containerenv").exists():
        return "podman"
    return None


def detect_tools() -> dict[str, str | None]:
    """명령 이름 → 경로(없으면 None)."""
    return {name: shutil.which(name) for name in TOOLS}


def detect_ssh(home: Path) -> dict[str, object]:
    """~/.ssh/config 의 Host 항목과 공개 키 이름·코멘트. 개인 키 내용은 읽지 않는다."""
    ssh_dir = home / ".ssh"
    hosts: list[dict[str, str]] = []
    config = ssh_dir / "config"
    if config.is_file():
        current: dict[str, str] | None = None
        for raw in config.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.replace("=", " ", 1).partition(" ")
            key, value = key.lower(), value.strip()
            if key == "host":
                current = {"host": value}
                hosts.append(current)
            elif current is not None and key in {
                "hostname",
                "user",
                "port",
                "identityfile",
                "proxycommand",
                "proxyjump",
            }:
                current[key] = value
    keys = []
    for pub in sorted(ssh_dir.glob("*.pub")) if ssh_dir.is_dir() else []:
        parts = pub.read_text(encoding="utf-8", errors="replace").split()
        keys.append(
            {
                "file": str(pub),
                "type": parts[0] if parts else None,
                "comment": " ".join(parts[2:]) if len(parts) > 2 else None,
                "private_key_exists": pub.with_suffix("").exists(),
            }
        )
    known_hosts = ssh_dir / "known_hosts"
    return {
        "config_hosts": hosts,
        "public_keys": keys,
        "known_hosts_entries": len(known_hosts.read_text(errors="replace").splitlines())
        if known_hosts.is_file()
        else 0,
    }


def find_repos(
    roots: list[Path], max_depth: int, limit: int
) -> list[dict[str, object]]:
    """roots 아래 git 저장소와 remote URL. .git/config 만 읽고 git 명령은 부르지 않는다."""
    repos: list[dict[str, object]] = []

    def walk(directory: Path, depth: int) -> None:
        if len(repos) >= limit or depth > max_depth:
            return
        git = directory / ".git"
        if git.exists():
            repos.append({"path": str(directory), "remotes": read_remotes(git)})
            return
        try:
            children = sorted(
                p for p in directory.iterdir() if p.is_dir() and not p.is_symlink()
            )
        except OSError:
            return
        for child in children:
            if child.name.startswith(".") or child.name in SKIP_DIRS:
                continue
            walk(child, depth + 1)

    for root in roots:
        if root.is_dir():
            walk(root, 0)
    return repos


def read_remotes(git: Path) -> dict[str, str]:
    """.git/config 의 remote 이름 → URL. 워크트리(.git 파일)는 빈 사전."""
    config_path = git / "config"
    if not config_path.is_file():
        return {}
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        parser.read(config_path, encoding="utf-8")
    except configparser.Error:
        return {}
    remotes = {}
    for section in parser.sections():
        if section.startswith('remote "') and parser.has_option(section, "url"):
            remotes[section[8:-1]] = parser.get(section, "url")
    return remotes


def detect_network() -> dict[str, object]:
    """기본 게이트웨이와 그쪽으로 나가는 로컬 주소. 패킷은 보내지 않는다."""
    gateway = None
    route = Path("/proc/net/route")
    if route.is_file():
        for line in route.read_text().splitlines()[1:]:
            fields = line.split()
            if len(fields) > 2 and fields[1] == "00000000":
                gateway = socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
                break
    elif shutil.which("route"):
        try:
            out = subprocess.run(
                ["route", "-n", "get", "default"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            ).stdout
            gateway = next(
                (ln.split()[-1] for ln in out.splitlines() if "gateway" in ln), None
            )
        except (OSError, subprocess.SubprocessError):
            gateway = None
    local_ip = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(
                (gateway or "192.0.2.1", 9)
            )  # UDP connect 는 경로만 고르고 전송하지 않는다
            local_ip = sock.getsockname()[0]
    except OSError:
        local_ip = None
    return {"default_gateway": gateway, "local_ip": local_ip}


def describe_file(path: Path) -> dict[str, object]:
    """파일 존재, 심볼릭 링크 대상, 권한."""
    info: dict[str, object] = {
        "path": str(path),
        "exists": path.exists(),
        "symlink_to": None,
        "mode": None,
    }
    if path.is_symlink():
        info["symlink_to"] = os.readlink(path)
    if path.exists():
        info["mode"] = oct(stat.S_IMODE(path.stat().st_mode))
        info["lines"] = len(
            path.read_text(encoding="utf-8", errors="replace").splitlines()
        )
    return info


def detect_agent_files(home: Path) -> dict[str, object]:
    """공통 지침, 환경 정보 파일, 도구별 전역 지침 파일 상태."""
    files = {
        name: describe_file(Path(p.replace("~", str(home), 1)))
        for name, p in INSTRUCTION_FILES.items()
    }
    files["environment"] = describe_file(home / ".agents" / "environment.md")
    skills_dir = home / ".agents" / "skills"
    files["user_skills"] = (
        sorted(p.name for p in skills_dir.iterdir() if (p / "SKILL.md").is_file())
        if skills_dir.is_dir()
        else []
    )
    return files


def probe_ssh(targets: list[str], timeout: int) -> list[dict[str, object]]:
    """비대화형 ssh 접속 시험. 비밀번호·호스트 키 확인 창이 뜨는 대상은 실패로 본다."""
    results = []
    for target in targets:
        cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={timeout}",
            target,
            "true",
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout + 5, check=False
            )
            results.append(
                {
                    "target": target,
                    "ok": proc.returncode == 0,
                    "error": proc.stderr.strip()[-300:] or None,
                }
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            results.append({"target": target, "ok": False, "error": str(exc)})
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="이 PC 의 작업 환경을 감지해 JSON 으로 낸다. 비밀값은 읽지 않는다.",
        epilog=(
            "예:\n"
            "  python3 scripts/detect.py\n"
            "  python3 scripts/detect.py --repo-root ~/github --probe user@host1 --probe host2\n"
            "  python3 scripts/detect.py --only ssh,agents\n\n"
            "절: system, tools, ssh, repos, network, agents, probe\n"
            "exit code: 0 성공(접속 실패도 결과에 담는다), 2 사용법 오류"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--repo-root",
        action="append",
        type=Path,
        help="git 저장소를 찾을 폴더(여러 번, 기본 홈)",
    )
    parser.add_argument(
        "--max-depth", type=int, default=4, help="저장소 탐색 깊이 (기본 4)"
    )
    parser.add_argument(
        "--max-repos", type=int, default=100, help="저장소 최대 개수 (기본 100)"
    )
    parser.add_argument(
        "--probe",
        action="append",
        default=[],
        metavar="[USER@]HOST",
        help="ssh 접속을 시험할 대상",
    )
    parser.add_argument(
        "--timeout", type=int, default=5, help="ssh 접속 시험 제한 시간(초, 기본 5)"
    )
    parser.add_argument("--only", help="출력할 절만 쉼표로 (예: ssh,agents)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    sections = {"system", "tools", "ssh", "repos", "network", "agents", "probe"}
    only = {s.strip() for s in args.only.split(",")} if args.only else sections
    if only - sections:
        parser.print_usage(sys.stderr)
        log.error(
            "오류: 알 수 없는 절 %s. 가능: %s",
            sorted(only - sections),
            ", ".join(sorted(sections)),
        )
        return EXIT_USAGE

    home = Path.home()
    result: dict[str, object] = {}
    if "system" in only:
        result["system"] = detect_system()
    if "tools" in only:
        result["tools"] = detect_tools()
    if "ssh" in only:
        result["ssh"] = detect_ssh(home)
    if "repos" in only:
        roots = [p.expanduser() for p in args.repo_root] if args.repo_root else [home]
        result["repos"] = find_repos(roots, args.max_depth, args.max_repos)
    if "network" in only:
        result["network"] = detect_network()
    if "agents" in only:
        result["agents"] = detect_agent_files(home)
    if "probe" in only and args.probe:
        if not shutil.which("ssh"):
            log.warning("ssh 명령이 없어 접속 시험을 건너뛴다")
        else:
            result["probe"] = probe_ssh(args.probe, args.timeout)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
