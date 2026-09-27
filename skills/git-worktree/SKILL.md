---
name: git-worktree
description: 한 저장소에서 여러 작업을 동시에 하려고 git worktree 를 만들거나, 쓰고 난 worktree 를 정리할 때 쓴다. "지금 작업은 두고 다른 브랜치에서 급한 거 먼저", "병렬로 따로 작업" 처럼 worktree 라는 말이 없어도 작업 디렉터리를 나눠야 하는 상황에 쓴다. 위치·이름 규칙, 만들기·목록·삭제 명령, 남은 worktree 정리를 담고 있다. 단순히 브랜치를 바꾸는 작업에는 쓰지 않는다.
---

# git worktree

worktree 는 같은 저장소의 다른 브랜치를 별도 폴더에 체크아웃한다. 지금 작업 폴더를 건드리지 않고 다른 브랜치에서 작업하거나,
여러 작업을 동시에 돌릴 때 쓴다. **만든 worktree 는 작업이 끝나면 반드시 지운다**(남으면 그 브랜치를 다른 곳에서 체크아웃할 수 없다).

## 절차

1. **상태를 본다**:

   ```bash
   git worktree list
   git status --short --branch
   ```

2. **만든다**: 저장소 폴더 옆에 `<저장소>-<주제>` 이름으로 둔다. 저장소 안에 두지 않는다(추적되지 않는 폴더가 생겨 도구가 헷갈린다).

   ```bash
   git fetch origin
   git worktree add -b <새 브랜치> ../<저장소>-<주제> origin/<기본 브랜치>   # 새 브랜치
   git worktree add ../<저장소>-<주제> <기존 브랜치>                          # 기존 브랜치
   ```

3. **작업한다**: 그 폴더에서 평소처럼 커밋·push 한다. 의존성 설치·빌드 산출물은 worktree 마다 따로 생기므로 필요하면 다시 설치한다.
4. **지운다**: 변경을 모두 커밋·push 했는지 확인한 뒤 지운다.

   ```bash
   git -C ../<저장소>-<주제> status --short     # 비어 있어야 한다
   git worktree remove ../<저장소>-<주제>
   git worktree prune                            # 폴더가 이미 사라진 항목 정리
   ```

5. **검증**: `git worktree list` 에 만든 worktree 가 남지 않았는지 확인하고 보고한다.

## 주의

- 한 브랜치는 한 worktree 에서만 체크아웃할 수 있다. `already checked out` 오류가 나면 `git worktree list` 로 어디에 있는지 찾는다.
- 커밋하지 않은 변경이 있는 worktree 는 `remove` 가 거부한다. `--force` 로 지우기 전에 사용자에게 확인한다.

## 하지 않는 것

- 사용자가 만든 worktree 를 확인 없이 지우지 않는다.
