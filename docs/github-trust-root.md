# GitHub trust root

`origin/main`은 Argo CD가 지속적으로 읽는 클러스터 desired state다. 따라서 `main` 쓰기 권한은
사실상 클러스터 변경 권한이며, 애플리케이션 배포 자동화도 검증을 우회해 직접 push하면 안 된다.

## 선택한 정책

| 선택 | 이유 | 비용·tradeoff | 재검토 조건 |
|---|---|---|---|
| 조직 2FA 필수, owner는 secure method 사용 | sole owner 계정 탈취가 곧 Git·클러스터 변조로 이어지는 경로를 줄인다 | 새 멤버도 먼저 2FA를 설정해야 한다 | 조직 SSO/Enterprise IdP 도입 |
| `main` 변경은 PR만 | 사람과 배포 봇 모두 같은 diff·감사·CI 경로를 지난다 | 이미지 배포가 인프라 CI 시간만큼 늦어진다 | 긴급 배포가 SLO를 넘기면 merge queue 또는 별도 deploy app 검토 |
| GitHub Actions의 `Static validation` 필수, strict=true | 현재 `main`을 기준으로 Helm·Ansible·정책 계약이 통과한 commit만 merge한다. 같은 이름을 게시할 수 있는 다른 주체는 인정하지 않는다 | base가 바뀌면 CI를 다시 돌린다 | CI 시간이 병목이면 job을 분리하되 보호 check와 source binding은 유지 |
| squash-only + linear history | 자동 이미지 bump PR 한 개를 한 commit으로 남기고 revert 대상을 분명히 한다 | PR 내부 commit 경계는 main에서 사라지고 rebase merge도 사용할 수 없다 | 인프라 PR이 여러 독립 변경을 자주 포함할 때 |
| 인프라 repo 전용 fine-grained PAT | 현재 단일 owner 규모에서 GitHub App 운영 없이 contents·PR 권한만 위임한다 | owner 계정에 수명·회전이 묶이고 만료 시 배포가 멈춘다 | maintainer/자동화가 늘거나 회전 부담이 커지면 GitHub App으로 교체 |
| 필수 승인 0명 | 현재 owner가 한 명이라 1명을 요구하면 자기 PR을 승인할 수 없어 영구 잠긴다 | 사람의 독립 리뷰는 없다. 2FA·PR diff·필수 CI에 의존한다 | 두 번째 신뢰 가능한 maintainer가 생기는 즉시 1명으로 변경 |
| 관리자 우회·force-push·삭제 금지 | sole owner도 평상시 실수로 검증을 건너뛰거나 이력을 바꾸지 못하게 한다 | 비상시 owner가 보호 설정을 먼저 변경해야 한다 | 별도 break-glass 절차와 감사 주체가 생길 때 |

`Validate infrastructure`는 workflow 표시 이름이고 GitHub의 required-check context는 job 이름인
`Static validation`이다. 적용 스크립트는 현재 `main`에서 성공한 check-run의 GitHub Actions
`app.id`를 읽어 context와 함께 고정한다. 이름만 같은 commit status로는 보호 조건을 만족할 수 없다.

## 적용 순서

보호 규칙을 먼저 켜면 아직 `main`에 직접 push하는 과거 배포 workflow와, 원격에 아직 없는
검증 workflow가 모두 막힌다. 다음 순서를 바꾸지 않는다.

1. 이 저장소 변경을 원격 `main`에 올리고 `Static validation` 성공을 확인한다.
2. `tapple-be`의 PR 기반 `cd-gitops.yml` 변경도 원격 `main`에 올린다. 이 push가 시작한 첫 CD는
   아직 정책이 없으면 인프라 checkout이나 PR 생성 전에 의도적으로 실패한다.
3. 배포용 `INFRA_REPO_TOKEN`을 resource owner `Tapplee`, **Only select repositories**에서
   `tapple-infra-v2` 하나만 선택한 fine-grained PAT로 교체한다. Repository permissions는
   **Contents: Read and write**, **Pull requests: Read and write**만 주고 만료일을 둔다.
4. GitHub **Organization settings → People**에서 disabled/insecure 2FA인 member와 outside
   collaborator가 없음을 확인한다. 이어 **Settings → Authentication security**에서
   **Require two-factor authentication**과 **Only allow secure two-factor methods**를 직접 켠다.
   현재 owner의 secure 2FA와 복구 수단도 먼저 확인한다.
5. `gh`에 조직 owner로 로그인하고 `jq`가 설치된 환경에서 아래 스크립트를 실행한다.

```bash
scripts/configure-github-trust-root.sh --apply
```

6. 2단계에서 fail-closed된 CD가 있으면 그 run의 **Re-run failed jobs**를 실행한다. 이미 5단계가
   끝난 뒤 trust-root 확인에 도달했다면 원래 run이 그대로 진행되므로 재실행하지 않는다.

스크립트는 두 저장소의 정확한 default branch와 workflow contract, 현재 infra `main` SHA에서
GitHub Actions가 성공시킨 check와 그 App ID, 조직 2FA 정책·미준수 member/outside collaborator를
읽기 전용으로 확인한다. 그 뒤 direct push를 먼저 닫는 branch protection을 적용하고 squash-only
auto-merge와 merge 후 branch 삭제를 켠다. 두 API 호출 사이에 실패해도 보호가 먼저 남으므로 배포는
우회되지 않으며 같은 명령을 다시 실행하면 수렴한다. 조직 2FA 설정은 UI에서 직접 확인·적용한다.

`gh pr merge --auto`는 미충족 보호 조건이 없으면 예약하지 않고 즉시 merge한다. 그래서 backend
workflow도 `main` 보호, App에 묶인 `Static validation`, auto/squash merge를 공개 API에서 모두
확인하기 전에는 실패한다. `--delete-branch`는 auto-merge 대기 경로에서 삭제를 예약하지 않으므로
branch 정리는 repository의 **Automatically delete head branches** 설정이 담당한다.

## 배포 흐름

```text
tapple-be main/dev
  → SHA 이미지 push
  → deploy/<environment>/<sha> 브랜치와 image.tag PR
  → Static validation
  → squash auto-merge
  → Argo CD pull
```

prod/dev 인프라 갱신은 직렬화한다. strict check가 통과한 PR을 기다리는 동안 다른 환경의 bump가
끼어 먼저 merge되어 check가 stale해지는 경합을 피하기 위해서다. preview PR은 인프라 값을
바꾸지 않으므로 이 직렬화 대상이 아니다.

배포 workflow는 열린 PR을 재사용할 때 same-repository의 정확한 head/base/SHA인지 확인하고,
merge 요청에는 `--match-head-commit`을 보낸다. 대기 중 `main`이 앞서면 head를 rebase해 check를
다시 실행하며, 일시적인 API·push 실패와 응답 유실은 제한적으로 재시도한다.

## 공식 문서

- [About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [REST API endpoints for branch protection](https://docs.github.com/en/rest/branches/branch-protection)
- [Managing auto-merge](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-auto-merge-for-pull-requests-in-your-repository)
- [`gh pr merge` manual](https://cli.github.com/manual/gh_pr_merge)
- [Managing fine-grained personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
- [Requiring 2FA in an organization](https://docs.github.com/en/organizations/keeping-your-organization-secure/managing-two-factor-authentication-for-your-organization/requiring-two-factor-authentication-in-your-organization)
