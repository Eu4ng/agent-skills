---
name: gitops-change
description: Argo CD 같은 GitOps 도구가 관리하는 쿠버네티스 클러스터의 설정을 바꿀 때 쓴다. GitOps 저장소의 파일을 고치거나 클러스터 문제를 조사하기 전에는 작업이 간단해도 먼저 이 스킬을 켠다. 서비스 추가·수정·삭제, 매니페스트·kustomize·Helm values 변경, 동기화가 안 되거나 파드가 안 뜨는 문제 해결, GitOps 밖에서 만드는 시크릿 준비가 해당하고, 사용자가 "클러스터에 올려 줘", "설정 바꿔 줘"라고만 해도 대상이 GitOps 저장소면 쓴다. 변경 전 렌더링·서버 dry-run, push 뒤 커밋 반영·Synced/Healthy 대기, 롤아웃과 실제 동작 확인, 관련 문서 동반 수정 절차를 담고 있다. GitOps 로 관리하지 않는 서버나 VM 의 설정 변경에는 쓰지 않는다.
---

# GitOps 변경

클러스터 상태의 원본은 GitOps 저장소다. 동기화 도구가 selfHeal·prune 으로 저장소와 다른 상태를 되돌린다. 그래서
`kubectl apply`·`edit` 로 고친 것은 곧 사라지고, 저장소에서 지운 리소스는 클러스터에서도 지워진다. 변경은 항상
저장소를 고쳐 push 하고, 동기화가 끝나 실제로 동작하는 것을 확인한 뒤에 보고한다.
아래 `scripts/` 경로는 이 스킬 폴더 기준이다.

## 환경 정보

`~/.agents/environment.md` 의 `## 클러스터`(kubectl 실행 명령, GitOps 저장소), `## 저장소`, `## 시크릿 위치`,
`## 작업 정책` 절을 읽는다. 파일이 없거나 항목이 비어 있으면 먼저 접근 가능한 곳(설정 파일, 서버, 저장소)을 조사하고,
그래도 모르는 것만 사용자에게 묻는다. 알아낸 값은 그 파일의 해당 절에 적은 뒤 진행한다. 비밀값 자체는 적지 않는다.

## 빠른 절차

1. **환경 정보를 읽는다.** `cat ~/.agents/environment.md` 를 실행해 읽는다(있는지 사용자에게 묻지 않는다). 경로는 홈 폴더 아래 `.agents` 폴더 안이다. 읽기에 실패하면 경로를 다시 확인하고 `ls -a ~/.agents` 로 찾는다.
   그 파일에서 kubectl 실행 명령(예: `ssh cp kubectl`), GitOps 저장소, 시크릿 위치를 확인한다.
2. **저장소 규칙을 읽는다.** 대상 GitOps 저장소의 AGENTS.md·README 에서 폴더 구조(폴더 = 앱 = 네임스페이스 등),
   커밋 규칙, 관련 문서 위치를 확인한다.
3. **저장소를 고친다.** 클러스터를 직접 고치지 않는다. 같은 종류의 설정이 여러 곳에 있으면(여러 사이트 오버레이,
   여러 서비스) 전부 찾아 함께 고친다.
4. **push 전에 렌더링하고 서버 dry-run 을 한다.** 로컬에 kubectl·kustomize·helm 이 없으면 폴더를 묶어 kubectl 이
   있는 호스트로 보내 확인한다.

   ```bash
   tar -C <저장소> -czf - <바꾼 폴더> | ssh <kubectl 호스트> \
     'd=$(mktemp -d); tar -xzf - -C $d; kubectl kustomize $d/<바꾼 폴더> | kubectl apply --dry-run=server -f -; rm -rf $d'
   ```

   Helm 차트 폴더는 `helm dependency build && helm template <이름> . -n <네임스페이스>` 로 렌더링한다.
5. **커밋하고 push 한다.**
6. **동기화를 기다린다.** push 한 커밋 SHA 로 아래 명령을 실행해 출력의 `ready` 가 `true` 가 될 때까지 기다린다.
   동기화 도구는 몇 분 간격으로 저장소를 보므로, push 직후의 클러스터는 아직 옛 상태다. **`ready: true` 를 보기 전에는
   끝났다고 보고하지 않는다.**

   ```bash
   python3 <이 스킬 폴더>/scripts/argo_wait.py <앱 이름> --revision <커밋 SHA> --refresh --timeout 100 \
     --kubectl "<kubectl 실행 명령>"
   ```

   `ready` 가 `false` 로 끝나면(시간 초과 포함) 같은 명령을 다시 실행한다. 사용자에게 기다려 달라고 넘기지 않는다.
   `--kubectl` 에는 환경 정보의 kubectl 실행 명령을 따옴표 없이 그대로 넣는다(예: `--kubectl "ssh cp kubectl"`).

   새 폴더를 더해 앱이 새로 생기는 경우에는 `--appset <ApplicationSet 이름>` 을 붙인다. 앱이 생길 때까지 몇 분 걸릴 수 있다.
7. **실제 동작을 확인한다.** 다음을 모두 확인한다.
   - `kubectl -n <ns> rollout status deploy/<이름> --timeout=300s` (6단계 뒤에 해야 새 설정의 롤아웃을 본다)
   - 바꾼 값이 배포된 리소스에 들어갔는지 직접 본다. 예: `kubectl -n <ns> get deploy <이름> -o jsonpath='{..env}'`
   - 로그에서 기대한 연결·시작 메시지를 확인한다.
   - 서비스를 불러 기대한 응답(HTTP 코드, 데이터)이 오는지 본다.

   Synced·Healthy 는 매니페스트가 적용됐다는 뜻일 뿐, 기능이 동작한다는 뜻은 아니다.
8. **관련 문서를 함께 고친다.** 바꾼 서비스를 설명하는 문서(블로그 글, README, 설치 스크립트 사본)를 찾아 같은
   내용으로 고친다. 사본 파일은 `cmp` 로 원본과 같은지 확인한다. 문서 저장소의 발행 절차(검증 명령, 브랜치)를 따른다.
9. **검증**: 7과 8까지 통과한 뒤에 보고한다. 확인하지 못한 것(화면을 직접 보지 못함 등)은 그렇다고 적는다.

## GitOps 밖의 시크릿

비밀값은 저장소에 넣지 않는다. 시크릿은 다시 실행해도 안전한 스크립트로 만들고, 그 스크립트는 문서 저장소(설치 글)에
둔다. 새 서버에서도 같은 상태를 스크립트와 저장소만으로 재현할 수 있어야 한다.

```bash
# 값은 화면에 보이지 않게 받고, 파이프로 넘겨 인자·기록에 남기지 않는다
read -rsp "토큰: " T; echo; [ -n "$T" ] || { echo "빈 값"; exit 1; }
printf '%s' "$T" | kubectl -n <ns> create secret generic <이름> --from-file=<키>=/dev/stdin \
  --dry-run=client -o yaml | kubectl apply -f -
unset T
```

에이전트가 값을 알아야 하면 사용자에게 묻기 전에 `## 시크릿 위치` 의 시크릿에서 꺼내 명령 안에서만 쓴다. 값을 출력하지 않는다.

## 문제 해결

| 증상 | 볼 곳 |
| :--- | :--- |
| 동기화 실패·OutOfSync 가 계속됨 | `kubectl -n argocd get app <앱> -o jsonpath='{range .status.conditions[*]}{.type}: {.message}{"\n"}{end}'`, 리소스별 상태 `{range .status.resources[*]}{.kind} {.name} {.status} {.health.status}{"\n"}{end}` |
| 렌더링 오류 | `kubectl -n argocd logs deploy/argocd-repo-server --since=10m` |
| 파드가 안 뜸 | `kubectl -n <ns> get events --sort-by=.lastTimestamp \| tail -20`, `kubectl -n <ns> logs deploy/<이름> --previous` |

## 주의

- 동기화 도구는 몇 분 간격으로 저장소를 확인한다. push 직후에 보면 옛 상태가 보인다. 커밋 SHA 가 반영된 것을
  확인하기 전에는 결과를 보고하지 않는다. `--refresh` 로 앞당길 수 있다.
- server dry-run 의 "missing last-applied-configuration" 경고는 무해하다.
- 큰 CRD 를 담은 차트(예: 모니터링 스택)는 annotation 한도를 넘어 동기화가 실패한다. 동기화 옵션에
  `ServerSideApply=true` 를 준다.
- Helm 차트 values 에 차트 스키마가 모르는 최상위 키를 넣으면 "additional properties ... not allowed" 로 실패한다.
- hostPort 를 쓰는 DaemonSet·Deployment 는 롤링 업데이트에 `maxSurge: 0` 이 필요하다. 새 파드가 같은 포트를
  잡지 못한다.
- 동기화 도구는 직접 만든 EndpointSlice 를 무시하기도 한다. 클러스터 밖 주소를 가리킬 때는 ExternalName Service 를 쓴다.
- DB 파드 안에서 실행한 셸을 강제로 죽이면 DB 프로세스가 복구를 반복할 수 있다. 시험은 별도 파드에서 한다.
- ssh 작은따옴표 안에 SQL·JSON 따옴표를 넣으면 깨진다. 긴 SQL 은 heredoc 으로 넘긴다:
  `ssh <호스트> "kubectl -n <ns> exec -i deploy/<db> -- psql ..." <<'EOF' ... EOF`

## 스크립트

- `scripts/argo_wait.py`: 앱들이 지정한 커밋으로 Synced·Healthy 가 될 때까지 기다리고 결과를 JSON 으로 낸다.
  작업 PC 에서 `--kubectl "<kubectl 실행 명령>"` 으로 부른다. 표준 라이브러리만 쓴다. `--help` 참고.

## 하지 않는 것

- 클러스터 리소스를 `kubectl apply`·`edit`·`patch` 로 직접 고치지 않는다(조사용 dry-run 은 괜찮다).
- 비밀값을 저장소·로그·보고에 남기지 않는다.
- 리소스 삭제, 노드 drain, 강제 push 는 `## 작업 정책` 에 따라 사용자 확인을 받는다.
- 백업·복원으로 상태를 옮기지 않는다. 저장소와 스크립트로 재현한다.
