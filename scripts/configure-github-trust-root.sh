#!/usr/bin/env bash
# Apply the GitHub-side trust boundary after this repository and tapple-be changes are on main.
# The backend workflow requires both branch protection and auto-merge before it writes anything,
# so an interrupted application fails closed and this script can be rerun safely.
set -euo pipefail

readonly infra_repository="Tapplee/tapple-infra-v2"
readonly backend_repository="Tapplee/tapple-be"
readonly organization="Tapplee"
readonly required_check="Static validation"
readonly backend_workflow_contract="github-trust-root-contract: v1"

if [[ "${1:-}" != "--apply" || "$#" -ne 1 ]]; then
  echo "usage: $0 --apply" >&2
  exit 2
fi

command -v gh >/dev/null || {
  echo "gh CLI is required" >&2
  exit 1
}
command -v jq >/dev/null || {
  echo "jq is required" >&2
  exit 1
}
gh auth status >/dev/null

infra_metadata=$(gh api "repos/$infra_repository")
infra_default_branch=$(jq -r .default_branch <<<"$infra_metadata")
infra_admin=$(jq -r .permissions.admin <<<"$infra_metadata")
[[ "$infra_default_branch" == "main" ]] || {
  echo "unexpected infra default branch: $infra_default_branch" >&2
  exit 1
}
[[ "$infra_admin" == "true" ]] || {
  echo "the active gh account is not an administrator of $infra_repository" >&2
  exit 1
}

backend_default_branch=$(gh api "repos/$backend_repository" --jq .default_branch)
[[ "$backend_default_branch" == "main" ]] || {
  echo "unexpected backend default branch: $backend_default_branch" >&2
  exit 1
}

# Branch protection would reject the old direct-push deployment path. Require the PR-based
# workflow to be present on the backend default branch before changing repository policy.
backend_workflow_sha=$(gh api \
  "repos/$backend_repository/contents/.github/workflows/cd-gitops.yml?ref=$backend_default_branch" \
  --jq .sha)
backend_workflow=$(gh api \
  -H "Accept: application/vnd.github.raw+json" \
  "repos/$backend_repository/contents/.github/workflows/cd-gitops.yml?ref=$backend_default_branch")
if ! grep -Fq "$backend_workflow_contract" <<<"$backend_workflow" ||
  ! grep -Fq 'gh pr create' <<<"$backend_workflow" ||
  ! grep -Fq 'gh pr merge' <<<"$backend_workflow"; then
  echo "tapple-be main does not contain the guarded PR-based deploy workflow" >&2
  exit 1
fi

# GitHub accepts an arbitrary context through the API, but requiring a check that has never
# succeeded can lock the sole maintainer out. Require success from GitHub Actions on the exact
# remote main SHA, then bind the protection rule to that GitHub App instead of any source.
main_sha=$(gh api "repos/$infra_repository/commits/$infra_default_branch" --jq .sha)
required_check_app_id=$(gh api \
  -H "Accept: application/vnd.github+json" \
  "repos/$infra_repository/commits/$main_sha/check-runs?filter=latest&per_page=100" \
  --jq "[.check_runs[] | select(.name == \"$required_check\" and .conclusion == \"success\" and .app.slug == \"github-actions\") | .app.id] | unique | if length == 1 then .[0] else empty end")
[[ "$required_check_app_id" =~ ^[0-9]+$ ]] || {
  echo "$required_check has not succeeded from GitHub Actions on infra main $main_sha" >&2
  exit 1
}

# Enabling an organization 2FA requirement restricts non-compliant members and can remove outside
# collaborators. Refuse repository mutation unless all owner-only audit filters are empty.
disabled_2fa=$(gh api --paginate "orgs/$organization/members?filter=2fa_disabled" --jq '.[].login')
insecure_2fa=$(gh api --paginate "orgs/$organization/members?filter=2fa_insecure" --jq '.[].login')
disabled_outside_2fa=$(gh api --paginate "orgs/$organization/outside_collaborators?filter=2fa_disabled" --jq '.[].login')
insecure_outside_2fa=$(gh api --paginate "orgs/$organization/outside_collaborators?filter=2fa_insecure" --jq '.[].login')
[[ -z "$disabled_2fa" && -z "$insecure_2fa" && -z "$disabled_outside_2fa" && -z "$insecure_outside_2fa" ]] || {
  echo "organization has members or outside collaborators without secure 2FA; refusing policy mutation" >&2
  printf '%s\n%s\n%s\n%s\n' \
    "$disabled_2fa" "$insecure_2fa" "$disabled_outside_2fa" "$insecure_outside_2fa" >&2
  exit 1
}

organization_2fa=$(gh api "orgs/$organization" --jq .two_factor_requirement_enabled)
[[ "$organization_2fa" == "true" ]] || {
  echo "enable the organization 2FA requirement in GitHub Authentication security first:" >&2
  echo "https://github.com/organizations/$organization/settings/security" >&2
  exit 1
}

# Close the direct-push path first. If a later repository-settings call fails, deployment remains
# blocked rather than temporarily merging an unvalidated PR; rerunning this script converges it.
[[ "$(gh api "repos/$infra_repository/commits/$infra_default_branch" --jq .sha)" == "$main_sha" ]] || {
  echo "infra main changed during preflight; rerun after $required_check succeeds on the new SHA" >&2
  exit 1
}
[[ "$(gh api "repos/$backend_repository/contents/.github/workflows/cd-gitops.yml?ref=$backend_default_branch" --jq .sha)" == "$backend_workflow_sha" ]] || {
  echo "backend deploy workflow changed during preflight; review and rerun" >&2
  exit 1
}

gh api --method PUT "repos/$infra_repository/branches/$infra_default_branch/protection" \
  -H "Accept: application/vnd.github+json" \
  --input - >/dev/null <<JSON
{
  "required_status_checks": {
    "strict": true,
    "contexts": [],
    "checks": [
      {
        "context": "$required_check",
        "app_id": $required_check_app_id
      }
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": false,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 0,
    "require_last_push_approval": false
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": false
}
JSON

gh api --method PATCH "repos/$infra_repository" \
  -F allow_auto_merge=true \
  -F allow_squash_merge=true \
  -F allow_merge_commit=false \
  -F allow_rebase_merge=false \
  -F delete_branch_on_merge=true >/dev/null

repository_flags=$(gh api "repos/$infra_repository" \
  --jq '[.allow_auto_merge, .allow_squash_merge, .allow_merge_commit, .allow_rebase_merge, .delete_branch_on_merge] | @tsv')
[[ "$repository_flags" == $'true\ttrue\tfalse\tfalse\ttrue' ]] || {
  echo "repository merge settings did not converge" >&2
  exit 1
}

protection=$(gh api "repos/$infra_repository/branches/$infra_default_branch/protection")
configured_check_app_id=$(jq -r \
  --arg context "$required_check" \
  '.required_status_checks.checks[] | select(.context == $context) | .app_id' \
  <<<"$protection")
protection_flags=$(jq -r \
  '[.required_status_checks.strict, .enforce_admins.enabled, .required_pull_request_reviews.required_approving_review_count, .required_linear_history.enabled, .required_conversation_resolution.enabled, .allow_force_pushes.enabled, .allow_deletions.enabled] | @tsv' \
  <<<"$protection")
[[ "$configured_check_app_id" == "$required_check_app_id" && "$protection_flags" == $'true\ttrue\t0\ttrue\ttrue\tfalse\tfalse' ]] || {
  echo "branch protection did not converge" >&2
  exit 1
}

printf 'GitHub trust root applied: check=%s app_id=%s main=%s\n' \
  "$required_check" "$required_check_app_id" "$main_sha"
gh api "orgs/$organization" --jq '{two_factor_requirement_enabled}'
