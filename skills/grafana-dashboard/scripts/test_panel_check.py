"""panel_check.py 테스트. 실행: uvx pytest -q -p no:cacheprovider scripts/test_panel_check.py"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import panel_check as pc

DS = {"uid": "db", "type": "grafana-postgresql-datasource"}


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("site IN ($site)", "site IN ('a','b')"),
        ("site IN (${site:sqlstring})", "site IN ('a','b')"),
        ("x = '${site:csv}'", "x = 'a,b'"),
        ("room IN ($room)", "room IN ('__all__')"),
        ("t > $__timeFilter(time)", "t > $__timeFilter(time)"),
        ("p = $one", "p = solo"),
    ],
)
def test_interpolate_follows_grafana_sql_rules(sql: str, expected: str) -> None:
    variables = {
        "site": {"values": ["a", "b"], "multi": True, "raw_all": None},
        "room": {"values": [], "multi": True, "raw_all": "'__all__'"},
        "one": {"values": ["solo"], "multi": False, "raw_all": None},
    }
    assert pc.interpolate(sql, variables, {}) == expected


def test_repeat_value_is_inserted_without_quotes() -> None:
    variables = {"prop": {"values": ["battery"], "multi": True, "raw_all": None}}
    assert (
        pc.interpolate("property = $prop", variables, {"prop": "battery"})
        == "property = battery"
    )
    assert (
        pc.interpolate("property = ${prop:sqlstring}", variables, {"prop": "battery"})
        == "property = 'battery'"
    )


def fake_fetch(dashboard: dict, rows_for: dict[str, list[str]]):
    """SQL 에 포함된 문자열로 응답을 고른다. 따옴표 없는 battery 는 DB 오류를 흉내 낸다."""

    def fetch(method: str, path: str, body: dict | None = None) -> dict:
        if path.startswith("/api/dashboards/uid/"):
            return {"dashboard": dashboard, "meta": {"updated": "t"}}
        sql = body["queries"][0]["rawSql"]
        if "= battery" in sql:
            return {"results": {"A": {"error": 'column "battery" does not exist'}}}
        for key, values in rows_for.items():
            if key in sql:
                return {"results": {"A": {"frames": [{"data": {"values": [values]}}]}}}
        return {"results": {"A": {"frames": []}}}

    return fetch


def test_check_expands_repeat_and_reports_error_and_empty() -> None:
    dashboard = {
        "title": "d",
        "templating": {
            "list": [
                {
                    "name": "prop",
                    "type": "query",
                    "multi": True,
                    "includeAll": True,
                    "datasource": DS,
                    "query": "SELECT DISTINCT property FROM r",
                    "current": {"value": ["$__all"]},
                }
            ]
        },
        "panels": [
            {"type": "timeseries", "title": "$prop", "repeat": "prop", "datasource": DS,
             "targets": [{"refId": "A", "rawSql": "SELECT v FROM r WHERE property = $prop"}]},
            {"type": "row", "panels": [
                {"type": "table", "title": "빈 표", "datasource": DS, "targets": [{"refId": "A", "rawSql": "SELECT nothing"}]},
            ]},
        ],
    }  # fmt: skip
    fetch = fake_fetch(
        dashboard, {"SELECT DISTINCT property": ["battery", "battery", "temp"]}
    )
    report = pc.check(fetch, "d", ("now-1h", "now"), {}, 10)
    statuses = {(p["panel"], p["status"]) for p in report["panels"]}
    assert ("battery", "error") in statuses
    assert ("빈 표", "empty") in statuses
    error = next(p for p in report["panels"] if p["status"] == "error")
    assert error["raw_sql"] == "SELECT v FROM r WHERE property = $prop"
    assert report["counts"]["error"] == 1
    assert report["variables"] == [{"variable": "prop", "values": 2, "error": None}]


def test_saved_selection_is_used_instead_of_all_values() -> None:
    dashboard = {
        "templating": {
            "list": [
                {"name": "site", "type": "query", "multi": True, "datasource": DS,
                 "query": "SELECT DISTINCT site", "current": {"value": ["b"]}},
            ]
        },
        "panels": [],
    }  # fmt: skip
    fetch = fake_fetch(dashboard, {"SELECT DISTINCT site": ["a", "b"]})
    variables, _ = pc.resolve_variables(fetch, dashboard, DS, ("now-1h", "now"), {})
    assert variables["site"]["values"] == ["b"]


def test_kubectl_argv_ssh_keeps_prefix_for_remote_shell() -> None:
    argv = pc.kubectl_argv(
        "ssh ubuntu@hub kubectl --kubeconfig ~/edge.yaml",
        ["get", "secret", "-o", "jsonpath={.data.a b}"],
    )
    assert argv == [
        "ssh",
        "ubuntu@hub",
        "kubectl --kubeconfig ~/edge.yaml get secret -o 'jsonpath={.data.a b}'",
    ]
    assert pc.kubectl_argv("kubectl", ["get", "x"]) == ["kubectl", "get", "x"]


def test_kubectl_argv_accepts_quoted_remote_command() -> None:
    assert pc.kubectl_argv("ssh cp 'kubectl -n monitoring'", ["get", "x"]) == [
        "ssh",
        "cp",
        "kubectl -n monitoring get x",
    ]
