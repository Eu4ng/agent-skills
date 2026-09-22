# agent-skills

저장소를 가리지 않고 공통으로 쓰는 개인 에이전트 스킬 모음. 각 스킬은
[Agent Skills](https://agentskills.io) 표준의 `skills/<이름>/SKILL.md` 형식이다.

| 스킬 | 용도 |
| :--- | :--- |
| `commit` | Conventional Commits 기반 커밋 메시지 작성 규칙 |

## 설치

### Claude Code

이 저장소가 곧 플러그인 마켓플레이스다. 한 번 등록하면 세션 시작 후 자동으로 업데이트를 확인한다.

```bash
claude plugin marketplace add eu4ng/agent-skills
claude plugin install eu4ng-skills@eu4ng
```

수동으로 갱신하려면 `claude plugin update eu4ng-skills@eu4ng`. 스킬은 `/eu4ng-skills:commit` 이름으로 뜬다.

### Codex, Cursor 등 (`.agents/skills` 를 읽는 도구)

```bash
npx skills add eu4ng/agent-skills -g
```

갱신은 `npx skills update`.

## 스킬 추가

`skills/<이름>/SKILL.md` 를 만들고 README 표에 한 줄 추가한다. 매니페스트는 `skills/` 아래를 자동으로 읽으므로
고칠 것이 없다. 커밋 전에 `claude plugin validate .` 로 검사한다.
