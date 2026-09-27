---
name: git-branch
description: git 브랜치를 새로 만들거나, 바꾸거나, 기본 브랜치와 맞추거나(rebase·merge), 병합이 끝난 브랜치를 지울 때 쓴다. "작업 시작해", "main 최신으로 맞춰", "이 브랜치 정리해" 처럼 브랜치라는 말이 없어도 작업 브랜치를 준비·정리하는 상황에 쓴다. 저장소별 브랜치 정책 확인, 이름 규칙, 동기화 방식 선택, 삭제 전 확인을 담고 있다. 커밋 메시지 작성이나 PR 생성에는 쓰지 않는다.
---

# git 브랜치

브랜치 정책은 저장소마다 다르다. 어떤 저장소는 기본 브랜치에 바로 커밋하고, 어떤 저장소는 개발 브랜치에 커밋한 뒤
PR 로만 기본 브랜치를 갱신한다. 그래서 **먼저 그 저장소의 규칙 문서를 읽고**, 규칙이 없을 때만 아래 기본값을 쓴다.

## 절차

1. **저장소 규칙을 읽는다**: 저장소 루트의 `AGENTS.md`, `CONTRIBUTING.md`, `README.md` 에서 커밋할 브랜치와
   병합 방식(PR 필수 여부, squash/merge)을 찾는다. 규칙이 있으면 그대로 따르고 아래 기본값은 쓰지 않는다.
2. **지금 상태를 본다**:

   ```bash
   git status --short --branch
   git branch -vv
   git remote show origin | sed -n '/HEAD branch/p'   # 기본 브랜치 이름
   ```

   커밋하지 않은 변경이 있으면 새 브랜치로 옮길지(그대로 `git switch -c` 하면 따라감) 먼저 판단한다.
   남의 변경이 섞여 있으면 사용자에게 확인한다.
3. **새 브랜치를 만든다**(규칙이 없을 때의 기본값): 기본 브랜치를 최신으로 받은 뒤 거기서 딴다.

   ```bash
   git fetch origin
   git switch -c <종류>/<주제> origin/<기본 브랜치>
   ```

   이름은 영어 소문자·하이픈, 종류는 커밋 타입과 같게 쓴다(`feat/`, `fix/`, `docs/`, `chore/`). 예: `docs/ollama-router-comment`.
4. **기본 브랜치와 맞춘다**:
   - 아직 push 하지 않았거나 나만 쓰는 브랜치: `git fetch origin && git rebase origin/<기본 브랜치>`
   - 이미 공유한 브랜치: `git fetch origin && git merge origin/<기본 브랜치>`(이력을 다시 쓰지 않음)
   - 충돌이 나면 파일을 고치고 `git add` 한 뒤 `git rebase --continue`(또는 merge 커밋). 판단이 서지 않는 충돌은
     `git rebase --abort` 로 되돌리고 사용자에게 알린다.
5. **병합된 브랜치를 지운다**: 기본 브랜치에 들어간 것을 확인한 뒤에만 지운다.

   ```bash
   git fetch --prune origin
   git branch --merged origin/<기본 브랜치>        # 여기 나온 것만 지운다
   git branch -d <브랜치>                          # -D(강제)는 쓰지 않는다
   ```

   squash 병합은 `--merged` 에 나오지 않는다. 그때는 PR 이 병합됐는지(호스팅 서비스의 PR 상태)로 확인한다.
6. **검증**: `git status --short --branch` 로 현재 브랜치와 upstream, 앞선·뒤처진 커밋 수를 확인하고 보고한다.

## 주의

- 저장소 규칙이 "기본 브랜치에 바로 커밋"이면 브랜치를 만들지 않는다. 불필요한 브랜치와 PR 은 규칙 위반이다.
- 개발 브랜치 → 기본 브랜치 병합을 자동 워크플로가 하는 저장소가 있다. 그 PR 을 손으로 만들거나 병합하지 않는다.
- 공유 브랜치에서 rebase 후 push 하려면 강제 push 가 필요하다. 강제 push 는 사용자 확인 없이는 하지 않는다.

## 하지 않는 것

- `git branch -D`, `git push --delete` 로 병합 여부를 확인하지 않은 브랜치를 지우지 않는다.
- 다른 사람의 브랜치를 rebase 하지 않는다.
