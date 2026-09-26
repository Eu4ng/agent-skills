#!/usr/bin/env python3
"""저사양 로컬 모델로 스킬을 점검한다. 성능이 낮은 모델에서도 동작하는 스킬이 잘 쓴 스킬이다.

두 가지 점검을 한다.
- trigger: 스킬 목록(이름·설명)과 요청을 주고, 먼저 읽을 스킬을 고르게 한다. 설명이 발동 조건을 잘 전하는지 본다.
- run: 파일 읽기·쓰기·명령 실행 도구를 주고 실제 과제를 맡긴다. 스킬을 찾아 읽고 절차를 따르는지 본다.

모델 서버는 Ollama 기본 API(`--api ollama`) 또는 OpenAI 호환 API(`--api openai`)로 부른다. 표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows: 잠금 없이 기록한다
    fcntl = None  # type: ignore[assignment]

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_CHECKS_FAILED = 3

MAX_TOOL_OUTPUT = 12000
ASK_RE = re.compile(
    r"\?\s*$|\?\n|알려\s?주세요|알려\s?주시|주시겠어요|말씀해\s?주세요", re.MULTILINE
)
log = logging.getLogger("local_eval")


def sandbox_env(home: Path, skills_dir: Path | None = None) -> dict[str, str]:
    """명령 실행 환경. 홈만 바꾸고, 도구 캐시는 실제 캐시를 써서 매번 내려받지 않게 한다."""
    real_cache = os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
    env = {**os.environ, "HOME": str(home), "XDG_CACHE_HOME": real_cache}
    env.setdefault("UV_CACHE_DIR", str(Path(real_cache) / "uv"))
    if skills_dir is not None:
        env["EVAL_SKILLS_DIR"] = str(skills_dir)
    return env


# ---------------------------------------------------------------- 스킬 목록


def read_skill(skill_dir: Path) -> dict[str, str]:
    """SKILL.md frontmatter 의 name·description 과 위치."""
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise ValueError(f"{skill_dir}/SKILL.md 에 frontmatter 가 없다")
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith((" ", "\t")):
            fields[key.strip()] = value.strip().strip("'\"")
    return {
        "name": fields.get("name", skill_dir.name),
        "description": fields.get("description", ""),
        "location": str((skill_dir / "SKILL.md").resolve()),
    }


def catalog_text(skills: list[dict[str, str]]) -> str:
    return "\n".join(
        f"- {s['name']}: {s['description']}\n  위치: {s['location']}" for s in skills
    )


# ---------------------------------------------------------------- 모델 호출


class Client:
    """Ollama 기본 API 와 OpenAI 호환 API 의 채팅 호출을 같은 모양으로 감싼다."""

    def __init__(
        self,
        api: str,
        base_url: str,
        model: str,
        num_ctx: int,
        think: bool,
        timeout: int,
    ) -> None:
        self.api, self.base_url, self.model = api, base_url.rstrip("/"), model
        self.num_ctx, self.think, self.timeout = num_ctx, think, timeout
        self.usage = Counter()

    def chat(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        """메시지를 보내고 {"content", "tool_calls": [{"id", "name", "arguments"}]} 를 돌려준다."""
        if self.api == "ollama":
            body: dict[str, object] = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "think": self.think,
                "options": {"num_ctx": self.num_ctx, "temperature": 0.2},
            }
            url = f"{self.base_url}/api/chat"
        else:
            body = {"model": self.model, "messages": messages, "temperature": 0.2}
            url = f"{self.base_url}/v1/chat/completions"
        if tools:
            body["tools"] = tools
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        if key := os.environ.get("LOCAL_LLM_API_KEY"):
            request.add_header("Authorization", f"Bearer {key}")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.load(response)
        if self.api == "ollama":
            message = data.get("message", {})
            self.usage["prompt_tokens"] += data.get("prompt_eval_count", 0)
            self.usage["completion_tokens"] += data.get("eval_count", 0)
            calls = [
                {
                    "id": str(i),
                    "name": c["function"]["name"],
                    "arguments": _as_dict(c["function"].get("arguments")),
                }
                for i, c in enumerate(message.get("tool_calls") or [])
            ]
        else:
            message = data["choices"][0]["message"]
            for key in ("prompt_tokens", "completion_tokens"):
                self.usage[key] += data.get("usage", {}).get(key, 0)
            calls = [
                {
                    "id": c.get("id", str(i)),
                    "name": c["function"]["name"],
                    "arguments": _as_dict(c["function"].get("arguments")),
                }
                for i, c in enumerate(message.get("tool_calls") or [])
            ]
        return {
            "content": message.get("content") or "",
            "tool_calls": calls,
            "raw": message,
        }

    def tool_result(self, call: dict[str, object], content: str) -> dict[str, object]:
        if self.api == "ollama":
            return {"role": "tool", "tool_name": call["name"], "content": content}
        return {"role": "tool", "tool_call_id": call["id"], "content": content}

    def assistant_message(self, reply: dict[str, object]) -> dict[str, object]:
        raw = dict(reply["raw"])  # type: ignore[arg-type]
        raw.setdefault("role", "assistant")
        return raw


def _as_dict(arguments: object) -> dict[str, object]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            value = json.loads(arguments)
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


# ---------------------------------------------------------------- trigger


TRIGGER_PROMPT = """너는 사용자의 컴퓨터에서 일하는 에이전트다. 아래는 설치된 스킬 목록이다.
요청을 처리하기 전에 먼저 읽어야 할 스킬이 있으면 그 이름을, 없으면 none 을 고른다.
스킬은 요청이 그 설명에 맞을 때만 고른다. 반드시 JSON 한 줄로만 답한다: {{"skill": "<이름 또는 none>"}}

스킬 목록:
{catalog}"""


def run_trigger(
    client: Client,
    skills: list[dict[str, str]],
    queries: list[dict[str, object]],
    runs: int,
) -> dict:
    system = TRIGGER_PROMPT.format(catalog=catalog_text(skills))
    names = {s["name"] for s in skills}
    results = []
    for item in queries:
        raw = item.get("expect")
        # 두 스킬이 모두 맞는 요청이면 목록으로 준다. 그중 하나를 고르면 맞다
        accepted = (
            [str(x) for x in raw] if isinstance(raw, list) else [str(raw or "none")]
        )
        expected = " | ".join(accepted)
        picks = []
        for _ in range(runs):
            reply = client.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": str(item["query"])},
                ]
            )
            match = re.search(r'"skill"\s*:\s*"([^"]+)"', str(reply["content"]))
            pick = match.group(1).strip() if match else "invalid"
            picks.append(
                pick
                if pick in names or pick in {"none", "invalid"}
                else f"unknown:{pick}"
            )
        hit = sum(p in accepted for p in picks) / runs
        results.append(
            {
                "query": item["query"],
                "expect": expected,
                "picks": picks,
                "rate": hit,
                "pass": hit > 0.5,
                "source": item.get("_source"),
            }
        )
        log.info(
            "%s %s ← %s",
            "PASS" if hit > 0.5 else "FAIL",
            picks,
            str(item["query"])[:60],
        )
    passed = sum(r["pass"] for r in results)
    return {
        "mode": "trigger",
        "passed": passed,
        "total": len(results),
        "results": results,
    }


# ---------------------------------------------------------------- run


RUN_PROMPT = """너는 사용자의 컴퓨터에서 일하는 코딩 에이전트다. 도구로 파일을 읽고 쓰고 명령을 실행하며 작업을 끝까지 수행한다.
작업 폴더: {workdir}
홈 폴더(~): {home}

{skills_block}

사용자에게 물어야 할 것이 있으면 ask_user 로 한 번에 묻는다. 작업이 끝나면 한 일을 짧게 보고한다."""


# Agent Skills 클라이언트 구현 안내의 권장 문구를 옮긴 것이다.
SKILLS_BY_FILE = """아래 스킬은 특정 작업을 위한 지시를 담고 있다. 작업이 스킬 설명에 맞으면 진행하기 전에 적힌 위치의
SKILL.md 를 read_file 로 읽는다. 스킬 안의 상대 경로는 그 스킬 폴더(SKILL.md 가 있는 폴더) 기준으로 풀어 절대 경로로 쓴다.
{catalog}"""
SKILLS_BY_TOOL = """아래 스킬은 특정 작업을 위한 지시를 담고 있다. 작업이 스킬 설명에 맞으면 activate_skill 도구를
스킬 이름으로 불러 전체 지시를 읽는다.
{catalog}"""


def tool_specs(
    allow_commands: bool, skill_names: list[str] | None = None
) -> list[dict[str, object]]:
    def spec(
        name: str, description: str, properties: dict[str, object], required: list[str]
    ) -> dict:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    specs = [
        spec(
            "read_file", "파일 내용을 읽는다.", {"path": {"type": "string"}}, ["path"]
        ),
        spec(
            "list_dir",
            "폴더의 파일 목록을 본다.",
            {"path": {"type": "string"}},
            ["path"],
        ),
        spec(
            "write_file",
            "파일을 만들거나 덮어쓴다. 작업 폴더와 홈 폴더 안에만 쓸 수 있다.",
            {"path": {"type": "string"}, "content": {"type": "string"}},
            ["path", "content"],
        ),
        spec(
            "ask_user",
            "사용자에게 질문한다. 질문은 한 번에 모아서 한다.",
            {"questions": {"type": "string"}},
            ["questions"],
        ),
    ]
    if skill_names:
        specs.append(
            spec(
                "activate_skill",
                "스킬의 전체 지시를 불러온다.",
                {"name": {"type": "string", "enum": skill_names}},
                ["name"],
            )
        )
    if allow_commands:
        specs.append(
            spec(
                "run_command",
                "작업 폴더에서 셸 명령을 실행하고 출력과 exit code 를 돌려준다.",
                {"command": {"type": "string"}},
                ["command"],
            )
        )
    return specs


class Sandbox:
    """도구 실행기. 쓰기는 작업 폴더와 홈 폴더 안으로 제한한다."""

    def __init__(
        self,
        workdir: Path,
        home: Path,
        allow_commands: bool,
        command_timeout: int,
        skills: list[dict[str, str]] | None = None,
    ) -> None:
        self.workdir, self.home = workdir.resolve(), home.resolve()
        self.skills = {s["name"]: Path(s["location"]).parent for s in skills or []}
        self.activated: list[str] = []
        self.allow_commands, self.command_timeout = allow_commands, command_timeout
        self.read_paths: list[str] = []
        self.commands: list[dict[str, object]] = []
        self.asked: list[str] = []

    def resolve(self, raw: str) -> Path:
        text = raw.strip()
        if text.startswith("~"):
            text = str(self.home) + text[1:]
        path = Path(text)
        return (path if path.is_absolute() else self.workdir / path).resolve()

    def call(self, name: str, args: dict[str, object]) -> tuple[str, bool]:
        """도구를 실행해 (결과 문자열, 중단 여부)를 돌려준다."""
        try:
            if name == "read_file":
                path = self.resolve(str(args.get("path", "")))
                self.read_paths.append(str(path))
                return path.read_text(encoding="utf-8", errors="replace")[
                    :MAX_TOOL_OUTPUT
                ], False
            if name in self.skills and name != "activate_skill":
                # 작은 모델은 스킬 이름을 도구 이름처럼 부르기도 한다. 스킬을 켠 것으로 본다
                args = {"name": name}
                name = "activate_skill"
            if name == "activate_skill" and str(args.get("name")) in self.skills:
                skill = str(args["name"])
                self.activated.append(skill)
                return activate(skill, self.skills[skill]), False
            if name == "list_dir":
                path = self.resolve(str(args.get("path", ".")))
                return "\n".join(
                    sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
                ), False
            if name == "write_file":
                path = self.resolve(str(args.get("path", "")))
                if not (
                    path.is_relative_to(self.workdir) or path.is_relative_to(self.home)
                ):
                    return (
                        f"오류: 작업 폴더({self.workdir})나 홈({self.home}) 밖에는 쓸 수 없다",
                        False,
                    )
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(str(args.get("content", "")), encoding="utf-8")
                return f"썼다: {path}", False
            if name == "ask_user":
                self.asked.append(str(args.get("questions", "")))
                return (
                    "사용자가 지금 답할 수 없다. 질문을 보고로 남기고 작업을 멈춘다.",
                    True,
                )
            if name == "run_command" and self.allow_commands:
                command = str(args.get("command", ""))
                env = sandbox_env(self.home)
                started = time.monotonic()
                try:
                    proc = subprocess.run(
                        ["bash", "-lc", command],
                        cwd=self.workdir,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=self.command_timeout,
                        check=False,
                    )
                    output, code = (proc.stdout + proc.stderr), proc.returncode
                except subprocess.TimeoutExpired:
                    output, code = f"시간 초과({self.command_timeout}초)", 124
                self.commands.append(
                    {
                        "command": command,
                        "exit": code,
                        "seconds": round(time.monotonic() - started, 1),
                    }
                )
                return f"exit={code}\n{output[-MAX_TOOL_OUTPUT:]}", False
            return f"오류: 알 수 없는 도구 {name}", False
        except OSError as exc:
            return f"오류: {exc}", False


def activate(name: str, skill_dir: Path) -> str:
    """activate_skill 결과: frontmatter 를 뺀 본문, 스킬 폴더, 함께 든 파일 목록(내용은 읽지 않음)."""
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    body = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL).strip()
    resources = sorted(
        str(p.relative_to(skill_dir))
        for p in skill_dir.rglob("*")
        if p.is_file() and p.name != "SKILL.md" and "__pycache__" not in p.parts
    )
    files = "\n".join(f"  <file>{r}</file>" for r in resources)
    return (
        f'<skill_content name="{name}">\n{body}\n\n스킬 폴더: {skill_dir}\n'
        f"이 스킬의 상대 경로는 스킬 폴더 기준이다.\n\n<skill_resources>\n{files}\n</skill_resources>\n</skill_content>"
    )


def remote_path(raw: str) -> str:
    """원격 셸에서 쓸 경로 식. ~ 는 원격 $HOME 으로 풀고 나머지는 따옴표로 감싼다."""
    text = raw.strip()
    if text in ("~", ""):
        return '"$HOME"' if text else "."
    if text.startswith("~/"):
        return '"$HOME"/' + shlex.quote(text[2:])
    return shlex.quote(text)


Runner = Callable[..., subprocess.CompletedProcess]


class RemoteSandbox:
    """도구 호출을 모두 ssh 로 원격 호스트(평가 샌드박스)에서 실행한다. 작업 PC 에는 아무것도 쓰지 않는다."""

    def __init__(
        self,
        target: str,
        ssh_options: list[str],
        workdir: str,
        home: str,
        command_timeout: int,
        skills: dict[str, tuple[Path, str]] | None = None,
        runner: Runner = subprocess.run,
    ) -> None:
        self.target, self.ssh_options, self.runner = target, ssh_options, runner
        self.workdir, self.home, self.command_timeout = workdir, home, command_timeout
        self.allow_commands = True
        self.local_skills = {n: local for n, (local, _) in (skills or {}).items()}
        self.skills = {
            n: remote for n, (_, remote) in (skills or {}).items()
        }  # 이름 → 원격 스킬 폴더
        self.read_paths: list[str] = []
        self.commands: list[dict[str, object]] = []
        self.asked: list[str] = []
        self.activated: list[str] = []

    def ssh(
        self, script: str, stdin: str | bytes | None = None, timeout: int | None = None
    ) -> tuple[int, str]:
        cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            *self.ssh_options,
            self.target,
            script,
        ]
        text = not isinstance(stdin, bytes)
        try:
            proc = self.runner(cmd, input=stdin, capture_output=True, text=text, timeout=timeout or self.command_timeout,
                               check=False)  # fmt: skip
        except subprocess.TimeoutExpired:
            return 124, f"시간 초과({timeout or self.command_timeout}초)"
        out = proc.stdout + proc.stderr
        return proc.returncode, out if isinstance(out, str) else out.decode(
            errors="replace"
        )

    def in_workdir(self, script: str) -> str:
        return f"cd {shlex.quote(self.workdir)} && {script}"

    def call(self, name: str, args: dict[str, object]) -> tuple[str, bool]:
        """도구를 원격에서 실행해 (결과 문자열, 중단 여부)를 돌려준다."""
        if name in self.skills and name != "activate_skill":
            args, name = {"name": name}, "activate_skill"
        if name == "activate_skill" and str(args.get("name")) in self.skills:
            skill = str(args["name"])
            self.activated.append(skill)
            local = self.local_skills[skill]
            return activate(skill, local).replace(str(local), self.skills[skill]), False
        if name == "ask_user":
            self.asked.append(str(args.get("questions", "")))
            return (
                "사용자가 지금 답할 수 없다. 질문을 보고로 남기고 작업을 멈춘다.",
                True,
            )
        path = remote_path(str(args.get("path", "")))
        if name == "read_file":
            self.read_paths.append(str(args.get("path", "")).strip())
            code, out = self.ssh(self.in_workdir(f"cat -- {path}"))
            return (
                out[:MAX_TOOL_OUTPUT] if code == 0 else f"오류: {out.strip()[-500:]}"
            ), False
        if name == "list_dir":
            code, out = self.ssh(self.in_workdir(f"ls -1Ap -- {path or '.'}"))
            return (out if code == 0 else f"오류: {out.strip()[-500:]}"), False
        if name == "write_file":
            script = f'mkdir -p "$(dirname -- {path})" && cat > {path}'
            code, out = self.ssh(
                self.in_workdir(script), stdin=str(args.get("content", ""))
            )
            return (
                f"썼다: {args.get('path')}"
                if code == 0
                else f"오류: {out.strip()[-500:]}"
            ), False
        if name == "run_command":
            command = str(args.get("command", ""))
            started = time.monotonic()
            code, out = self.ssh(self.in_workdir("bash -lc " + shlex.quote(command)))
            self.commands.append(
                {
                    "command": command,
                    "exit": code,
                    "seconds": round(time.monotonic() - started, 1),
                }
            )
            return f"exit={code}\n{out[-MAX_TOOL_OUTPUT:]}", False
        return f"오류: 알 수 없는 도구 {name}", False


# 모델에게 보이는 스킬 사본에서 뺀다. evals/ 에는 정답(확인 명령)과 가짜 환경 파일이 있어 모델이 그쪽으로 빠진다
EXCLUDED_DIRS = {"__pycache__", "evals"}


def pack_dir(root: Path) -> bytes:
    """폴더를 tar.gz 바이트로 묶는다(캐시·점검 사례 제외)."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root)
            if EXCLUDED_DIRS & set(rel.parts):
                continue
            tar.add(path, arcname=str(rel), recursive=False)
    return buffer.getvalue()


def remote_prepare(
    box: RemoteSandbox,
    skills_root: str,
    skill_dirs: list[Path],
    reset: str | None,
    ready: str | None,
    wait: int,
) -> str | None:
    """사례 하나를 시작하기 전: 초기화 명령 → 접속·준비 대기 → 작업 폴더와 스킬 사본. 실패하면 오류 문장."""
    if reset:
        proc = subprocess.run(
            ["bash", "-lc", reset],
            capture_output=True,
            text=True,
            timeout=wait,
            check=False,
        )
        if proc.returncode != 0:
            return f"초기화 실패: {(proc.stdout + proc.stderr).strip()[-500:]}"
    deadline = time.monotonic() + wait
    while True:
        code, out = box.ssh(ready or "true", timeout=60)
        if code == 0:
            break
        if time.monotonic() > deadline:
            return f"원격 준비 대기 시간 초과: {out.strip()[-300:]}"
        time.sleep(10)
    root = shlex.quote(skills_root)
    code, out = box.ssh(
        f"rm -rf {root} && mkdir -p {root} {shlex.quote(box.workdir)}", timeout=60
    )
    if code != 0:
        return f"원격 폴더 준비 실패: {out[-300:]}"
    for skill in skill_dirs:
        dest = shlex.quote(f"{skills_root}/{skill.name}")
        code, out = box.ssh(
            f"mkdir -p {dest} && tar -xzf - -C {dest}",
            stdin=pack_dir(skill),
            timeout=120,
        )
        if code != 0:
            return f"스킬 복사 실패({skill.name}): {out[-300:]}"
    return None


def run_task(
    client: Client,
    skills: list[dict[str, str]],
    task: str,
    sandbox: Sandbox,
    max_turns: int,
    instructions: str = "",
) -> dict[str, object]:
    by_tool = bool(sandbox.skills)
    block = (SKILLS_BY_TOOL if by_tool else SKILLS_BY_FILE).format(
        catalog=catalog_text(skills)
    )
    system = RUN_PROMPT.format(
        workdir=sandbox.workdir, home=sandbox.home, skills_block=block
    )
    if instructions.strip():
        # 실제 에이전트 도구처럼 사용자 전역 지침(AGENTS.md 등)을 시스템 지침에 넣는다
        system += (
            "\n\n다음은 사용자의 지침이다. 항상 따른다.\n\n" + instructions.strip()
        )
    messages: list[dict[str, object]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": task},
    ]
    tools = tool_specs(
        sandbox.allow_commands, sorted(sandbox.skills) if by_tool else None
    )
    calls_log: list[dict[str, object]] = []
    final, stopped, turn = "", "max_turns", 0
    for turn in range(1, max_turns + 1):
        reply = client.chat(messages, tools)
        messages.append(client.assistant_message(reply))
        if not reply["tool_calls"]:
            final, stopped = str(reply["content"]), "answered"
            break
        halt = False
        for call in reply["tool_calls"]:  # type: ignore[union-attr]
            output, stop = sandbox.call(str(call["name"]), call["arguments"])  # type: ignore[arg-type]
            short = {k: (str(v)[:200]) for k, v in call["arguments"].items()}  # type: ignore[union-attr]
            calls_log.append(
                {
                    "turn": turn,
                    "tool": call["name"],
                    "args": short,
                    "result": output[:300],
                }
            )
            log.info(
                "[%d] %s %s",
                turn,
                call["name"],
                json.dumps(short, ensure_ascii=False)[:160],
            )
            messages.append(client.tool_result(call, output))
            halt = halt or stop
        if halt:
            final, stopped = str(reply["content"]), "asked_user"
            break
    locations = {s["location"]: s["name"] for s in skills}
    return {
        "turns": turn,
        "stopped": stopped,
        "skills_read": sorted(
            {locations[p] for p in sandbox.read_paths if p in locations}
            | set(sandbox.activated)
        ),
        "files_read": sandbox.read_paths,
        "commands": sandbox.commands,
        "asked": sandbox.asked,
        "final": final,
        "tool_calls": calls_log,
        "messages": messages,
    }


def behavior_checks(
    case: dict[str, object], result: dict[str, object]
) -> list[dict[str, object]]:
    """사례의 행동 기대치를 대화 기록으로 확인한다.

    - expect_skill: 켜야 하는 스킬 이름
    - expect_commands: 실행했어야 하는 명령의 정규식 목록(하나라도 맞는 명령이 있어야 한다)
    - expect_ask: true 면 사용자에게 물었어야 하고, false 면 묻지 않았어야 한다
    - expect_final / reject_final: 최종 답변에 있어야 할 / 없어야 할 정규식 목록
    """
    checks: list[dict[str, object]] = []
    if skill := case.get("expect_skill"):
        read = result["skills_read"]
        checks.append(
            {
                "check": f"스킬 {skill} 을 켰다",
                "pass": skill in read,
                "output": f"켠 스킬: {read}",
            }
        )  # type: ignore[operator]
    commands = [str(c["command"]) for c in result["commands"]]  # type: ignore[union-attr]
    for pattern in case.get("expect_commands", []):  # type: ignore[union-attr]
        hit = any(re.search(str(pattern), c) for c in commands)
        checks.append(
            {
                "check": f"명령 /{pattern}/ 을 실행했다",
                "pass": hit,
                "output": "; ".join(commands)[-300:],
            }
        )
    final = str(result.get("final", ""))
    for pattern in case.get("expect_final", []):  # type: ignore[union-attr]
        checks.append(
            {
                "check": f"답변에 /{pattern}/ 이 있다",
                "pass": bool(re.search(str(pattern), final)),
                "output": final[-300:],
            }
        )
    for pattern in case.get("reject_final", []):  # type: ignore[union-attr]
        hit = re.search(str(pattern), final)
        checks.append(
            {
                "check": f"답변에 /{pattern}/ 이 없다",
                "pass": not hit,
                "output": hit.group(0) if hit else "",
            }
        )
    if "expect_ask" in case:
        # ask_user 도구 대신 최종 답변에서 질문해도 실제 도구에서는 물은 것이다
        asked = bool(result["asked"]) or bool(
            ASK_RE.search(str(result.get("final", "")))
        )
        checks.append(
            {
                "check": "사용자에게 물었다"
                if case["expect_ask"]
                else "사용자에게 묻지 않았다",
                "pass": asked == bool(case["expect_ask"]),
                "output": str(result["asked"])[:300],
            }
        )
    return checks


def run_checks(
    checks: list[str], workdir: Path, home: Path, skills_dir: Path
) -> list[dict[str, object]]:
    """평가 작성자가 정한 확인 명령(사례의 checks)을 작업 폴더에서 실행한다. exit 0 이면 통과.

    명령 안에서 스킬들이 든 폴더를 `$EVAL_SKILLS_DIR` 로 가리킬 수 있다.
    """
    results = []
    for command in checks:
        proc = subprocess.run(
            ["bash", "-lc", command],
            cwd=workdir,
            env=sandbox_env(home, skills_dir),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        results.append(
            {
                "check": command,
                "pass": proc.returncode == 0,
                "output": (proc.stdout + proc.stderr)[-500:],
            }
        )
    return results


# ---------------------------------------------------------------- 결과 기록


def run_checks_remote(
    checks: list[str], box: RemoteSandbox, skills_dir: str
) -> list[dict[str, object]]:
    """확인 명령을 원격 작업 폴더에서 실행한다. $EVAL_SKILLS_DIR 는 원격 스킬 사본 폴더다."""
    results = []
    for command in checks:
        script = box.in_workdir(
            f"EVAL_SKILLS_DIR={shlex.quote(skills_dir)} bash -lc {shlex.quote(command)}"
        )
        code, out = box.ssh(script, timeout=300)
        results.append({"check": command, "pass": code == 0, "output": out[-500:]})
    return results


def record(evals_dir: Path, entry: dict[str, object]) -> Path:
    """<스킬>/evals/results.json 에 모델별 결과를 남긴다. 모델·모드·API·생각 모드·켜는 방식이 같은 이전 결과는 바꾼다.

    다른 PC 에서도 의미가 있도록 경로·출력 같은 환경 정보는 넣지 않는다.
    """
    path = evals_dir / "results.json"
    skill_md = evals_dir.parent / "SKILL.md"
    if skill_md.is_file():
        # 어느 판의 스킬에 대한 결과인지 남긴다. SKILL.md 가 바뀌면 값이 달라진다
        entry = {
            **entry,
            "skill_sha": hashlib.sha256(skill_md.read_bytes()).hexdigest()[:12],
        }
    # 모델마다 다른 서버로 여러 점검을 동시에 돌리면 같은 파일을 함께 고친다. 읽기부터 쓰기까지 잠근다
    with (evals_dir / ".results.lock").open("w") as lock:
        if fcntl is not None:
            fcntl.flock(lock, fcntl.LOCK_EX)
        data = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.is_file()
            else {"results": []}
        )
        fields = ("model", "mode", "api", "think", "activation")
        key = tuple(entry.get(f) for f in fields)
        data["results"] = [
            r for r in data["results"] if tuple(r.get(f) for f in fields) != key
        ]
        data["results"].append(entry)
        data["results"].sort(
            key=lambda r: (r["mode"], r["model"], bool(r.get("think")))
        )
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        tmp.replace(path)
    return path


def record_trigger(summary: dict, base: dict[str, object]) -> list[str]:
    by_source: dict[str, list[dict]] = {}
    for r in summary["results"]:
        if r.get("source"):
            by_source.setdefault(r["source"], []).append(r)
    written = []
    for source, rows in by_source.items():
        entry = {
            **base,
            "mode": "trigger",
            "passed": sum(r["pass"] for r in rows),
            "total": len(rows),
            "failures": [
                {"query": r["query"], "expect": r["expect"], "picks": r["picks"]}
                for r in rows
                if not r["pass"]
            ],
        }
        written.append(str(record(Path(source), entry)))
    return written


def record_run(evals_path: Path, outcomes: list[dict], base: dict[str, object]) -> str:
    cases = [
        {
            "id": o["id"],
            "pass": all(c["pass"] for c in o["checks"]),
            "skills_read": o["skills_read"],
            "checks_passed": sum(c["pass"] for c in o["checks"]),
            "checks_total": len(o["checks"]),
            "failed_checks": [c["check"] for c in o["checks"] if not c["pass"]],
        }
        for o in outcomes
    ]
    entry = {
        **base,
        "mode": "run",
        "passed": sum(c["pass"] for c in cases),
        "total": len(cases),
        "cases": cases,
    }
    return str(record(evals_path.resolve().parent, entry))


def report(skill_dirs: list[Path]) -> str:
    """스킬마다 results.json 을 모델·모드별 마크다운 표로 만든다. 현재 SKILL.md 판의 결과인지 표시한다."""
    lines = [
        "| 스킬 | 모드 | 모델 | 생각 | 통과 | 확인 항목 | 날짜 | 현재 판 |",
        "| :--- | :--- | :--- | :--- | ---: | ---: | :--- | :--- |",
    ]
    for skill in skill_dirs:
        path = skill / "evals" / "results.json"
        if not path.is_file():
            lines.append(f"| {skill.name} | - | - | - | - | - | - | 결과 없음 |")
            continue
        current = hashlib.sha256((skill / "SKILL.md").read_bytes()).hexdigest()[:12]
        for r in json.loads(path.read_text(encoding="utf-8"))["results"]:
            same = "예" if r.get("skill_sha") == current else "아니오"
            think = "켬" if r.get("think") else "끔"
            cases = r.get("cases") or []
            checks = "-"
            if cases and all("checks_total" in c for c in cases):
                checks = f"{sum(c['checks_passed'] for c in cases)}/{sum(c['checks_total'] for c in cases)}"
            lines.append(
                f"| {skill.name} | {r['mode']} | {r['model']} | {think} | {r.get('passed')}/{r.get('total')} "
                f"| {checks} | {r.get('date', '')} | {same} |"
            )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="저사양 로컬 모델로 스킬의 트리거와 실행을 점검한다.",
        epilog=(
            "예:\n"
            "  local_eval.py trigger --skills skills/* --queries skills/*/evals/triggers.json --runs 5\n"
            "  local_eval.py run --skills skills/* --evals skills/x/evals/evals.json --workdir /tmp/ev --allow-commands\n"
            "  local_eval.py run --skills skills/* --task '이 절차를 스킬로 만들어 줘' --workdir /tmp/ev\n"
            "  local_eval.py report --skills skills/*   # 기록된 결과를 표로\n\n"
            "모델 서버: --base-url 또는 LOCAL_LLM_URL(기본 http://127.0.0.1:11434), --model 또는 LOCAL_LLM_MODEL.\n"
            "OpenAI 호환 서버에 키가 필요하면 LOCAL_LLM_API_KEY.\n"
            'triggers.json: [{"query": "...", "expect": "<스킬 이름>" | ["<스킬>", ...] | null}]\n'
            'evals.json: {"evals": [{"id", "prompt", "expect_skill", "expect_commands": [정규식], "expect_ask": bool,\n'
            '             "expect_final": [정규식], "reject_final": [정규식], "home_files": {"홈 기준 경로": "evals 기준 파일"},\n'
            '             "checks": ["작업 폴더에서 실행할 확인 명령, $EVAL_SKILLS_DIR 사용 가능"]}]}\n'
            "run_command 는 모델이 만든 명령을 그대로 실행하므로 --allow-commands 를 줄 때만 켜진다. 버려도 되는 폴더에서 돌린다.\n"
            "출력: stdout 에 요약 JSON, --output 에 대화 전체.\n"
            "exit code: 0 통과, 1 모델 호출 실패, 2 사용법 오류, 3 점검 실패(트리거 오답 또는 checks 실패)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "mode",
        choices=["trigger", "run", "report"],
        help="report: results.json 을 표로 낸다",
    )
    parser.add_argument(
        "--skills",
        nargs="+",
        type=Path,
        required=True,
        help="스킬 폴더들(목록에 올릴 스킬)",
    )
    parser.add_argument(
        "--queries",
        nargs="+",
        type=Path,
        help="trigger: 질의 JSON 파일(여러 개면 합친다)",
    )
    parser.add_argument(
        "--runs", type=int, default=3, help="trigger: 질의당 반복 횟수 (기본 3)"
    )
    parser.add_argument("--task", help="run: 과제 문장")
    parser.add_argument(
        "--evals", type=Path, help="run: evals.json (모든 사례를 차례로 실행)"
    )
    parser.add_argument("--workdir", type=Path, help="run: 작업 폴더(없으면 만든다)")
    parser.add_argument(
        "--home", type=Path, help="run: 모델에게 보일 홈 폴더 (기본 <workdir>/home)"
    )
    parser.add_argument(
        "--allow-commands", action="store_true", help="run: 셸 명령 도구를 켠다"
    )
    parser.add_argument(
        "--max-turns", type=int, default=25, help="run: 최대 왕복 수 (기본 25)"
    )
    parser.add_argument(
        "--command-timeout",
        type=int,
        default=120,
        help="run: 명령 하나의 제한 시간(초)",
    )
    parser.add_argument(
        "--instructions",
        action="append",
        default=[],
        metavar="PATH",
        help="run: 시스템 지침에 넣을 사용자 지침 파일(여러 번). 실제 도구처럼 전역 AGENTS.md 를 줄 때 쓴다. "
        "~ 는 모델에게 보이는 홈(원격이면 원격 홈) 기준",
    )
    parser.add_argument(
        "--remote",
        metavar="[USER@]HOST",
        help="run: 도구 호출을 모두 이 호스트에서 ssh 로 실행한다(평가 샌드박스)",
    )
    parser.add_argument("--ssh-option", action="append", default=[], metavar="OPT",
                        help="run: ssh 에 넘길 옵션(여러 번). 예: --ssh-option=-i --ssh-option ~/.ssh/eval_sandbox")  # fmt: skip
    parser.add_argument(
        "--reset",
        metavar="CMD",
        help="run: 사례마다 먼저 실행할 로컬 명령(예: 샌드박스 스냅샷 되돌리기)",
    )
    parser.add_argument(
        "--ready",
        metavar="CMD",
        help="run: 원격에서 exit 0 이 될 때까지 기다릴 명령(예: kubectl get nodes)",
    )
    parser.add_argument(
        "--remote-wait",
        type=int,
        default=900,
        help="run: 초기화·준비 대기 최대 초 (기본 900)",
    )
    parser.add_argument(
        "--activation",
        choices=["tool", "file"],
        default="tool",
        help="run: 스킬을 activate_skill 도구로 켜게 할지(기본), 파일 읽기로 켜게 할지",
    )
    parser.add_argument(
        "--api",
        choices=["ollama", "openai"],
        default="ollama",
        help="모델 서버 API (기본 ollama)",
    )
    parser.add_argument(
        "--base-url", default=os.environ.get("LOCAL_LLM_URL", "http://127.0.0.1:11434")
    )
    parser.add_argument("--model", default=os.environ.get("LOCAL_LLM_MODEL"))
    parser.add_argument(
        "--num-ctx", type=int, default=32768, help="ollama 컨텍스트 길이 (기본 32768)"
    )
    parser.add_argument(
        "--think", action="store_true", help="모델의 생각(thinking) 모드를 켠다"
    )
    parser.add_argument(
        "--timeout", type=int, default=900, help="모델 요청 하나의 제한 시간(초)"
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="결과를 질의·사례 파일 옆 results.json 에 모델별로 남긴다",
    )
    parser.add_argument("--output", type=Path, help="대화 전체를 저장할 JSON 파일")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    if args.mode == "report":
        sys.stdout.write(report([p.resolve() for p in args.skills]))
        return EXIT_OK
    if not args.model:
        log.error("오류: --model 또는 LOCAL_LLM_MODEL 이 필요하다 (예: gemma4:e4b)")
        return EXIT_USAGE
    skill_dirs = [p.resolve() for p in args.skills]
    temp_workdir = None
    if args.mode == "run" and args.remote and not args.workdir:
        # 스킬 사본만 둔다. 모델은 원격만 본다. 끝나면 지운다
        temp_workdir = args.workdir = Path(tempfile.mkdtemp(prefix="local_eval-"))
    if args.mode == "run" and args.workdir:
        # 모델이 실제 스킬 저장소를 고치지 못하게 사본을 보여 준다. 명령은 작업 폴더 밖에도 쓸 수 있기 때문이다
        snapshot = args.workdir.resolve() / "_skills"
        shutil.rmtree(snapshot, ignore_errors=True)
        skill_dirs = [
            Path(
                shutil.copytree(
                    p,
                    snapshot / p.name,
                    ignore=shutil.ignore_patterns(*EXCLUDED_DIRS),
                )
            )
            for p in skill_dirs
        ]
    try:
        skills = [read_skill(p) for p in skill_dirs]
    except (OSError, ValueError) as exc:
        log.error("오류: 스킬을 읽을 수 없다: %s", exc)
        return EXIT_USAGE
    client = Client(
        args.api, args.base_url, args.model, args.num_ctx, args.think, args.timeout
    )
    started = time.monotonic()
    try:
        if args.mode == "trigger":
            if not args.queries:
                log.error("오류: trigger 에는 --queries 가 필요하다")
                return EXIT_USAGE
            queries = [
                {**q, "_source": str(path.resolve().parent)}
                for path in args.queries
                for q in json.loads(path.read_text(encoding="utf-8"))
            ]
            summary = run_trigger(
                client,
                skills,
                queries,
                args.runs,
            )
            ok = summary["passed"] == summary["total"]
            transcript: object = summary
        else:
            if not (args.workdir or args.remote) or not (args.task or args.evals):
                log.error(
                    "오류: run 에는 --workdir(또는 --remote) 와 --task 또는 --evals 가 필요하다"
                )
                return EXIT_USAGE
            cases = (
                json.loads(args.evals.read_text(encoding="utf-8"))["evals"]
                if args.evals
                else [{"id": "task", "prompt": args.task, "checks": []}]
            )
            outcomes, transcript, ok = [], [], True
            remote_home = ""
            if args.remote:
                probe = RemoteSandbox(
                    args.remote, args.ssh_option, "/", "", args.command_timeout
                )
                if args.reset or args.ready:
                    error = remote_prepare(
                        probe,
                        "/tmp/local_eval-probe",
                        [],
                        args.reset,
                        args.ready,
                        args.remote_wait,
                    )
                    if error:
                        log.error("오류: %s", error)
                        return EXIT_FAILED
                code, remote_home = probe.ssh('printf %s "$HOME"', timeout=60)
                if code != 0 or not remote_home.startswith("/"):
                    log.error(
                        "오류: 원격 호스트에 붙을 수 없다: %s",
                        remote_home.strip()[-300:],
                    )
                    return EXIT_FAILED
            for case_index, case in enumerate(cases):
                if args.remote:
                    case_id = str(case.get("id", "task"))
                    root = f"{remote_home}/eval"
                    remote_skills = {
                        s["name"]: (d, f"{root}/_skills/{d.name}")
                        for s, d in zip(skills, skill_dirs)
                    }
                    box = RemoteSandbox(args.remote, args.ssh_option, f"{root}/{case_id}", remote_home,
                                        args.command_timeout, remote_skills if args.activation == "tool" else None)  # fmt: skip
                    box.skills = box.skills if args.activation == "tool" else {}
                    log.info("== 사례 %s (원격 %s)", case_id, args.remote)
                    error = remote_prepare(box, f"{root}/_skills", skill_dirs,
                                           args.reset if case_index or not (args.reset or args.ready) else None,
                                           args.ready, args.remote_wait)  # fmt: skip
                    if error:
                        log.error("오류: %s", error)
                        return EXIT_FAILED
                    remote_catalog = [
                        {**s, "location": f"{root}/_skills/{d.name}/SKILL.md"}
                        for s, d in zip(skills, skill_dirs)
                    ]
                    instructions = ""
                    for path in args.instructions:
                        code, text = box.ssh(f"cat -- {remote_path(path)}", timeout=30)
                        if code != 0:
                            log.error(
                                "오류: 지침 파일을 읽을 수 없다: %s",
                                text.strip()[-300:],
                            )
                            return EXIT_FAILED
                        instructions += text + "\n"
                    result = run_task(
                        client,
                        remote_catalog,
                        str(case["prompt"]),
                        box,
                        args.max_turns,
                        instructions,
                    )
                    checks = behavior_checks(case, result) + run_checks_remote(
                        case.get("checks", []), box, f"{root}/_skills"
                    )
                    ok = ok and all(c["pass"] for c in checks)
                    transcript.append({"id": case_id, **result})  # type: ignore[union-attr]
                    outcomes.append({"id": case_id, "workdir": f"{args.remote}:{box.workdir}",
                                     **{k: v for k, v in result.items() if k not in {"messages", "tool_calls", "files_read"}},
                                     "checks": checks})  # fmt: skip
                    continue
                workdir = (args.workdir / str(case.get("id", "task"))).resolve()
                home = (args.home or workdir / "home").resolve()
                workdir.mkdir(parents=True, exist_ok=True)
                home.mkdir(parents=True, exist_ok=True)
                for rel, source in dict(case.get("home_files", {})).items():
                    # 사례가 가정하는 환경 파일(예: 가짜 environment.md)을 모델의 홈에 넣는다
                    target = home / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(args.evals.resolve().parent / source, target)
                sandbox = Sandbox(
                    workdir,
                    home,
                    args.allow_commands,
                    args.command_timeout,
                    skills if args.activation == "tool" else None,
                )
                log.info("== 사례 %s", case.get("id"))
                missing = [
                    p for p in args.instructions if not sandbox.resolve(p).is_file()
                ]
                if missing:
                    log.error("오류: 지침 파일이 없다: %s", ", ".join(missing))
                    return EXIT_FAILED
                instructions = "".join(
                    sandbox.resolve(path).read_text(encoding="utf-8") + "\n"
                    for path in args.instructions
                )
                result = run_task(
                    client,
                    skills,
                    str(case["prompt"]),
                    sandbox,
                    args.max_turns,
                    instructions,
                )
                checks = behavior_checks(case, result) + run_checks(
                    case.get("checks", []),
                    workdir,
                    home,
                    skill_dirs[0].parent,
                )
                ok = ok and all(c["pass"] for c in checks)
                transcript.append({"id": case.get("id"), **result})  # type: ignore[union-attr]
                outcomes.append(
                    {
                        "id": case.get("id"),
                        "workdir": str(workdir),
                        **{
                            k: v
                            for k, v in result.items()
                            if k not in {"messages", "tool_calls", "files_read"}
                        },
                        "checks": checks,
                    }
                )
            summary = {"mode": "run", "cases": outcomes}
    except (urllib.error.URLError, TimeoutError, KeyError) as exc:
        log.error("오류: 모델 호출 실패: %s", exc)
        return EXIT_FAILED
    summary.update(
        {
            "model": args.model,
            "seconds": round(time.monotonic() - started, 1),
            "usage": dict(client.usage),
        }
    )
    if args.record:
        base: dict[str, object] = {
            "model": args.model,
            "api": args.api,
            "date": datetime.datetime.now().astimezone().date().isoformat(),
            "think": args.think,
        }
        if args.mode == "trigger":
            summary["recorded"] = record_trigger(summary, {**base, "runs": args.runs})
        elif args.evals:
            summary["recorded"] = [
                record_run(
                    args.evals, outcomes, {**base, "activation": args.activation}
                )
            ]
        else:
            log.warning(
                "--task 로 준 과제는 기록하지 않는다. evals.json 사례로 만들어 --evals 로 돌린다"
            )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(transcript, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=2, default=str)
    sys.stdout.write("\n")
    if temp_workdir:
        shutil.rmtree(temp_workdir, ignore_errors=True)
    return EXIT_OK if ok else EXIT_CHECKS_FAILED


if __name__ == "__main__":
    sys.exit(main())
