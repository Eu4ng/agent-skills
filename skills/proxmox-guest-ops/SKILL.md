---
name: proxmox-guest-ops
description: Proxmox VE 의 VM·LXC 컨테이너(게스트)를 조회하거나, 시작·종료·재시작하거나, 메모리·코어를 바꾸거나, 스냅샷·삭제하거나, 호스트 장치(GPU 등)를 넘길 때 쓴다. "서버 메모리 얼마나 남았어", "그 VM 꺼", "컨테이너에 GPU 붙여" 처럼 Proxmox 라는 말이 없어도 가상 머신·컨테이너를 다루는 상황에 쓴다. 게스트가 있는 노드 찾기, 자원 여유 확인, 클러스터 쿼럼 확인, 파괴적 작업 전 확인 절차를 담고 있다. 게스트 안에서 돌아가는 서비스 설정에는 쓰지 않는다.
---

# Proxmox 게스트 운영

클러스터에서는 `qm`(VM)·`pct`(LXC) 명령을 **게스트가 있는 노드에서** 실행해야 한다. 다른 노드에서 실행하면 "does not exist" 로 실패한다.
게스트를 새로 만들거나 설정을 바꾸는 일은 그 게스트를 만드는 플레이북(코드)을 고쳐 적용한다. 손으로 바꾸면 다음 실행 때 되돌아가거나
새 서버에서 재현되지 않는다.

## 환경 정보

`~/.agents/environment.md` 의 `## 호스트`(Proxmox 노드와 접속 방법, 게스트 목록)와 `## 작업 정책` 절을 직접 열어 읽는다(있는지 사용자에게
묻지 않는다). 파일이 없거나 필요한 항목이 비어 있으면 먼저 접근 가능한 곳(설정 파일, 서버, 저장소)을 조사하고, 그래도 모르는 것만
사용자에게 묻는다. 알아낸 값은 그 파일의 해당 절에 적은 뒤 진행한다. 비밀값 자체는 적지 않고 값이 있는 위치만 적는다.

## 절차

1. **환경 정보를 읽는다**: Proxmox 노드의 ssh 대상과, 게스트를 만드는 플레이북 저장소를 확인한다.
2. **게스트와 노드를 찾는다**(아무 노드에서나):

   ```bash
   pvesh get /cluster/resources --type vm --output-format json \
     | python3 -c "import sys,json; [print(v['vmid'], v['type'], v['name'], v['node'], v['status'], v.get('maxmem',0)//2**20, 'MB') for v in json.load(sys.stdin)]"
   ```

3. **자원 여유를 본다**(메모리를 늘리거나 게스트를 만들기 전):

   ```bash
   free -g | sed -n 2p                     # 게스트가 있을 노드에서. available 을 본다
   qm config <vmid> | grep -E '^(memory|balloon|cores)'
   ```

   `balloon: 0` 인 VM 은 설정한 메모리를 통째로 쥐고 있고, 메모리를 줄이려면 재시작해야 한다. LXC 는 쓰는 만큼만 차지한다.
4. **바꾼다**:
   - 설정 변경(코어·메모리·장치): 플레이북의 변수 파일을 고쳐 적용한다. 재시작이 필요한 변경(balloon 없는 VM 메모리, LXC 장치 추가)은
     아래 순서로 한다: 영향 확인(그 게스트가 쿠버네티스 노드면 먼저 drain) → `qm shutdown <vmid> --timeout 180`(VM) / `pct shutdown <id>`(LXC)
     → 플레이북 실행(설정 적용·시작) → 서비스 복귀 확인.
   - LXC 에 호스트 GPU 넘기기: `pct set <id> --dev0 /dev/dri/renderD128,gid=<렌더 그룹 gid>` 뒤 CT 재시작. 비특권 CT 는 CT 안에서 서비스를
     root 로 돌리면 그룹 매핑 없이 장치를 쓴다.
   - 시작·종료: `qm start|shutdown <vmid>`, `pct start|shutdown <id>`. 강제 종료(`qm stop`)는 shutdown 이 실패했을 때만.
5. **클러스터 상태를 확인한다**(노드 작업 뒤): `pvecm status` 에서 `Quorate: Yes` 와 기대 표 수를 본다. 과반을 잃으면 게스트 설정을 바꿀 수 없다.
6. **검증**: `qm status`/`pct status` 가 기대한 상태인지, 게스트의 서비스가 응답하는지 확인한 뒤 보고한다.

## 주의

- 삭제(`qm destroy`, `pct destroy --purge`), 강제 종료, 운영 중인 게스트의 종료는 사용자 확인을 받고 한다. 삭제 전에 설정(`qm config`)과
  이름·VMID 가 맞는지 다시 본다.
- 측정·시험용 게스트를 임시로 만들었으면 설명(`--description`)에 용도와 삭제 예정을 적고, 끝나면 사용자에게 삭제를 확인받아 지운다.
- 노드 이름을 바꾸거나 클러스터에 넣는 작업은 게스트 설정 파일 위치(`/etc/pve/nodes/<노드>/`)가 바뀐다. 플레이북·스크립트로만 한다.
- 호스트 전력은 RAPL 로 잴 수 있다: `/sys/class/powercap/intel-rapl:0/energy_uj`(마이크로줄, AMD 도 같은 경로). 두 번 읽어 차이를 시간으로 나눈다.

## 하지 않는 것

- 확인 없이 게스트를 지우거나 강제 종료하지 않는다.
- 플레이북이 관리하는 게스트의 설정을 손으로만 바꾸고 끝내지 않는다.
