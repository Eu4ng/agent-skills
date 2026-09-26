#!/usr/bin/env python3
"""Argo CD 앱들이 지정한 커밋으로 Synced·Healthy 가 될 때까지 기다린다.

kubectl 이 있는 호스트에서 실행한다. 원격이면 stdin 으로 넘긴다:
  ssh <호스트> 'python3 - app-a app-b --revision 1a2b3c4 --refresh' < argo_wait.py
표준 라이브러리만 쓴다. 결과는 stdout 에 JSON, 진행 상황은 stderr 로 낸다.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time

EXIT_OK = 0
EXIT_NOT_READY = 1
EXIT_USAGE = 2
EXIT_KUBECTL = 3


def kubectl_argv(prefix: str, args: list[str]) -> list[str]:
    """kubectl 실행 명령에 인자를 붙인다. 'ssh <호스트> kubectl' 처럼 ssh 를 거치면 원격 부분을 한 문자열로 묶는다."""
    tokens = shlex.split(prefix)
    if tokens and tokens[0] == "ssh":
        # "ssh cp 'kubectl -n x'" 처럼 원격 명령을 따옴표로 묶어 넘겨도 같은 뜻으로 푼다
        tokens = [
            part for t in tokens for part in (shlex.split(t) if " " in t else [t])
        ]
        cut = next(
            (i for i, t in enumerate(tokens) if t.endswith(("kubectl", "k3s"))),
            len(tokens),
        )
        # 사용자가 쓴 앞부분(예: --kubeconfig ~/edge.yaml)은 원격 셸이 풀도록 그대로 두고, 붙이는 인자만 따옴표로 감싼다
        return tokens[:cut] + [" ".join([*tokens[cut:], shlex.join(args)])]
    return tokens + args


def kubectl(base: str, args: list[str], timeout: int = 30) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            kubectl_argv(base, args),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return 127, "kubectl 이 없다"
    except subprocess.TimeoutExpired:
        return 124, "kubectl 시간 초과"
    return proc.returncode, proc.stdout if proc.returncode == 0 else proc.stderr


def app_state(base: str, ns: str, name: str) -> dict[str, object]:
    """앱 하나의 동기화 상태. 앱이 아직 없으면 exists=False."""
    code, out = kubectl(base, ["-n", ns, "get", "application", name, "-o", "json"])
    if code != 0:
        return {"app": name, "exists": False, "error": out.strip()[-300:]}
    status = json.loads(out).get("status", {})
    sync = status.get("sync", {})
    operation = status.get("operationState", {})
    unhealthy = [
        f"{r.get('kind')}/{r.get('name')}: {r.get('status')} {r.get('health', {}).get('status', '')}".strip()
        for r in status.get("resources", [])
        if r.get("status") != "Synced"
        or r.get("health", {}).get("status") not in (None, "Healthy")
    ]
    conditions = [
        f"{c.get('type')}: {c.get('message', '')[:200]}"
        for c in status.get("conditions", [])
    ]
    return {
        "app": name,
        "exists": True,
        "revision": sync.get("revision", ""),
        "sync": sync.get("status"),
        "health": status.get("health", {}).get("status"),
        "operation": operation.get("phase"),
        "operation_message": (operation.get("message") or "")[:300],
        "unhealthy_resources": unhealthy[:20],
        "conditions": conditions,
    }


def ready(state: dict[str, object], revision: str | None) -> bool:
    if not state["exists"]:
        return False
    if revision and not str(state["revision"]).startswith(revision):
        return False
    return state["sync"] == "Synced" and state["health"] == "Healthy"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Argo CD 앱들이 지정한 커밋으로 Synced·Healthy 가 될 때까지 기다린다.",
        epilog=(
            "예:\n"
            "  python3 argo_wait.py grafana --revision 1a2b3c4 --refresh\n"
            '  python3 argo_wait.py grafana --revision 1a2b3c4 --kubectl "ssh cp kubectl"   # 작업 PC 에서\n'
            "  ssh <호스트> 'python3 - weather --appset iot-hub --revision 1a2b3c4' < argo_wait.py\n"
            "  python3 argo_wait.py app-a --kubeconfig ~/edge.yaml   # 다른 클러스터의 Argo CD\n\n"
            '출력: {"ready": bool, "waited_seconds": n, "apps": [{app, revision, sync, health, '
            "operation, unhealthy_resources, conditions}]}\n"
            "exit code: 0 모두 준비됨, 1 시간 안에 준비 안 됨(apps 의 conditions·unhealthy_resources 를 본다),\n"
            "           2 사용법 오류, 3 kubectl 실행 실패"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("apps", nargs="+", help="Argo CD Application 이름")
    parser.add_argument(
        "--revision", help="기다릴 커밋 SHA(앞부분만 줘도 된다). 없으면 상태만 본다"
    )
    parser.add_argument(
        "--refresh", action="store_true", help="시작할 때 앱에 refresh 를 요청한다"
    )
    parser.add_argument(
        "--appset", help="새 앱이 생길 ApplicationSet. 시작할 때 refresh 를 요청한다"
    )
    parser.add_argument(
        "--namespace", default="argocd", help="Argo CD 네임스페이스 (기본 argocd)"
    )
    parser.add_argument("--kubectl", default="kubectl", metavar="CMD",
                        help='kubectl 실행 명령 (기본 kubectl). 작업 PC 에서: "ssh cp kubectl"')  # fmt: skip
    parser.add_argument("--kubeconfig", help="kubectl 에 넘길 kubeconfig")
    parser.add_argument(
        "--timeout", type=int, default=600, help="최대 대기 초 (기본 600)"
    )
    parser.add_argument(
        "--interval", type=int, default=10, help="확인 간격 초 (기본 10)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    base = args.kubectl + (
        f" --kubeconfig {shlex.quote(args.kubeconfig)}" if args.kubeconfig else ""
    )
    code, out = kubectl(base, ["version", "--client", "-o", "json"])
    if code != 0:
        print(f"오류: kubectl 을 쓸 수 없다: {out.strip()}", file=sys.stderr)
        return EXIT_KUBECTL
    if args.appset:
        kubectl(
            base,
            ["-n", args.namespace, "annotate", "applicationset", args.appset,
             "argocd.argoproj.io/refresh=true", "--overwrite"],
        )  # fmt: skip
    if args.refresh:
        for app in args.apps:
            kubectl(
                base,
                ["-n", args.namespace, "annotate", "application", app,
                 "argocd.argoproj.io/refresh=normal", "--overwrite"],
            )  # fmt: skip
    started = time.monotonic()
    while True:
        states = [app_state(base, args.namespace, a) for a in args.apps]
        done = all(ready(s, args.revision) for s in states)
        waited = round(time.monotonic() - started)
        summary = ", ".join(
            f"{s['app']}={str(s.get('revision', ''))[:7]} {s.get('sync')} {s.get('health')}"
            for s in states
        )
        print(f"[{waited}s] {summary}", file=sys.stderr)
        if done or waited >= args.timeout:
            break
        time.sleep(args.interval)
    json.dump(
        {"ready": done, "waited_seconds": waited, "apps": states},
        sys.stdout,
        ensure_ascii=False,
        indent=2,
    )
    sys.stdout.write("\n")
    return EXIT_OK if done else EXIT_NOT_READY


if __name__ == "__main__":
    sys.exit(main())
