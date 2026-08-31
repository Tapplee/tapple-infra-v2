# GitHub trust root

Argo CD는 `tapple-infra-v2/main`을 자동 반영한다.
따라서 이 branch의 쓰기 권한은 사실상 cluster 변경 권한이다.
저장소가 public인 사실은 쓰기 권한을 주지 않는다.

## 현재 정책

| 정책 | 이유 | 비용 |
|---|---|---|
| 조직 secure 2FA | 계정 탈취 위험을 낮춘다 | 미준수 사용자는 먼저 2FA를 설정해야 한다 |
| `main`은 PR만 | 사람과 bot이 같은 diff와 CI 경로를 쓴다 | 배포가 CI만큼 늦어진다 |
| `Static validation`, strict | 최신 base에서 검증된 commit만 merge한다 | base 변경 시 CI를 다시 돈다 |
| check를 GitHub Actions App ID에 고정 | 같은 이름의 임의 status를 인정하지 않는다 | workflow identity 변경 시 정책도 갱신한다 |
| squash와 linear history | 자동 배포 PR의 rollback commit이 분명하다 | PR 내부 commit 경계는 main에서 사라진다 |
| 관리자 우회 금지 | 평상시 검증 우회를 막는다 | 비상시 보호 설정 변경이 먼저 필요하다 |
| force-push와 branch 삭제 금지 | desired state 이력을 보존한다 | history rewrite를 사용할 수 없다 |
| 승인 0 | 현재 단계의 명시적 결정이다 | 독립 리뷰를 강제하지 않는다 |

승인 0은 인원 수나 역할 모델을 추론한 값이 아니다.
약 20명의 maintainer 역할과 향후 review 규칙은 별도 정책으로 결정한다.
이번 설정은 direct push 방지와 필수 CI를 우선한다.
대화가 남은 PR은 merge하지 않도록 conversation resolution은 유지한다.

workflow 표시 이름은 `Validate infrastructure`다.
required-check context는 job 이름인 `Static validation`이다.

## 공개 PR 경계

public 저장소에는 외부와 fork PR이 열릴 수 있다.
backend PR workflow는 fork head를 checkout하거나 실행하지 않는다.
preview workflow는 same-repository와 `MEMBER`, `OWNER`, `COLLABORATOR`를 모두 확인한다.
외부 PR은 image, preview, infra 배포 credential에 접근하지 못한다.
infra `Static validation`은 read-only token과 GitHub-hosted runner에서 fork diff를 검사할 수 있다.
GitHub secret scanning과 push protection은 별도 수동 gate다.

## 적용 순서

보호 규칙보다 workflow를 먼저 배포한다.
순서를 바꾸면 아직 direct push를 쓰는 경로와 아직 존재하지 않는 required check가 함께 막힌다.

1. 이 저장소 변경을 `main`에 올린다.
2. 현재 `main` SHA의 `Static validation` 성공을 확인한다.
3. `tapple-be`의 PR 기반 `cd-gitops.yml`을 먼저 배포한다.
4. `INFRA_REPO_TOKEN`을 이 저장소만 선택한 fine-grained credential로 교체한다.
5. credential에는 Contents read/write와 Pull requests read/write만 준다.
6. credential에 만료일을 둔다.
7. 조직의 secure 2FA와 복구 수단을 확인한다.
8. `gh`와 `jq`가 있는 관리자 환경에서 스크립트를 실행한다.

```bash
scripts/configure-github-trust-root.sh --apply
```

스크립트는 두 저장소의 default branch와 workflow 계약을 먼저 읽는다.
스크립트는 현재 infra `main`의 성공 check와 GitHub Actions App ID를 확인한다.
스크립트는 branch protection을 먼저 적용한다.
그 뒤 auto-merge, squash-only, merge 뒤 branch 삭제를 적용한다.
중간 실패 시 보호가 먼저 남는다.
같은 명령을 다시 실행하면 수렴한다.
조직 2FA는 GitHub UI에서 별도로 적용한다.

## 배포 흐름

```text
tapple-be main/dev merge
  -> GHCR에 SHA tag push
  -> registry digest 확인
  -> deploy/<environment>/<tag>-<digest> branch
  -> image.tag + image.digest PR
  -> Static validation
  -> squash auto-merge
  -> Argo CD pull
```

tag는 사람이 commit을 찾는 메타데이터다.
trust root 후 첫 신뢰 배포 PR이 digest를 채우면 prod와 dev의 실제 container image는 `repository@sha256:...`를 사용한다.
현재 빈 digest는 이 bootstrap gate 전의 SHA tag fallback이다.
registry tag를 다시 가리켜도 실행 digest는 바뀌지 않는다.
preview는 ApplicationSet 제약 때문에 PR head SHA tag를 사용한다.

prod와 dev infra update는 workflow concurrency로 직렬화한다.
열린 배포 PR을 재사용할 때 정확한 head, base, SHA를 검증한다.
merge 요청은 `--match-head-commit`을 사용한다.
base가 앞서면 rebase 후 `Static validation`을 다시 실행한다.

## rollback

영구 rollback은 known-good tag와 digest를 복원하는 PR이다.
그 PR도 같은 required check를 통과한다.
Argo CD UI history rollback은 self-heal이 최신 Git 상태로 되돌릴 수 있다.
UI rollback은 장애를 잠시 막는 용도로만 사용한다.

## 확인

```bash
gh api repos/Tapplee/tapple-infra-v2/branches/main/protection
gh api repos/Tapplee/tapple-infra-v2 \
  --jq '{allow_auto_merge,allow_squash_merge,allow_merge_commit,allow_rebase_merge,delete_branch_on_merge}'
```

다음 값이 필요하다.

- strict required check가 `Static validation`과 Actions App ID에 묶여 있다.
- admin enforcement가 켜져 있다.
- approval count가 0이다.
- linear history와 conversation resolution이 켜져 있다.
- force push와 branch deletion이 꺼져 있다.
- merge commit과 rebase merge가 꺼져 있다.

GitHub 역할, CODEOWNERS, 승인 수 변경은 이 문서와 스크립트를 같은 PR에서 바꾼다.
