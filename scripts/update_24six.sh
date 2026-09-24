#!/usr/bin/env bash
# Move the 24six fork to the latest upstream stable release and publish it.
#
# The fork's stable branch is upstream stable with the 24six commits rebased on top. This
# script fetches upstream, rebases the fork branch onto upstream stable, runs the provider and
# release-script checks, force-pushes the fork's stable branch and then dispatches the
# "24six Release" workflow, which builds the image, creates the GitHub release and bumps the
# Home Assistant add-on. Finally it verifies that all three exist.
#
# Usage: scripts/update_24six.sh [--skip-checks] [--no-release] [--force-release]
#   --skip-checks    Do not run pytest and pre-commit before pushing.
#   --no-release     Rebase and push only; do not dispatch the release workflow.
#   --force-release  Dispatch the release workflow even when nothing new was pushed.
#
# Configuration comes from the environment (defaults in brackets):
#   FORK_BRANCH      local branch carrying the 24six commits [24six-stable]
#   UPSTREAM_REMOTE  git remote of music-assistant/server [origin]
#   FORK_REMOTE      git remote of the fork [tikotzky]
#   FORK_REPOSITORY  GitHub repository of the fork [tikotzky/music-assistant-server]
#   ADDON_REPOSITORY GitHub repository of the add-on fork
#                    [tikotzky/music-assistant-home-assistant-addon]
#   ADDON_CHECKOUT   local clone of the add-on fork to fast-forward after the release
#                    [../music-assistant-home-assistant-addon, skipped when absent]
set -euo pipefail

cd "$(dirname "$0")/.."

FORK_BRANCH=${FORK_BRANCH:-24six-stable}
UPSTREAM_REMOTE=${UPSTREAM_REMOTE:-origin}
FORK_REMOTE=${FORK_REMOTE:-tikotzky}
FORK_REPOSITORY=${FORK_REPOSITORY:-tikotzky/music-assistant-server}
ADDON_REPOSITORY=${ADDON_REPOSITORY:-tikotzky/music-assistant-home-assistant-addon}
ADDON_CHECKOUT=${ADDON_CHECKOUT:-../music-assistant-home-assistant-addon}
RELEASE_WORKFLOW="release-24six.yml"
IMAGE=ghcr.io/${FORK_REPOSITORY%%/*}/server
UPSTREAM_STABLE="$UPSTREAM_REMOTE/stable"
FORK_STABLE="$FORK_REMOTE/stable"

# The uv config pins `exclude-newer`, which makes fresh tool installs fail; the hooks and
# tests only work with the pin lifted. 1Password commit signing does not work unattended.
export UV_EXCLUDE_NEWER=${UV_EXCLUDE_NEWER:-2100-01-01T00:00:00Z}
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=commit.gpgsign GIT_CONFIG_VALUE_0=false

skip_checks=false
release=true
force_release=false
for argument in "$@"; do
  case "$argument" in
    --skip-checks) skip_checks=true ;;
    --no-release) release=false ;;
    --force-release) force_release=true ;;
    --help | -h)
      sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "❌ Unknown argument: $argument (see --help)" >&2
      exit 2
      ;;
  esac
done

step() { printf '\n▶ %s\n' "$*"; }

for tool in git gh curl python3; do
  if ! command -v "$tool" &>/dev/null; then
    echo "❌ $tool is required" >&2
    exit 1
  fi
done

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "❌ The working tree has uncommitted changes; commit or stash them first." >&2
  exit 1
fi
if [[ -d "$(git rev-parse --git-path rebase-merge)" || -d "$(git rev-parse --git-path rebase-apply)" ]]; then
  echo "❌ A rebase is in progress; finish it (git rebase --continue) and re-run." >&2
  exit 1
fi

step "Fetching $UPSTREAM_REMOTE and $FORK_REMOTE"
git fetch --quiet --tags "$UPSTREAM_REMOTE"
git fetch --quiet "$FORK_REMOTE"

upstream_version=$(git describe --tags --abbrev=0 --match '[0-9]*.[0-9]*.[0-9]*' "$UPSTREAM_STABLE")
if [[ "$(git rev-parse "$upstream_version^{commit}")" != "$(git rev-parse "$UPSTREAM_STABLE")" ]]; then
  echo "⚠️ $UPSTREAM_STABLE is ahead of its newest release tag $upstream_version;" \
    "the release will still be named after $upstream_version." >&2
fi
echo "Upstream stable release: $upstream_version"

if git merge-base --is-ancestor "$UPSTREAM_STABLE" "$FORK_BRANCH"; then
  echo "$FORK_BRANCH already contains $UPSTREAM_STABLE; nothing to rebase."
else
  step "Rebasing $FORK_BRANCH onto $UPSTREAM_STABLE"
  echo "New upstream commits: $(git rev-list --count "$FORK_BRANCH..$UPSTREAM_STABLE")"
  if ! git rebase "$UPSTREAM_STABLE" "$FORK_BRANCH"; then
    echo "❌ The rebase stopped on a conflict. Resolve it, run 'git rebase --continue'" \
      "until it finishes, then re-run this script to check, push and release." >&2
    exit 1
  fi
fi
git checkout --quiet "$FORK_BRANCH"
echo "24six commits on top of upstream: $(git rev-list --count "$UPSTREAM_STABLE..$FORK_BRANCH")"

if [[ "$skip_checks" == false ]]; then
  step "Running the 24six tests"
  if [[ -f .venv/bin/activate ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
  fi
  python -m pytest tests/providers/twentyfour_six tests/scripts/test_release_24six.py \
    --quiet --no-header -p no:cacheprovider

  step "Running pre-commit on the files the fork changes"
  git diff --name-only --diff-filter=d "$UPSTREAM_STABLE..$FORK_BRANCH" |
    xargs pre-commit run --files
fi

pushed=false
if [[ "$(git rev-parse "$FORK_BRANCH")" == "$(git rev-parse "$FORK_STABLE")" ]]; then
  echo "$FORK_STABLE is already at $(git rev-parse --short "$FORK_BRANCH"); nothing to push."
else
  step "Pushing $FORK_BRANCH to $FORK_STABLE"
  git push --force-with-lease "$FORK_REMOTE" "$FORK_BRANCH:stable"
  pushed=true
fi

if [[ "$release" == false ]]; then
  echo "Skipping the release (--no-release)."
  exit 0
fi
if [[ "$pushed" == false && "$force_release" == false ]]; then
  echo "Nothing new was pushed, so no release was made (use --force-release to release anyway)."
  exit 0
fi

step "Dispatching the release workflow on $FORK_REPOSITORY"
head_sha=$(git rev-parse "$FORK_BRANCH")
gh workflow run "$RELEASE_WORKFLOW" --repo "$FORK_REPOSITORY" --ref stable
run_id=""
for _ in $(seq 1 12); do
  sleep 5
  run_id=$(gh run list --repo "$FORK_REPOSITORY" --workflow "$RELEASE_WORKFLOW" --limit 5 \
    --json databaseId,headSha,createdAt \
    --jq "[.[] | select(.headSha == \"$head_sha\")] | sort_by(.createdAt) | last | .databaseId // empty")
  [[ -n "$run_id" ]] && break
done
if [[ -z "$run_id" ]]; then
  echo "❌ The dispatched run did not show up; check the Actions tab of $FORK_REPOSITORY." >&2
  exit 1
fi
echo "Run: https://github.com/$FORK_REPOSITORY/actions/runs/$run_id"

step "Waiting for the release workflow"
gh run watch "$run_id" --repo "$FORK_REPOSITORY" --exit-status --interval 30 | tail -n 3

step "Verifying the release"
version=$(gh release list --repo "$FORK_REPOSITORY" --limit 1 --json tagName --jq '.[0].tagName')
if [[ "$version" != "$upstream_version-24six."* ]]; then
  echo "❌ The newest release is $version, not a release of upstream $upstream_version." >&2
  exit 1
fi
echo "GitHub release: https://github.com/$FORK_REPOSITORY/releases/tag/$version"

registry_token=$(curl --silent --fail "https://ghcr.io/token?scope=repository:${IMAGE#ghcr.io/}:pull" |
  python3 -c 'import json, sys; print(json.load(sys.stdin)["token"])')
manifest_status=$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --header "Authorization: Bearer $registry_token" \
  --header 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json' \
  "https://ghcr.io/v2/${IMAGE#ghcr.io/}/manifests/$version")
if [[ "$manifest_status" != 200 ]]; then
  echo "❌ Image $IMAGE:$version is not pullable (HTTP $manifest_status)." >&2
  exit 1
fi
echo "Container image: $IMAGE:$version"

addon_version=$(gh api "repos/$ADDON_REPOSITORY/contents/music_assistant/config.yaml" --jq '.content' |
  base64 --decode | sed -n 's/^version: *//p')
if [[ "$addon_version" != "$version" ]]; then
  echo "❌ The add-on in $ADDON_REPOSITORY is at $addon_version, expected $version." >&2
  exit 1
fi
echo "Add-on version: $addon_version"

if [[ -d "$ADDON_CHECKOUT/.git" ]]; then
  step "Fast-forwarding the local add-on clone"
  git -C "$ADDON_CHECKOUT" pull --quiet --ff-only || echo "⚠️ Could not fast-forward $ADDON_CHECKOUT" >&2
  git -C "$ADDON_CHECKOUT" log --oneline -1
fi

printf '\n✅ Released %s\n' "$version"
