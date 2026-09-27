---
name: patroni-ops
description: Patroni 로 복제하는 PostgreSQL(TimescaleDB 포함) 클러스터의 상태를 보거나, 주 DB 를 찾아 쿼리하거나, 주 DB 를 다른 멤버로 넘기거나(switchover), 멤버를 다시 붙일 때 쓴다. "DB 어느 게 주야", "DB 쿼리 좀 돌려", "DB 넘겨 놓고 노드 재시작" 처럼 Patroni 라는 말이 없어도 복제 DB 클러스터를 다루는 상황에 쓴다. 주 DB 찾기, 멤버 목록·복제 지연 확인, switchover, 안전한 쿼리 방법을 담고 있다. DB 스키마 설계나 대시보드 수정에는 쓰지 않는다.
---

# Patroni DB 운영

Patroni 는 멤버 중 하나를 주 DB 로 고르고 나머지를 스트리밍 복제로 따라가게 한다. 주 DB 는 바뀔 수 있으므로 **파드·호스트 이름을
고정해 쓰지 말고 매번 찾는다.** 쓰기와 관리 명령은 주 DB 에서만 한다.

## 환경 정보

`~/.agents/environment.md` 의 `## 서비스`(DB 접속 방법)와 `## 클러스터`(kubectl 실행 위치), `## 시크릿 위치`(DB 계정) 절을 직접 열어 읽는다(있는지
사용자에게 묻지 않는다). 파일이 없거나 필요한 항목이 비어 있으면 먼저 접근 가능한 곳(설정 파일, 서버, 저장소)을 조사하고, 그래도 모르는 것만
사용자에게 묻는다. 알아낸 값은 그 파일의 해당 절에 적은 뒤 진행한다. 비밀값 자체는 적지 않고 값이 있는 위치만 적는다.

## 절차

1. **환경 정보를 읽는다**: DB 가 있는 클러스터·네임스페이스, 컨테이너 이름, Patroni 설정 파일 경로를 확인한다.
2. **주 DB 를 찾는다**: Patroni 가 파드에 `role` 라벨(`primary`/`replica`)을 붙인다.

   ```bash
   kubectl -n <ns> get pods -L role
   P=$(kubectl -n <ns> get pod -l role=primary -o jsonpath='{.items[0].metadata.name}')
   ```

3. **멤버 상태를 본다**:

   ```bash
   kubectl -n <ns> exec $P -c <컨테이너> -- patronictl -c <patroni 설정 파일> list
   ```

   Leader 1, Sync Standby(동기 복제를 쓰면) 1, 나머지 Replica `streaming`, Lag 0 에 가까우면 정상이다. 설정 파일 경로는 StatefulSet 의
   컨테이너 명령(`patroni <경로>`)에서 찾는다.
4. **쿼리한다**: 여러 줄 SQL 은 heredoc 으로 넘긴다(ssh·셸 따옴표 안에 SQL 따옴표를 넣으면 깨진다).

   ```bash
   kubectl -n <ns> exec -i $P -c <컨테이너> -- psql -U postgres -d <DB> -At <<'SQL'
   select now();
   SQL
   ```

5. **주 DB 를 넘긴다**(노드 작업 전 등, 사용자 확인 뒤):

   ```bash
   kubectl -n <ns> exec $P -c <컨테이너> -- patronictl -c <설정> switchover --leader <지금 주 DB> --candidate <새 주 DB> --force
   ```

   서비스가 새 주 DB 를 가리키는지(`kubectl -n <ns> get endpoints <서비스>`), 옛 주 DB 가 Replica 로 다시 붙는지(`streaming`) 확인한다.
6. **검증**: `patronictl list` 가 정상이고, 쓰는 앱의 새 행이 계속 들어오는지(최근 몇 분 행 수) 확인한 뒤 보고한다.

## 주의

- 서비스가 selector 없이 Patroni 가 쓰는 Endpoints 로 주 DB 를 가리키는 구성에서는, 컨트롤러가 만든 옛 Endpoints(미러링 제외 라벨이 붙은 것)가
  남아 있으면 리더 잠금에 실패한다. 옛 Endpoints 를 지우면 Patroni 가 다시 만든다.
- DB 파드 안의 셸이나 psql 을 `pkill -f` 로 죽이지 않는다. 자기 셸까지 죽고, DB 프로세스를 잘못 건드리면 복구가 반복될 수 있다.
- 다른 DB 에서 행을 옮길 때는 임시 테이블에 받은 뒤 `EXCEPT` 로 이미 있는 행을 빼고 넣으면 여러 번 실행해도 겹치지 않는다.

## 하지 않는 것

- 확인 없이 switchover·failover·멤버 재초기화(`reinit`)를 하지 않는다.
- 복제 멤버(Replica)에 쓰지 않는다.
