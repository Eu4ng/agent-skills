#!/usr/bin/env python3
"""Home Assistant WebSocket API 를 불러 레지스트리를 조회·변경한다. UI 로 하던 일을 명령으로 한다.

작업 PC 에서 --kubectl 로 부르면 이 스크립트가 알아서 한다: 시크릿에서 토큰을 꺼내고(출력하지 않음), 자기 자신을
HA 파드 안에서 실행한다(aiohttp 는 HA 컨테이너에 있다). 예:
  python3 ha_ws.py --kubectl "ssh cp kubectl" --summary
파드 안에서 직접 실행할 때는 토큰을 HA_TOKEN 환경 변수로 준다. 결과는 stdout 에 JSON 으로 낸다.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import shlex
import subprocess
import sys
from collections import Counter
from pathlib import Path

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_AUTH = 3

LISTS = {
    "entities": "config/entity_registry/list",
    "devices": "config/device_registry/list",
    "areas": "config/area_registry/list",
    "entries": "config_entries/get",
    "states": "get_states",
}
READ_ONLY = set(LISTS.values()) | {"get_config", "get_services"}


def summarize(
    entities: list[dict], devices: list[dict], areas: list[dict]
) -> dict[str, object]:
    """레지스트리를 한눈에 볼 수 있게 센다."""
    by_platform = Counter(e.get("platform") for e in entities)
    disabled = Counter(
        f"{e.get('platform')}:{e.get('disabled_by')}"
        for e in entities
        if e.get("disabled_by")
    )
    no_area = [
        d.get("name_by_user") or d.get("name")
        for d in devices
        if not d.get("area_id")
        and not d.get("disabled_by")
        and d.get("entry_type") != "service"
    ]
    return {
        "entities": len(entities),
        "devices": len(devices),
        "areas": [a.get("name") for a in areas],
        "entities_by_platform": dict(by_platform.most_common()),
        "disabled_by_platform_reason": dict(disabled.most_common()),
        "devices_without_area": sorted(n for n in no_area if n)[:200],
    }


async def run(
    url: str, token: str, calls: list[dict], summary: bool, dry_run: bool
) -> tuple[int, dict]:
    import aiohttp  # HA 컨테이너 안에는 있다

    results: dict[str, object] = {"calls": []}
    async with (
        aiohttp.ClientSession() as session,
        session.ws_connect(url, timeout=30) as ws,
    ):
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": token})
        auth = await ws.receive_json()
        if auth.get("type") != "auth_ok":
            return EXIT_AUTH, {
                "error": f"인증 실패: {auth.get('message', auth.get('type'))}"
            }
        next_id = 1

        async def call(payload: dict) -> dict:
            nonlocal next_id
            message = {**payload, "id": next_id}
            next_id += 1
            await ws.send_json(message)
            while True:
                reply = await ws.receive_json()
                if reply.get("id") == message["id"]:
                    return reply

        if summary:
            lists = {
                k: (await call({"type": LISTS[k]})).get("result") or []
                for k in ("entities", "devices", "areas")
            }
            results["summary"] = summarize(
                lists["entities"], lists["devices"], lists["areas"]
            )
        failed = False
        for payload in calls:
            if dry_run and payload.get("type") not in READ_ONLY:
                results["calls"].append({"request": payload, "sent": False})
                continue
            reply = await call(payload)
            ok = bool(reply.get("success", True))
            failed = failed or not ok
            results["calls"].append({"request": payload, "sent": True, "success": ok, "result": reply.get("result"),
                                     "error": reply.get("error")})  # fmt: skip
    return (EXIT_FAILED if failed else EXIT_OK), results


def kubectl_argv(prefix: str, args: list[str]) -> list[str]:
    """kubectl 실행 명령에 인자를 붙인다. 'ssh <호스트> kubectl' 처럼 ssh 를 거치면 원격 부분을 한 문자열로 묶는다."""
    tokens = shlex.split(prefix)
    if tokens and tokens[0] == "ssh":
        cut = next(
            (i for i, t in enumerate(tokens) if t.endswith(("kubectl", "k3s"))),
            len(tokens),
        )
        return tokens[:cut] + [shlex.join(tokens[cut:] + args)]
    return tokens + args


def read_secret(prefix: str, ref: str) -> str:
    """'네임스페이스/이름:키' 시크릿 값을 읽는다. 값은 출력하지 않는다."""
    name, _, key = ref.partition(":")
    ns, _, secret = name.partition("/")
    out = subprocess.run(
        kubectl_argv(prefix, ["-n", ns, "get", "secret", secret, "-o", f"jsonpath={{.data.{key or 'token'}}}"]),
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"시크릿 {ref} 를 읽지 못했다: {out.stderr.strip()[-200:]}")
    return base64.b64decode(out.stdout.strip()).decode()


def run_in_pod(args: argparse.Namespace, forward: list[str]) -> int:
    """토큰을 시크릿에서 꺼내 이 스크립트를 HA 파드 안에서 실행한다. 토큰은 인자가 아니라 stdin 으로 넘긴다."""
    try:
        token = read_secret(args.kubectl, args.token_secret)
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return EXIT_AUTH
    marker = "from __future__ import annotations\n"
    source = (
        Path(__file__)
        .read_text(encoding="utf-8")
        .replace(
            marker,
            marker + f"import os as _os\n_os.environ['HA_TOKEN'] = {token!r}\n",
            1,
        )
    )
    cmd = kubectl_argv(
        args.kubectl,
        ["-n", args.namespace, "exec", "-i", f"deploy/{args.deploy}", "-c", args.container, "--",
         "python3", "-", *forward],
    )  # fmt: skip
    return subprocess.run(cmd, input=source, text=True, check=False).returncode


def forward_args(argv: list[str]) -> list[str]:
    """파드 안으로 넘길 인자: 작업 PC 전용 옵션(--kubectl 등)을 뺀다."""
    drop = {"--kubectl", "--namespace", "--deploy", "--container", "--token-secret"}
    forward, skip = [], False
    for item in argv:
        if skip:
            skip = False
        elif item in drop:
            skip = True
        elif item.split("=", 1)[0] not in drop:
            forward.append(item)
    return forward


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Home Assistant WebSocket API 로 레지스트리를 조회·변경한다.",
        epilog=(
            "예:\n"
            '  python3 ha_ws.py --kubectl "ssh cp kubectl" --summary   # 작업 PC 에서 (권장)\n'
            "  ... python3 - --summary < ha_ws.py                      # 파드 안에서\n"
            "  ... python3 - --list entities --filter platform=mqtt < ha_ws.py\n"
            '  ... python3 - --dry-run --call \'{"type":"config/entity_registry/update","entity_id":"sensor.x",'
            '"new_entity_id":"sensor.y"}\' < ha_ws.py\n\n'
            "--list: entities, devices, areas, entries, states\n"
            '출력: {"summary"?, "list"?, "calls": [{request, sent, success, result, error}]}\n'
            "--dry-run 이면 조회가 아닌 호출은 보내지 않고 request 만 보여 준다.\n"
            "exit code: 0 성공, 1 실패한 호출 있음, 2 사용법 오류(aiohttp·토큰 없음 포함), 3 인증 실패"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--url", default=os.environ.get("HA_URL", "ws://127.0.0.1:8123/api/websocket")
    )
    parser.add_argument(
        "--kubectl",
        metavar="CMD",
        help='작업 PC 에서: kubectl 실행 명령(예: "kubectl", "ssh cp kubectl")',
    )
    parser.add_argument(
        "--namespace",
        default="home-assistant",
        help="--kubectl: HA 네임스페이스 (기본 home-assistant)",
    )
    parser.add_argument(
        "--deploy",
        default="home-assistant",
        help="--kubectl: HA 배포 이름 (기본 home-assistant)",
    )
    parser.add_argument(
        "--container",
        default="home-assistant",
        help="--kubectl: HA 컨테이너 (기본 home-assistant)",
    )
    parser.add_argument(
        "--token-secret", default="home-assistant/ha-api-token:token", metavar="NS/NAME:KEY",
        help="--kubectl: 장기 액세스 토큰 시크릿 (기본 home-assistant/ha-api-token:token)",
    )  # fmt: skip
    parser.add_argument(
        "--summary",
        action="store_true",
        help="엔티티·기기·영역 수와 비활성·영역 없는 기기를 센다",
    )
    parser.add_argument(
        "--list", choices=sorted(LISTS), help="레지스트리·상태 목록을 낸다"
    )
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="--list 결과를 거른다",
    )
    parser.add_argument(
        "--call",
        action="append",
        default=[],
        metavar="JSON",
        help="보낼 WebSocket 메시지(id 제외)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="변경 호출은 보내지 않는다"
    )
    parser.add_argument(
        "--limit", type=int, default=500, help="--list 최대 항목 수 (기본 500)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.kubectl:
        return run_in_pod(
            args, forward_args(list(sys.argv[1:] if argv is None else argv))
        )
    token = os.environ.get("HA_TOKEN")
    if not token:
        print(
            "오류: HA_TOKEN 환경 변수가 없다. 장기 액세스 토큰을 시크릿에서 꺼내 넘긴다",
            file=sys.stderr,
        )
        return EXIT_USAGE
    try:
        calls = [json.loads(c) for c in args.call]
    except json.JSONDecodeError as exc:
        print(f"오류: --call 은 JSON 이어야 한다: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if args.list:
        calls.insert(0, {"type": LISTS[args.list]})
    if not calls and not args.summary:
        print("오류: --summary, --list, --call 중 하나가 필요하다", file=sys.stderr)
        return EXIT_USAGE
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        print(
            "오류: aiohttp 가 없다. HA 컨테이너 안에서 실행한다(kubectl exec -i ... python3 - < ha_ws.py)",
            file=sys.stderr,
        )
        return EXIT_USAGE
    code, results = asyncio.run(run(args.url, token, calls, args.summary, args.dry_run))
    if args.list and results.get("calls"):
        items = results["calls"].pop(0).get("result") or []
        for key, _, value in (f.partition("=") for f in args.filter):
            items = [i for i in items if str(i.get(key)) == value]
        results["list"] = {"count": len(items), "items": items[: args.limit]}
    json.dump(results, sys.stdout, ensure_ascii=False, indent=2, default=str)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
