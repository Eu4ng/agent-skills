---
name: k8s-node-maintenance
description: 쿠버네티스 노드를 drain·재시작하거나, 노드 VM 의 메모리·코어를 바꾸거나, 노드를 새 노드로 교체·제거할 때 쓴다. "워커 메모리 줄여", "노드 하나 재부팅해야 해", "옛 노드 빼고 새 노드로" 처럼 drain 이라는 말이 없어도 노드를 잠시 내리거나 바꾸는 상황에 쓴다. 사전 점검(etcd·DB·볼륨), drain 옵션, 재시작 뒤 복귀 확인, 교체 순서를 담고 있다. 파드 하나의 문제 해결에는 쓰지 않는다.
---

# 쿠버네티스 노드 유지보수

노드를 내리면 그 노드의 파드가 다른 노드로 옮겨지는데, **노드 로컬 디스크(local-path 등)에 묶인 파드는 옮겨지지 않고 노드가 돌아올 때까지 멈춘다.**
그래서 먼저 무엇이 멈추는지 확인하고, 사용자 확인을 받은 뒤 한 번에 한 노드씩 진행한다.

## 환경 정보

`~/.agents/environment.md` 의 `## 클러스터`(kubectl 실행 위치)와 `## 호스트`(노드와 VM, 플레이북 저장소) 절을 직접 열어 읽는다(있는지 사용자에게
묻지 않는다). 파일이 없거나 필요한 항목이 비어 있으면 먼저 접근 가능한 곳(설정 파일, 서버, 저장소)을 조사하고, 그래도 모르는 것만
사용자에게 묻는다. 알아낸 값은 그 파일의 해당 절에 적은 뒤 진행한다. 비밀값 자체는 적지 않고 값이 있는 위치만 적는다.

## 절차

1. **환경 정보를 읽는다**: kubectl 을 실행할 곳과 노드를 만드는 플레이북을 확인한다.
2. **영향을 본다**:

   ```bash
   kubectl get pods -A -o wide --field-selector spec.nodeName=<노드>
   kubectl get pv -o custom-columns=NAME:.metadata.name,CLAIM:.spec.claimRef.name,NODE:.spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].values[0] | grep <노드>
   ```

   - local-path 등 노드 고정 볼륨을 쓰는 파드 → 노드가 돌아올 때까지 멈춘다(목록을 사용자에게 알린다).
   - control plane 이면 etcd 과반이 유지되는지 확인한다: 멤버 수와 건강 상태(`etcdctl member list`, `endpoint health`).
   - DB 클러스터(Patroni 등) 멤버가 있으면 주 DB 가 그 노드에 있는지 보고, 있으면 먼저 다른 멤버로 넘긴다(switchover).
   - 복제 볼륨(Longhorn 등)은 모든 볼륨이 healthy 인지 본다(복제본이 하나뿐인 볼륨은 그 노드와 함께 멈춘다).
3. **사용자 확인을 받는다**: 멈추는 서비스와 예상 시간을 알리고 확인받는다.
4. **drain 한다**:

   ```bash
   kubectl drain <노드> --ignore-daemonsets --delete-emptydir-data --timeout=300s
   ```

   PodDisruptionBudget 때문에 멈추면 어떤 파드인지 보고 원인을 해결한다(`--disable-eviction` 으로 우회하지 않는다).
5. **작업한다**: VM 종료 → 플레이북 변수 변경·적용(메모리·코어는 VM 을 끈 상태에서 적용하고 플레이북이 다시 시작) → 노드 Ready 대기.

   ```bash
   kubectl wait --for=condition=Ready node/<노드> --timeout=300s
   kubectl uncordon <노드>
   ```

6. **노드 교체**(새 이름으로 바꿀 때): 새 노드를 플레이북 목록에 더해 합류시킨다 → 새 노드 Ready·볼륨 복제 완료 확인 → 옛 노드를 drain →
   플레이북의 제거 절차(예: `retire` 표시)로 `kubeadm reset`·노드 삭제·VM 삭제. 노드 고정 볼륨의 데이터는 지우기 전에 새 곳으로 복사한다
   (다시 받으면 되는 캐시도 복사가 더 빠르고, 사용자는 다시 받는 것을 원하지 않을 수 있다).
7. **검증**: 모든 노드 Ready, 비정상 파드 0(`kubectl get pods -A | grep -vE 'Running|Completed'`), GitOps 앱 전부 Synced·Healthy,
   DB 클러스터 멤버·복제 지연, 볼륨 healthy 를 확인하고 보고한다.

## 주의

- VM 에 메모리 벌루닝이 꺼져 있으면(`balloon: 0`) 메모리를 줄이는 데 재시작이 필요하다.
- DB 멤버를 재시작하면 동기 복제 대상이 다른 멤버로 바뀔 수 있다. 우선순위가 정해져 있어도 자동으로 되돌아오지 않을 수 있으니 결과를 적어 둔다.
- 노드가 돌아온 직후 Prometheus 처럼 기록을 다시 읽는 파드는 잠시 Degraded 로 보인다. 몇 분 기다린 뒤 다시 본다.

## 하지 않는 것

- 확인 없이 drain·재시작·노드 삭제를 하지 않는다.
- 두 노드를 동시에 내리지 않는다.
