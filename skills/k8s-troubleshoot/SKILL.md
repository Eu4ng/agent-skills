---
name: k8s-troubleshoot
description: 쿠버네티스에서 파드가 안 뜨거나(Pending, CrashLoopBackOff, ImagePullBackOff, CreateContainerConfigError), 앱이 Degraded 이거나, 서비스에 연결이 안 되거나 간헐적으로 끊길 때 원인을 찾을 때 쓴다. "왜 안 떠", "접속이 가끔 끊겨", "Degraded 떠" 처럼 증상만 말해도 쓴다. 증상별 확인 순서와 명령, 흔한 원인(Secret 누락, 볼륨 미결합, 가상 IP 충돌, 프록시 신뢰 설정)을 담고 있다. 설정을 새로 바꾸는 작업 자체에는 쓰지 않는다.
---

# 쿠버네티스 문제 해결

추측으로 고치지 않는다. **이벤트·로그·실제 상태에서 오류 문장을 먼저 찾고**, 원인이 확인된 것만 고친다. 고치는 것은 GitOps 저장소나
그 리소스를 만드는 스크립트이고, 클러스터를 직접 고치지 않는다(동기화가 되돌린다).

## 환경 정보

`~/.agents/environment.md` 의 `## 클러스터`(kubectl 실행 위치, 클러스터별 kubeconfig)와 `## 시크릿 위치` 절을 직접 열어 읽는다(있는지 사용자에게
묻지 않는다). 파일이 없거나 필요한 항목이 비어 있으면 먼저 접근 가능한 곳(설정 파일, 서버, 저장소)을 조사하고, 그래도 모르는 것만
사용자에게 묻는다. 알아낸 값은 그 파일의 해당 절에 적은 뒤 진행한다. 비밀값 자체는 적지 않고 값이 있는 위치만 적는다.

## 절차

1. **환경 정보를 읽고 대상 클러스터를 정한다**.
2. **상태와 이벤트를 본다**:

   ```bash
   kubectl -n <ns> get pods -o wide
   kubectl -n <ns> get events --sort-by=.lastTimestamp | tail -15
   kubectl -n <ns> describe pod <파드> | sed -n '/Events:/,$p'
   kubectl -n <ns> logs <파드> --all-containers --tail=50      # 재시작했으면 --previous
   ```

3. **증상별로 확인한다**:

   | 증상 | 확인 | 흔한 원인 |
   | :--- | :--- | :--- |
   | `CreateContainerConfigError`, `secret ... not found`, `FailedMount ... secret` | `kubectl -n <ns> get secret` | GitOps 밖에서 만드는 Secret 이 새 클러스터·네임스페이스에 없음 → 그 Secret 을 만드는 스크립트를 다시 실행 |
   | `ImagePullBackOff`, `401 Unauthorized` | 이벤트의 이미지 이름 | 비공개 레지스트리 pull Secret 누락 |
   | `Pending`, `unbound immediate PersistentVolumeClaims` | `kubectl -n <ns> get pvc`, 스토리지 드라이버 파드 | 스토리지 클래스·용량·노드 고정 볼륨의 노드가 없음 |
   | `Pending`, affinity/taint | `describe` 의 `FailedScheduling` 문장 | podAffinity 대상이 없음, 노드 자원 부족 |
   | 앱 `Degraded` 인데 파드는 Running | `kubectl -n <ns> get pods` 의 READY 칸, GitOps 앱의 리소스별 상태 | 준비 상태 검사 실패, 막 재시작해 기록을 다시 읽는 중 |
   | 서비스 연결 안 됨 | `kubectl -n <ns> get endpointslices -l kubernetes.io/service-name=<svc>` | selector 가 파드 라벨과 다름, 파드 not ready |
   | 가상 IP 로 가끔 끊김(`Connection reset`) | 모든 노드에서 `ip -4 addr show <인터페이스> \| grep <VIP>` | 같은 IP 가 두 노드에 붙음(ARP 충돌). 여러 서비스가 한 IP 를 쓰면서 서비스마다 리더를 뽑는 설정 |
   | 프록시 뒤 앱이 400, `untrusted proxy` | 앱 로그의 거부된 주소 | 서비스 VIP·kube-proxy SNAT 로 요청 출처가 노드 주소로 바뀜 → 앱의 신뢰 프록시 목록을 실제 출처로 |
   | 파드 안 이름 해석 실패 | `kubectl run dnstest --rm -i --restart=Never --image=busybox -- nslookup <이름>` | 노드의 DNS 서버·검색 도메인 |

4. **재현한다**: 짧은 연결을 여러 번 보내 간헐적인 문제를 재현한다(한 번 성공으로 판단하지 않는다). 다른 경로(포트 포워딩)와 비교하면
   네트워크 경로 문제인지 앱 문제인지 나뉜다:

   ```bash
   kubectl -n <ns> port-forward deploy/<앱> 18080:<포트> &
   ```

5. **고치고 검증한다**: 원인 쪽(GitOps 저장소, Secret 스크립트, 노드 설정 플레이북)을 고쳐 적용한 뒤, 같은 재현 방법으로 여러 번 통과하는지
   확인하고 보고한다.

## 주의

- 새 클러스터로 옮기면 Secret 은 따라오지 않는다. 옮긴 뒤 앱이 뜨지 않으면 Secret 부터 본다.
- 준비 상태 검사를 TCP 로 걸면 요청 없는 연결이 앱 로그에 오류(`<BADREQ>` 등)로 남는다. HTTP 검사로 바꾼다.
- 클러스터 직접 수정(`kubectl edit/patch`)은 조사용으로도 하지 않는다. 동기화가 되돌리고, 원인을 가린다.

## 하지 않는 것

- 오류 문장을 확인하지 않고 추측으로 고치지 않는다.
- 파드를 반복해서 지워 "고쳐지기"를 기다리지 않는다.
