# agent-skills

저장소를 가리지 않고 공통으로 쓰는 개인 에이전트 스킬 모음. 각 스킬은
[Agent Skills](https://agentskills.io) 표준의 `skills/<이름>/SKILL.md` 형식이다.

| 스킬 | 용도 |
| :--- | :--- |
| `commit` | Conventional Commits 기반 커밋 메시지 작성 규칙 |
| `skill-authoring` | 표준·공급자 중립 방식으로 스킬을 만들고 고치는 절차, 검사 스크립트 |
| `python-dev` | 공식 문서 기준 파이썬 스크립트·프로젝트·테스트 작성 규칙 |
| `env-onboarding` | PC 별 환경 정보 파일(`~/.agents/environment.md`) 생성·점검 |
| `gitops-change` | Argo CD 등 GitOps 클러스터 변경: 렌더링·dry-run, 동기화 대기(`argo_wait.py`), 동작 확인, 문서 동반 수정 |
| `grafana-dashboard` | Grafana 대시보드 수정과 모든 패널 쿼리 실행 검사(`panel_check.py`) |
| `home-assistant-ops` | Home Assistant 레지스트리·통합을 UI 대신 API 로 처리(`ha_ws.py`) |

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

### 새 PC 에서

스킬을 설치한 뒤 에이전트에게 "환경 온보딩 해 줘"라고 한다. `env-onboarding` 이 서버·접속 경로·저장소 정보를
감지하고 모르는 것만 물어 `~/.agents/environment.md` 를 만든다. 이 파일은 git 에 올리지 않는다. 다른 PC 로
옮길 때는 이 파일만 복사하고 다시 온보딩을 실행해 점검한다.

## 스킬 추가

`skill-authoring` 스킬의 절차를 따른다. 저장소 규칙과 검사 명령은 [AGENTS.md](AGENTS.md) 에 있다.
