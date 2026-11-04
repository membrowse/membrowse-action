---
name: bump-version
description: Bump the membrowse package version (pyproject.toml and the Claude plugin manifests), open a PR, wait for CI to pass and squash-merge it. Use when the user asks to bump the version, cut a patch/minor/major release version, or run /bump-version. Accepts an optional argument - "patch" (default), "minor", "major", or an explicit version like 1.3.0.
---

# Bump version

Bumps the version, opens a PR, waits for its checks and merges it. Argument: `patch` (default), `minor`, `major`, or an explicit `X.Y.Z`.

## 1. Preconditions — stop if any fails

```bash
git rev-parse --abbrev-ref HEAD          # must print: main
git fetch origin main
git status --porcelain --untracked-files=no   # must be empty (untracked files are fine)
git rev-list --count HEAD..origin/main   # must be 0; if not, `git pull --ff-only` first
git rev-list --count origin/main..HEAD   # must be 0 (no unpushed local commits on main)
```

If the branch is not `main`, stop and tell the user — do not switch branches for them. If tracked files are modified, stop and report them.

## 2. Compute the new version

Read the current version from `pyproject.toml` (`version = "X.Y.Z"` under `[project]`). Apply the argument:
- `patch` → `X.Y.(Z+1)`; `minor` → `X.(Y+1).0`; `major` → `(X+1).0.0`; explicit → use as given (must be greater than current).

The version appears in exactly these three places — update all of them and nothing else:
- `pyproject.toml` — `version = "…"`
- `.claude-plugin/plugin.json` — `"version": "…"`
- `.claude-plugin/marketplace.json` — `"version": "…"` of the plugin entry

Verify with `grep -rn '"version"\|^version' pyproject.toml .claude-plugin/` that all three show the new version. Do not touch version mentions in tests or docs (those are historical references).

## 3. Branch, commit, push, PR

```bash
git checkout -b bump-vNEW
git add pyproject.toml .claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "bump vNEW"
git push -u origin bump-vNEW
gh pr create --base main --head bump-vNEW --title "bump vNEW" \
  --body "Bump version to NEW in pyproject.toml and the Claude plugin manifests."
```

No `Co-Authored-By` trailers or "Generated with Claude Code" lines in the commit or PR body. If the user gave a reason for the release (e.g. "patch for #191"), add it as the first line of the PR body.

## 4. Wait for checks

```bash
gh pr checks bump-vNEW --watch --fail-fast
```

Run it in the background or with a long timeout (CI takes several minutes). If checks have not registered yet, `gh pr checks` may report none — wait ~30 s and retry. If any check fails, stop: report the failing check and its log (`gh run view <run-id> --log-failed`), and leave the PR open. Do not merge.

## 5. Merge and clean up

```bash
gh pr merge bump-vNEW --squash --delete-branch
git checkout main
git pull --ff-only
```

Report the merged PR URL and the new version. Merging does not publish to PyPI — publishing runs on a GitHub release (`.github/workflows/publish-to-pypi.yml`). Mention that, but do not create the release unless the user asks.
