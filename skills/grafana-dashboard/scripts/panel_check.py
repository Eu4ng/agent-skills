#!/usr/bin/env python3
"""Grafana 대시보드의 모든 패널 쿼리를 실제로 실행해 오류·빈 결과를 찾는다.

대시보드 JSON 을 API 로 받아 템플릿 변수를 풀고(변수 쿼리도 실제로 실행한다), 반복 패널은 값마다 펼쳐
`/api/ds/query` 로 각 쿼리를 돌린다. SQL 계열 데이터소스(PostgreSQL·TimescaleDB·MySQL 등)의 rawSql 쿼리를 대상으로 한다.
화면을 그리는 것까지 확인하지는 않는다. 표준 라이브러리만 쓴다.

인증: GRAFANA_TOKEN(서비스 계정 토큰) 또는 GRAFANA_USER·GRAFANA_PASSWORD 환경 변수. 주소: --url 또는 GRAFANA_URL.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_HTTP = 3

VAR_RE = re.compile(r"\$\{(\w+)(?::(\w+))?\}|\[\[(\w+)(?::(\w+))?\]\]|\$(?!__)(\w+)")
SKIP_DS = {"-- Mixed --", "-- Dashboard --", "grafana"}

Fetch = Callable[[str, str, dict | None], dict]


class HttpError(Exception):
    pass


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


def load_admin_secret(prefix: str, ref: str) -> None:
    """시크릿(네임스페이스/이름)의 admin-user·admin-password 를 환경 변수로 읽어 둔다. 값은 출력하지 않는다."""
    ns, _, name = ref.partition("/")
    for key, env in (
        ("admin-user", "GRAFANA_USER"),
        ("admin-password", "GRAFANA_PASSWORD"),
    ):
        out = subprocess.run(
            kubectl_argv(prefix, ["-n", ns, "get", "secret", name, "-o", f"jsonpath={{.data.{key}}}"]),
            capture_output=True, text=True, timeout=60, check=False,
        )  # fmt: skip
        if out.returncode != 0 or not out.stdout.strip():
            raise HttpError(
                f"시크릿 {ref} 의 {key} 를 읽지 못했다: {out.stderr.strip()[-200:]}"
            )
        os.environ[env] = base64.b64decode(out.stdout.strip()).decode()


def make_fetch(url: str, timeout: int) -> Fetch:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token := os.environ.get("GRAFANA_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    elif os.environ.get("GRAFANA_USER"):
        pair = f"{os.environ['GRAFANA_USER']}:{os.environ.get('GRAFANA_PASSWORD', '')}"
        headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()

    def fetch(method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            url.rstrip("/") + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            if exc.code in (400, 500) and path.startswith("/api/ds/query"):
                try:
                    return json.loads(detail)  # 쿼리 오류도 results 안에 담겨 온다
                except json.JSONDecodeError:
                    pass
            raise HttpError(f"{method} {path}: HTTP {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise HttpError(f"{method} {path}: {exc.reason}") from exc

    return fetch


def quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def format_value(values: list[str], fmt: str | None, multi: bool) -> str:
    """Grafana SQL 데이터소스가 변수를 끼워 넣는 방식을 따른다."""
    if fmt in ("raw", "csv"):
        return ",".join(values)
    if fmt in ("sqlstring", "singlequote"):
        return ",".join(quote(v) for v in values)
    if fmt == "doublequote":
        return ",".join('"' + v.replace('"', '\\"') + '"' for v in values)
    if multi or len(values) > 1:
        return ",".join(quote(v) for v in values)
    return values[0] if values else ""


def interpolate(sql: str, variables: dict[str, dict], scoped: dict[str, str]) -> str:
    """$var, ${var}, ${var:fmt}, [[var]] 를 바꾼다. $__ 로 시작하는 매크로는 Grafana 가 푼다."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(3) or match.group(5)
        fmt = match.group(2) or match.group(4)
        if name in scoped:  # 반복 패널의 값은 하나로 들어간다(따옴표 없음)
            return format_value([scoped[name]], fmt, multi=False)
        var = variables.get(name)
        if var is None:
            return match.group(0)
        if (
            var.get("raw_all") is not None
        ):  # 사용자가 정한 All 값은 Grafana 가 따옴표 없이 그대로 넣는다
            return var["raw_all"]
        return format_value(var["values"], fmt, var["multi"])

    return VAR_RE.sub(replace, sql)


def ds_query(
    fetch: Fetch, ds: dict, sql: str, span: tuple[str, str], fmt: str = "table"
) -> dict:
    """쿼리 하나를 실행해 {rows, error, first_column} 을 돌려준다."""
    body = {
        "from": span[0],
        "to": span[1],
        "queries": [
            {
                "refId": "A",
                "datasource": {"uid": ds.get("uid"), "type": ds.get("type")},
                "rawSql": sql,
                "rawQuery": True,
                "format": fmt,
                "intervalMs": 60000,
                "maxDataPoints": 500,
            }
        ],
    }
    result = fetch("POST", "/api/ds/query", body).get("results", {}).get("A", {})
    frames = result.get("frames") or []
    rows, first = 0, []
    for frame in frames:
        values = frame.get("data", {}).get("values") or []
        if values:
            rows += len(values[0])
            first.extend(str(v) for v in values[0])
    return {"rows": rows, "error": result.get("error"), "first_column": first}


def resolve_variables(
    fetch: Fetch,
    dashboard: dict,
    default_ds: dict,
    span: tuple[str, str],
    overrides: dict[str, list[str]],
) -> tuple[dict[str, dict], list[dict]]:
    """변수마다 값 목록을 구한다. 앞 변수의 값을 뒤 변수 쿼리에 넣으며 순서대로 푼다."""
    variables: dict[str, dict] = {}
    report = []
    for var in dashboard.get("templating", {}).get("list", []):
        name, kind = var.get("name"), var.get("type")
        multi = bool(var.get("multi") or var.get("includeAll"))
        error, raw_all = None, None
        current = var.get("current", {}).get("value")
        current = (
            current
            if isinstance(current, list)
            else ([current] if current not in (None, "") else [])
        )
        selected_all = not current or "$__all" in current
        if name in overrides:
            values = overrides[name]
        elif kind == "query":
            ds = var.get("datasource") or default_ds
            query = var.get("query")
            sql = (
                query.get("rawSql") or query.get("query")
                if isinstance(query, dict)
                else str(query or "")
            )
            result = ds_query(fetch, ds, interpolate(sql, variables, {}), span)
            error = result["error"]
            values = sorted(set(result["first_column"]))
            if (
                not selected_all
            ):  # 대시보드에 저장된 선택값(사용자가 처음 보는 화면)을 쓴다
                values = [v for v in values if v in current] or [
                    str(v) for v in current
                ]
            elif var.get("includeAll") and var.get("allValue"):
                raw_all = str(var["allValue"])
        elif kind == "custom":
            values = [
                o.get("value")
                for o in var.get("options", [])
                if o.get("value") != "$__all"
            ] or [v.strip() for v in str(var.get("query", "")).split(",") if v.strip()]
        else:
            current = var.get("current", {}).get("value", var.get("query", ""))
            values = current if isinstance(current, list) else [str(current)]
        variables[name] = {
            "values": [str(v) for v in values],
            "multi": multi,
            "raw_all": raw_all,
        }
        report.append(
            {
                "variable": name,
                "values": "All(사용자 값)" if raw_all else len(values),
                "error": error,
            }
        )
    return variables, report


def iter_panels(panels: list[dict]):
    for panel in panels:
        yield panel
        yield from iter_panels(panel.get("panels", []))


def check(
    fetch: Fetch,
    uid: str,
    span: tuple[str, str],
    overrides: dict[str, list[str]],
    max_repeat: int,
) -> dict:
    data = fetch("GET", f"/api/dashboards/uid/{uid}", None)
    dashboard, meta = data["dashboard"], data.get("meta", {})
    default_ds = next(
        (
            p.get("datasource")
            for p in iter_panels(dashboard.get("panels", []))
            if isinstance(p.get("datasource"), dict)
        ),
        {},
    )
    variables, var_report = resolve_variables(
        fetch, dashboard, default_ds, span, overrides
    )
    results = []
    for panel in iter_panels(dashboard.get("panels", [])):
        targets = [t for t in panel.get("targets", []) if t.get("rawSql")]
        if panel.get("type") == "row" or not targets:
            continue
        repeat = panel.get("repeat")
        scopes = [{}]
        if repeat and repeat in variables:
            scopes = [{repeat: v} for v in variables[repeat]["values"][:max_repeat]]
        for scope in scopes:
            for target in targets:
                ds = target.get("datasource") or panel.get("datasource") or default_ds
                if (
                    not isinstance(ds, dict)
                    or ds.get("uid") in SKIP_DS
                    or str(ds.get("uid", "")).startswith("$")
                ):
                    results.append(
                        {
                            "panel": panel.get("title"),
                            "status": "skipped",
                            "reason": "데이터소스를 풀 수 없다",
                        }
                    )
                    continue
                sql = interpolate(target["rawSql"], variables, scope)
                out = ds_query(fetch, ds, sql, span, target.get("format", "table"))
                status = (
                    "error" if out["error"] else ("empty" if out["rows"] == 0 else "ok")
                )
                entry = {
                    "panel": interpolate(str(panel.get("title", "")), variables, scope),
                    "type": panel.get("type"),
                    "ref": target.get("refId"),
                    "status": status,
                    "rows": out["rows"],
                }
                if scope:
                    entry["repeat"] = scope
                if out["error"]:
                    entry["error"] = str(out["error"])[:400]
                    entry["sql"] = sql[:400]
                results.append(entry)
    counts = {
        s: sum(r["status"] == s for r in results)
        for s in ("ok", "empty", "error", "skipped")
    }
    return {
        "dashboard": dashboard.get("title"),
        "uid": uid,
        "version": dashboard.get("version"),
        "updated": meta.get("updated"),
        "variables": var_report,
        "counts": counts,
        "panels": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Grafana 대시보드의 모든 패널 쿼리를 실제로 실행해 오류·빈 결과를 찾는다.",
        epilog=(
            "예:\n"
            "  GRAFANA_USER=admin GRAFANA_PASSWORD=... python3 panel_check.py --url http://127.0.0.1:3000 --uid my-dash\n"
            "  ssh <호스트> 'GRAFANA_URL=... GRAFANA_USER=... GRAFANA_PASSWORD=... python3 - --uid my-dash' < panel_check.py\n"
            "  python3 panel_check.py --uid my-dash --wait-contains 'state-timeline' --wait 180\n"
            '  python3 panel_check.py --uid my-dash --url http://<Grafana> --admin-secret monitoring/grafana-admin --kubectl "ssh cp kubectl"\n\n'
            '출력: {"dashboard", "version", "updated", "variables": [...], "counts": {ok, empty, error, skipped},\n'
            '       "panels": [{panel, type, status: ok|empty|error|skipped, rows, error?, sql?, repeat?}]}\n'
            "exit code: 0 오류 없음(빈 결과는 --fail-empty 일 때만 실패), 1 오류 또는 빈 결과,\n"
            "           2 사용법 오류, 3 Grafana 접속·인증 실패"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--uid", required=True, help="대시보드 uid")
    parser.add_argument(
        "--admin-secret", metavar="NS/NAME",
        help="관리자 자격 증명 시크릿(키 admin-user, admin-password). 주면 --kubectl 로 읽는다. 값은 출력하지 않는다",
    )  # fmt: skip
    parser.add_argument("--kubectl", default="kubectl", metavar="CMD",
                        help='--admin-secret 을 읽을 kubectl 실행 명령 (기본 kubectl). 예: "ssh cp kubectl"')  # fmt: skip
    parser.add_argument(
        "--url",
        default=os.environ.get("GRAFANA_URL", "http://127.0.0.1:3000"),
        help="Grafana 주소",
    )
    parser.add_argument(
        "--from", dest="start", default="now-24h", help="시간 범위 시작 (기본 now-24h)"
    )
    parser.add_argument("--to", default="now", help="시간 범위 끝 (기본 now)")
    parser.add_argument(
        "--var",
        action="append",
        default=[],
        metavar="NAME=V1,V2",
        help="변수 값을 정한다",
    )
    parser.add_argument(
        "--max-repeat",
        type=int,
        default=50,
        help="반복 패널을 펼칠 최대 값 수 (기본 50)",
    )
    parser.add_argument(
        "--fail-empty", action="store_true", help="빈 결과도 실패로 본다"
    )
    parser.add_argument(
        "--wait-contains",
        metavar="TEXT",
        help="대시보드 JSON 에 TEXT 가 나타날 때까지 기다린다(배포 반영 확인)",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=120,
        help="--wait-contains 의 최대 대기 초 (기본 120)",
    )
    parser.add_argument(
        "--timeout", type=int, default=60, help="요청 하나의 제한 시간 초 (기본 60)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        overrides = {
            k: v.split(",") for k, _, v in (item.partition("=") for item in args.var)
        }
    except ValueError:
        print("오류: --var 는 NAME=V1,V2 형식이다", file=sys.stderr)
        return EXIT_USAGE
    if args.admin_secret and not os.environ.get("GRAFANA_TOKEN"):
        try:
            load_admin_secret(args.kubectl, args.admin_secret)
        except (HttpError, OSError, subprocess.SubprocessError) as exc:
            print(f"오류: {exc}", file=sys.stderr)
            return EXIT_HTTP
    fetch = make_fetch(args.url, args.timeout)
    try:
        if args.wait_contains:
            deadline = time.monotonic() + args.wait
            while args.wait_contains not in json.dumps(
                fetch("GET", f"/api/dashboards/uid/{args.uid}", None)
            ):
                if time.monotonic() > deadline:
                    print(
                        f"오류: {args.wait}초 안에 '{args.wait_contains}' 가 대시보드에 나타나지 않았다",
                        file=sys.stderr,
                    )
                    return EXIT_FAILED
                time.sleep(5)
        report = check(
            fetch, args.uid, (args.start, args.to), overrides, args.max_repeat
        )
    except HttpError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return EXIT_HTTP
    counts = report["counts"]
    report["ok"] = counts["error"] == 0 and not (args.fail_empty and counts["empty"])
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    print(
        f"ok={counts['ok']} empty={counts['empty']} error={counts['error']} skipped={counts['skipped']}",
        file=sys.stderr,
    )
    return EXIT_OK if report["ok"] else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
