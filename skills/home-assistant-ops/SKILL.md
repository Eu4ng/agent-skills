---
name: home-assistant-ops
description: Home Assistant 의 기기·엔티티·영역·통합 설정을 바꾸거나 조회할 때 쓴다. HA 설정을 조사하거나 바꾸기 전에는 먼저 이 스킬을 켠다. 기기·엔티티 이름이나 ID 바꾸기, 비활성 엔티티 켜기, 영역 배정, 통합 추가, 원격 HA 잔재 정리, 상태·이력 확인이 해당하고, 사용자가 "HA 에서 이거 바꿔 줘", "기기 추가했어"라고만 해도 쓴다. UI 대신 API·스크립트로 하는 절차, 토큰을 시크릿에서 꺼내 파드 안에서 실행하는 법, dry-run → 실행 → 재확인 순서, 이름 규칙을 따르는 법을 담고 있다. HA 의 배포 매니페스트나 컨테이너 설정만 바꾸는 작업에는 쓰지 않는다.
---

# Home Assistant 운영

**먼저 `cat ~/.agents/environment.md` 를 실행해 읽는다.** kubectl 실행 명령, 네임스페이스, HA 인스턴스·토큰 시크릿 위치가 그 파일에 있다.
이 값들을 사용자에게 묻지 않는다.

사용자는 UI 로 하나씩 누르는 안내보다 한 번에 끝나는 스크립트를 원한다. HA 설정은 WebSocket·REST API 로 바꾸고,
같은 종류의 대상은 전부 한 번에 처리한다. 토큰은 사용자에게 묻지 않는다. 스크립트가 시크릿에서 직접 읽는다.
아래 `scripts/` 경로는 이 스킬 폴더 기준이다.

## 환경 정보

`~/.agents/environment.md` 의 다음 절을 읽는다.

- `## 서비스`: HA 인스턴스 목록, 네임스페이스·배포 이름, 운영 스크립트와 이름 규칙 문서 위치
- `## 시크릿 위치`: HA 장기 액세스 토큰
- `## 클러스터`: kubectl 실행 명령

파일이 없거나 항목이 비어 있으면 먼저 접근 가능한 곳(설정 파일, 서버, 저장소)을 조사하고, 그래도 모르는 것만
사용자에게 묻는다. 알아낸 값은 그 파일의 해당 절에 적은 뒤 진행한다. 비밀값 자체는 적지 않는다.

## 빠른 절차

진단이나 계획만 보고하고 멈추지 않는다. 삭제처럼 확인이 필요한 작업이 아니면 고치기·배포·검증까지 이어서 하고, 끝난 뒤
한 번에 보고한다.

1. **환경 정보를 읽는다.** `cat ~/.agents/environment.md` 를 실행해 읽는다(있는지 사용자에게 묻지 않는다). 경로는 홈 폴더 아래 `.agents` 폴더 안이다. 읽기에 실패하면 경로를 다시 확인하고 `ls -a ~/.agents` 로 찾는다.
   그 파일에서 대상 HA(네임스페이스·배포), 토큰 시크릿 위치, kubectl 실행 명령을 확인한다. 여러 HA(지역별, 중앙)가 있으면 어느 인스턴스를 바꿀지 정한다. 토큰이 있는지
   사용자에게 묻지 않는다.
2. **현재 상태를 본다.** 작업 PC 에서 아래 명령을 그대로 실행한다. 스크립트가 토큰을 시크릿에서 읽어 HA 파드 안에서
   실행하므로 토큰을 직접 꺼낼 필요가 없다. 토큰을 출력하거나 명령에 붙여 넣지 않는다.

   ```bash
   python3 <이 스킬 폴더>/scripts/ha_ws.py --kubectl "<kubectl 실행 명령>" --summary
   python3 <이 스킬 폴더>/scripts/ha_ws.py --kubectl "<kubectl 실행 명령>" --device "<기기 이름>"
   ```

   `--kubectl` 에는 환경 정보의 kubectl 실행 명령을 그대로 넣는다(예: `--kubectl "ssh cp kubectl"`).
   `--device` 는 그 기기와 기기에 속한 엔티티 ID 를 모두 낸다(`devices[].entities[].entity_id`). 기기 이름을 바꿀 때는
   이 목록의 엔티티를 모두 바꾼다. 엔티티 ID 는 영문 소문자·숫자·밑줄만 쓴다. 기기 이름의 `-`·공백은 `_` 로 바꾸고
   기존 접미사는 유지한다(예: 기기 `Kitchen Sensor` 를 `kitchen-th` 로 바꾸면 `sensor.kitchen_sensor` 는
   `sensor.kitchen_th`, `sensor.kitchen_sensor_battery` 는 `sensor.kitchen_th_battery`). 다른 목록은 `--list <종류> --filter <키>=<값>` 으로 보고, 결과는 `list.items` 에 있다.

   네임스페이스·배포·토큰 시크릿이 기본값(`home-assistant`, `home-assistant/ha-api-token:token`)과 다르면
   `--namespace`·`--deploy`·`--token-secret` 을 붙인다.
3. **변경을 미리 본다.** 환경에 전용 운영 스크립트가 있으면 그것을 `--dry-run` 과 함께 쓴다. 없으면 같은 명령에
   `--dry-run --call '<JSON>'` 을 붙여 보낼 메시지를 확인한다. 바꿀 대상(기기와 그 엔티티 전부)이 빠짐없이 들어갔는지 본다.

   ```bash
   python3 <이 스킬 폴더>/scripts/ha_ws.py --kubectl "<kubectl 실행 명령>" --dry-run \
     --call '{"type":"config/entity_registry/update","entity_id":"sensor.old","new_entity_id":"sensor.new"}'
   ```

4. **실행한다.** `--dry-run` 을 빼고 같은 명령을 실행한다. 바꿀 것이 여러 개면 `--call` 을 여러 번 붙여 한 번에 보낸다
   (기기 이름은 `config/device_registry/update` 의 `name_by_user`).
5. **검증**:
   - 같은 dry-run 을 다시 실행해 할 일이 남지 않았는지 확인한다.
   - `--device "<새 이름>"`·`--summary`·`--list` 로 결과를 확인한다.
   - 데이터가 흘러가는 곳(MQTT, DB)이 있으면 새 이름·값으로 들어오는지 본다.

   통과하기 전에는 끝났다고 보고하지 않는다.

## 서버 설정을 바꾸는 경우 (GitOps)

HA 의 배포 설정(자원 한도, 이미지, 볼륨, 네트워크)을 바꾸는 일이면 위 절차 대신 GitOps 변경 절차를 따른다. GitOps 변경을 다루는 스킬이 있으면 먼저 켠다.
설정 파일 위치는 사용자에게 묻지 말고 GitOps 저장소에서 찾는다. 저장소를 고쳐 커밋·push 한 뒤, 동기화 도구가 push 한
커밋으로 Synced·Healthy 가 될 때까지 아래 명령으로 기다린다. 한 줄이 출력되면 반영된 것이고, 아무것도 안 나오면 다시
실행한다. 그 전에 본 롤아웃·로그는 옛 배포다. 그다음 배포된 리소스에 새 값이 들어갔는지 확인한다.

```bash
H=$(git -C <저장소> rev-parse HEAD)
for i in 1 2 3 4 5 6; do <kubectl 실행 명령> -n argocd get app <앱> --no-headers \
  -o custom-columns=REV:.status.sync.revision,SYNC:.status.sync.status,HEALTH:.status.health.status \
  | grep "^$H *Synced *Healthy" && break; sleep 15; done
```

## 자주 쓰는 호출

| 할 일 | WebSocket 메시지 `type` |
| :--- | :--- |
| 엔티티 목록·수정(이름, `new_entity_id`, `disabled_by: null`, `area_id`) | `config/entity_registry/list`, `config/entity_registry/update` |
| 기기 목록·수정(`name_by_user`, `area_id`) | `config/device_registry/list`, `config/device_registry/update` |
| 영역 목록·생성·삭제 | `config/area_registry/list`, `config/area_registry/create`, `config/area_registry/delete` |
| 통합(설정 항목) 목록 | `config_entries/get` |
| 통합 추가 | REST `POST /api/config/config_entries/flow` 로 흐름을 시작하고 단계별로 값을 보낸다 |
| 상태 보기 | `get_states` 또는 REST `GET /api/states/<entity_id>` |

정확한 필드는 HA 버전에 따라 다르다. 확인은 해당 목록 호출의 결과 필드를 보고 한다.

## 이름 규칙

기기 이름이 방·종류·위치를 담고, 그 이름이 DB 의 칸으로 나뉘어 들어가는 환경이 있다. 이름을 새로 짓거나 바꿀 때는
`## 서비스` 에 적힌 이름 규칙 문서를 따른다. 이름을 바꾼 뒤에는 다음 순서로 처리한다.

1. 엔티티 ID 를 새 이름에 맞춘다.
2. 영역을 다시 배정한다.
3. 중앙 HA 가 있으면 그쪽에 남은 옛 엔티티를 정리한다.

## 주의

- 기기 이름을 바꿔도 엔티티 ID 는 자동으로 바뀌지 않는다(바꿀지 묻지 않는 버전도 있다). 엔티티 ID 를 따로 바꾼다.
  바꾸지 않으면 엔티티 ID 를 쓰는 곳(상태 발행 토픽, DB 의 속성 이름)에 옛 이름이 남는다.
- 통합이 꺼 둔 엔티티(`disabled_by: integration`)와 사용자가 끈 엔티티(`disabled_by: user`)를 구분한다. 일괄로 켤 때는
  통합이 꺼 둔 것만 켠다. 새 기기부터 기본으로 켜지게 하는 설정(예: 브리지의 기본 활성 옵션)이 있으면 함께 고친다.
- HA 이력(recorder)은 엔티티 ID 를 따라간다. 기기를 다른 방으로 옮기기 전의 기록도 같은 엔티티에 섞여 보인다.
  이름별로 나뉜 이력은 DB 에서 본다.
- 토큰 시크릿이 빈 값으로 만들어지면 "already exists" 뒤에도 인증이 실패한다. 값 길이를 확인하고 다시 만든다.
- 템플릿에서 속성 키가 열거형이면 `| string` 이 기대대로 동작하지 않는다. `k ~ ''` 로 문자열로 만든다.
- 삭제가 들어간 작업(엔티티·영역 삭제, 잔재 정리)은 dry-run 결과를 보여 주고 확인받은 뒤에 실행한다.

## 스크립트

- `scripts/ha_ws.py`: WebSocket API 호출기. `--summary`(엔티티·기기·영역 수, 비활성 이유별 수, 영역 없는 기기),
  `--device <이름>`(기기와 그 엔티티), `--list`, `--call '<JSON>'`, `--dry-run` 을 지원한다. 작업 PC 에서 `--kubectl "<kubectl 실행 명령>"` 으로 부르면
  토큰 시크릿을 읽어 HA 파드 안에서 실행한다. `--help` 참고.

## 하지 않는 것

- UI 에서 하나씩 누르는 절차를 안내하는 것으로 끝내지 않는다. API·스크립트로 처리하고, 불가능하면 그 이유를 말한다.
- 토큰을 사용자에게 묻거나, 출력하거나, 파일에 남기지 않는다.
- 사용자가 끈 엔티티를 일괄 작업으로 켜지 않는다.
