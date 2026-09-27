---
name: git-push
description: 커밋을 원격 저장소에 올릴 때(git push) 쓴다. "올려 줘", "반영해", "원격에 보내" 처럼 push 라는 말이 없어도 커밋을 원격에 내보내는 상황에 쓴다. push 전 검사(저장소가 정한 빌드·린트), upstream 설정, 거부됐을 때의 처리, 강제 push 금지 규칙을 담고 있다. 커밋 메시지 작성이나 PR 생성에는 쓰지 않는다.
---

# git push

push 는 다른 사람과 자동화(CI, GitOps 동기화, 배포)에 바로 영향을 준다. 그래서 **저장소가 정한 검사를 통과한 뒤에만**
올리고, **이력을 덮어쓰는 강제 push 는 하지 않는다**.

## 절차

1. **저장소 규칙을 읽는다**: `AGENTS.md`·`README.md` 에서 push 전 검사 명령(빌드, 린트, 렌더링·dry-run 등)과 push 할 브랜치를
   찾는다. 지금 브랜치가 그 규칙의 브랜치인지 확인한다.

   ```bash
   git status --short --branch
   git log --oneline @{u}..HEAD 2>/dev/null || git log --oneline -5   # 올라갈 커밋
   ```

2. **검사를 돌린다**: 규칙 문서의 검사 명령을 그대로 실행하고 모두 통과해야 다음으로 간다. 실패하면 고치고 커밋한 뒤 다시 돌린다.
3. **push 한다**:

   ```bash
   git push                         # upstream 이 있을 때
   git push -u origin <브랜치>      # 처음 올리는 브랜치
   ```

4. **거부되면**(`rejected ... fetch first`, `non-fast-forward`): 원격에 새 커밋이 있다는 뜻이다. 덮어쓰지 않고 받아서 합친다.

   ```bash
   git fetch origin
   git rebase origin/<브랜치>       # 내 커밋이 아직 나만 가진 것일 때. 공유 중이면 git merge
   ```

   합친 뒤 2단계 검사를 다시 돌리고 push 한다.
5. **검증**: `git status --short --branch` 에 `ahead`/`behind` 가 없는지 확인한다. push 뒤에 도는 자동화(CI, 동기화)가 있으면
   그 결과까지 확인한 뒤 보고한다.

## 주의

- 강제 push(`--force`, `--force-with-lease`)는 사용자가 명시적으로 요청했을 때만 한다. 요청을 받아도 `--force-with-lease` 를 쓴다.
- pre-push·commit-msg 훅이 거부하면 `--no-verify` 로 우회하지 않고 원인을 고친다.
- 기본 브랜치가 보호돼 있으면 push 대신 PR 로 올린다.

## 하지 않는 것

- 검사를 건너뛰고 push 하지 않는다.
- 사용자가 요청하지 않았고 저장소 규칙에도 없는 push 를 하지 않는다.
