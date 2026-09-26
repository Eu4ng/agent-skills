# AGENTS.md

저장소를 가리지 않고 쓰는 공용 에이전트 스킬 모음이다. 각 스킬은 [Agent Skills](https://agentskills.io) 표준의
`skills/<이름>/SKILL.md` 폴더이고, 어떤 에이전트 도구·모델에서도 같게 동작하도록 쓴다.

## 스킬 작성·수정

스킬을 새로 만들거나 고칠 때는 [`skills/skill-authoring/SKILL.md`](skills/skill-authoring/SKILL.md) 를 읽고
그 절차를 따른다.

## 공개 저장소 규칙

이 저장소는 공개다.

- 비밀값(토큰, 비밀번호, 키)을 넣지 않는다.
- 개인 인프라 정보(IP, 호스트명, 도메인, 계정, 시크릿 이름)도 넣지 않는다.
- 스킬에 환경 값이 필요하면 각 PC 의 `~/.agents/environment.md` 에서 읽게 한다.

## 검사

스킬을 추가하거나 고친 뒤 저장소 루트에서 실행한다. 오류가 0 이 될 때까지 push 하지 않는다.

```bash
python3 skills/skill-authoring/scripts/lint.py skills/*
for s in skills/*; do uvx --from skills-ref agentskills validate "$s"; done
uvx ruff format --check skills && uvx ruff check skills   # 파이썬 스크립트가 있을 때
claude plugin validate .                                  # 이 명령이 있는 환경에서만
```

스크립트 테스트도 돌린다: `uvx pytest -q -p no:cacheprovider skills/python-dev/assets skills/skill-authoring/scripts`

새로 만들거나 고친 스킬은 저사양 로컬 모델로도 점검한다. 모델 서버·이름은 `~/.agents/environment.md` 의
`## 로컬 LLM` 절에서 읽는다. 트리거는 질의마다 5회 중 과반이 맞아야 하고, 실행 사례는 `checks` 가 모두 통과해야 한다.

```bash
S=skills/skill-authoring/scripts/local_eval.py
python3 $S trigger --skills skills/* --queries skills/*/evals/triggers.json --runs 5 --model <모델>
python3 $S run --skills skills/* --evals skills/<이름>/evals/evals.json --workdir <임시 폴더> --allow-commands --model <모델>
```

## 저장소 구조와 배포

- 스킬을 추가하면 README 의 스킬 표에 한 줄을 넣는다. 배포 매니페스트는 `skills/` 아래를 자동으로 읽는다.
- `.claude-plugin/` 은 기존 배포 채널(플러그인 마켓플레이스) 매니페스트라 유지한다. 그 밖의 도구 전용 파일·폴더나
  심볼릭 링크는 만들지 않는다.
- 커밋 메시지는 Conventional Commits 를 따르고, 제목은 한국어 명사형으로 끝낸다. 검사를 통과하면 `main` 에 커밋하고 push 한다.
