# 환경 정보

갱신: 2026-01-01

## 이 PC

- 이름·역할: 작업용 컨테이너. kubectl 없음 → 컨트롤플레인에 ssh 해서 실행한다.
- ssh 키: `~/.ssh/id_ed25519`

## 호스트

| 이름 | 주소 | 접속(ssh 대상) | 역할 |
| :--- | :--- | :--- | :--- |
| cp | 192.0.2.10 | `admin@192.0.2.10` | 허브 k8s 컨트롤플레인 |
| edge | 192.0.2.20 | `admin@192.0.2.20` | 엣지 k3s |

## 클러스터

| 클러스터 | kubectl 실행 명령 | 비고 |
| :--- | :--- | :--- |
| 허브 | `ssh admin@192.0.2.10 kubectl` | Argo CD 가 `~/src/gitops` 를 selfHeal+prune 으로 동기화. 폴더 `services/<이름>/` = 앱 = 네임스페이스 |
| 엣지 | `ssh admin@192.0.2.10 kubectl --kubeconfig /home/admin/edge.yaml` | 허브 Argo CD 가 `sites/edge/` 를 동기화 |

명령 뒤에 kubectl 인자를 붙여 쓴다(예: `ssh admin@192.0.2.10 kubectl get pods`). 스크립트의 `--kubectl` 옵션에는 이 명령을 그대로 넣는다.

## 서비스

| 서비스 | 접근 | 비고 |
| :--- | :--- | :--- |
| Grafana | 컨트롤플레인에서 `http://127.0.0.1:30082` | 관리자: 허브 `monitoring/grafana-admin` 의 `admin-user`, `admin-password`. 대시보드 원본 `~/src/gitops/services/monitoring/dashboards/*.json`, uid `home-records` |
| Home Assistant(엣지) | 엣지 `home-assistant` 네임스페이스 `deploy/home-assistant`, 컨테이너 `home-assistant` | 이름 규칙 문서 `~/src/gitops/README.md` |

## 시크릿 위치

| 용도 | 위치 |
| :--- | :--- |
| HA 장기 액세스 토큰 | 엣지 `home-assistant/ha-api-token` 의 `token` |
| Grafana 관리자 | 허브 `monitoring/grafana-admin` |

## 저장소

| 경로 | 역할 |
| :--- | :--- |
| `~/src/gitops` | GitOps 원본. main 에 push |
| `~/src/blog` | 설치 글. 인프라를 바꾸면 관련 글도 고친다 |

## 작업 정책

- 확인받을 작업: 리소스 삭제, 노드 drain, 강제 push
