"""scripts/ 의 스크립트 테스트. 실행: uvx pytest -q -p no:cacheprovider scripts/test_scripts.py

위반 예시를 일부러 담고 있다. <!-- lint-allow: ip, product, tool, web -->
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lint
import local_eval
import new_skill
import user_messages


def make_skill(
    root: Path, name: str, body: str, description: str = "무언가 할 때 쓴다."
) -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return skill


def lint_json(capsys: pytest.CaptureFixture[str], *paths: Path) -> tuple[int, dict]:
    code = lint.main([str(p) for p in paths])
    return code, json.loads(capsys.readouterr().out)


def test_given_clean_skill_when_lint_then_no_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skill = make_skill(
        tmp_path,
        "good-skill",
        "# 제목\n\n파일을 읽는다.\n\n## 참고\n\n- https://example.org/doc",
    )
    code, out = lint_json(capsys, skill)
    assert code == lint.EXIT_OK
    assert (out["errors"], out["warnings"]) == (0, 0)


@pytest.mark.parametrize(
    ("body", "kind"),
    [
        ("Read 도구로 연다.", "tool"),
        ("서버는 192.168.1.5 이다.", "ip"),
        ("자세한 건 https://example.org 를 본다.", "web"),
        ("Claude 에서 쓴다.", "product"),
    ],
)
def test_given_rule_violation_when_lint_then_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], body: str, kind: str
) -> None:
    code, out = lint_json(capsys, make_skill(tmp_path, "some-skill", body))
    assert code == lint.EXIT_OK
    assert kind in {w["kind"] for w in out["skills"][0]["warnings"]}


def test_given_local_url_when_lint_then_not_web_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, out = lint_json(
        capsys, make_skill(tmp_path, "local-url", "서버: http://127.0.0.1:11434")
    )
    assert out["warnings"] == 0


@pytest.mark.parametrize(
    ("name", "body", "message"),
    [
        ("Bad--Name", "본문", "폴더명"),
        ("todo-left", "TODO(할 일)", "TODO("),
        ("broken-link", "[문서](references/none.md)", "링크 대상이 없다"),
    ],
)
def test_given_error_when_lint_then_exit_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    name: str,
    body: str,
    message: str,
) -> None:
    code, out = lint_json(
        capsys,
        make_skill(tmp_path, name.lower().replace("--", "-"), body).rename(
            tmp_path / name
        ),
    )
    assert code == lint.EXIT_ERRORS
    assert any(message in e["message"] for e in out["skills"][0]["errors"])


def test_given_relative_dot_path_when_lint_then_uses_real_folder_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    skill = make_skill(tmp_path, "dot-path", "본문")
    monkeypatch.chdir(skill)
    code, _ = lint_json(capsys, Path("."))
    assert code == lint.EXIT_OK


def test_given_new_name_when_new_skill_then_template_passes_only_todo_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert new_skill.main([str(tmp_path), "release-tagging"]) == new_skill.EXIT_OK
    created = json.loads(capsys.readouterr().out)
    text = Path(created["skill_md"]).read_text(encoding="utf-8")
    assert "name: release-tagging" in text
    assert created["todo"] > 0
    _, out = lint_json(capsys, tmp_path / "release-tagging")
    assert all("TODO(" in e["message"] for e in out["skills"][0]["errors"])


def test_given_existing_skill_when_new_skill_then_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_skill(tmp_path, "exists", "본문")
    assert new_skill.main([str(tmp_path), "exists"]) == new_skill.EXIT_EXISTS
    assert new_skill.main([str(tmp_path), "Bad_Name"]) == new_skill.EXIT_USAGE


def test_user_messages_skips_tool_results_and_injected_text(tmp_path: Path) -> None:
    log = tmp_path / "s.jsonl"
    rows = [
        {"type": "user", "message": {"role": "user", "content": "첫 요청"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "답"}],
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "content": "x"}],
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": "<system-reminder>무시</system-reminder>",
            },
        },
        {
            "type": "user",
            "isMeta": True,
            "message": {"role": "user", "content": "메타"},
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "아니 그게 아니라"}],
            },
        },
    ]
    log.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8"
    )
    texts = [m["text"] for m in user_messages.iter_messages(log, context=True)]
    assert texts == ["첫 요청", "아니 그게 아니라"]


def test_record_replaces_same_model_entry(tmp_path: Path) -> None:
    base = {"model": "m", "api": "ollama", "mode": "trigger"}
    local_eval.record(tmp_path, {**base, "passed": 1})
    local_eval.record(tmp_path, {**base, "passed": 2})
    local_eval.record(tmp_path, {**base, "model": "n", "passed": 3})
    data = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert sorted((r["model"], r["passed"]) for r in data["results"]) == [
        ("m", 2),
        ("n", 3),
    ]


def test_activate_returns_body_folder_and_resources(tmp_path: Path) -> None:
    skill = make_skill(tmp_path, "act", "# 본문")
    (skill / "scripts").mkdir()
    (skill / "scripts" / "x.py").write_text("", encoding="utf-8")
    text = local_eval.activate("act", skill)
    assert "name: act" not in text
    assert (
        "# 본문" in text and str(skill) in text and "<file>scripts/x.py</file>" in text
    )


def test_sandbox_refuses_write_outside_and_maps_skill_name_call(tmp_path: Path) -> None:
    skill = make_skill(tmp_path / "skills", "act", "# 본문")
    box = local_eval.Sandbox(
        tmp_path / "work",
        tmp_path / "home",
        False,
        5,
        [{"name": "act", "location": str(skill / "SKILL.md")}],
    )
    (tmp_path / "work").mkdir()
    output, _ = box.call(
        "write_file", {"path": str(tmp_path / "elsewhere.txt"), "content": "x"}
    )
    assert output.startswith("오류")
    output, _ = box.call("act", {})
    assert "<skill_content" in output and box.activated == ["act"]


def test_behavior_checks_cover_skill_commands_and_asking() -> None:
    case = {
        "expect_skill": "a",
        "expect_commands": [r"detect\.py", r"lint"],
        "expect_ask": True,
    }
    result = {
        "skills_read": ["a"],
        "commands": [{"command": "python3 scripts/detect.py"}],
        "asked": [],
    }
    passed = [c["pass"] for c in local_eval.behavior_checks(case, result)]
    assert passed == [True, True, False, False]


def test_record_keeps_entries_from_parallel_writers(tmp_path: Path) -> None:
    import threading

    def write(model: str) -> None:
        local_eval.record(tmp_path, {"model": model, "api": "ollama", "mode": "run"})

    threads = [threading.Thread(target=write, args=(f"m{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    data = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert sorted(r["model"] for r in data["results"]) == [f"m{i}" for i in range(8)]


def test_behavior_checks_count_questions_in_final_answer() -> None:
    case = {"expect_ask": True}
    result = {
        "skills_read": [],
        "commands": [],
        "asked": [],
        "final": "서버 주소를 알려주세요",
    }
    assert [c["pass"] for c in local_eval.behavior_checks(case, result)] == [True]
    result["final"] = "파일을 만들었다."
    assert [c["pass"] for c in local_eval.behavior_checks(case, result)] == [False]


def test_behavior_checks_expect_and_reject_final() -> None:
    case = {
        "expect_final": [r"panel_check"],
        "reject_final": [r"kubectl apply(?!.*dry-run)"],
    }
    good = {
        "skills_read": [],
        "commands": [],
        "asked": [],
        "final": "python3 panel_check.py; kubectl apply --dry-run=server",
    }
    bad = {
        "skills_read": [],
        "commands": [],
        "asked": [],
        "final": "kubectl apply -f x.yaml",
    }
    assert [c["pass"] for c in local_eval.behavior_checks(case, good)] == [True, True]
    assert [c["pass"] for c in local_eval.behavior_checks(case, bad)] == [False, False]


def test_trigger_accepts_any_of_listed_skills() -> None:
    class FakeClient:
        def __init__(self, answers: list[str]) -> None:
            self.answers = iter(answers)

        def chat(self, messages: list[dict], tools: list | None = None) -> dict:
            return {"content": json.dumps({"skill": next(self.answers)})}

    skills = [{"name": n, "description": "d", "location": "x"} for n in ("a", "b")]
    queries = [{"query": "q1", "expect": ["a", "b"]}, {"query": "q2", "expect": None}]
    report = local_eval.run_trigger(
        FakeClient(["b", "a", "b", "none", "a", "none"]), skills, queries, 3
    )
    assert [r["pass"] for r in report["results"]] == [True, True]
    assert report["results"][0]["expect"] == "a | b"


def test_report_marks_current_version(tmp_path: Path) -> None:
    skill = make_skill(tmp_path, "rep", "# 본문")
    (skill / "evals").mkdir()
    local_eval.record(
        skill / "evals",
        {"model": "m", "api": "ollama", "mode": "trigger", "passed": 3, "total": 4},
    )
    table = local_eval.report([skill])
    assert "| rep | trigger | m | 끔 | 3/4 | - |" in table and table.rstrip().endswith(
        "| 예 |"
    )
    (skill / "SKILL.md").write_text(
        "---\nname: rep\ndescription: 바뀜.\n---\n", encoding="utf-8"
    )
    assert local_eval.report([skill]).rstrip().endswith("| 아니오 |")
