"""Git metadata detection utilities."""

import os
import re
import subprocess
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, List

import requests

logger = logging.getLogger(__name__)

# GitHub's sentinel 'before' SHA for branch creation / first push (not a commit).
_ZERO_SHA = '0' * 40

# Matches a full 40-character hex git SHA-1.
_FULL_SHA1_RE = re.compile(r'[0-9a-f]{40}')

# How many first-parent ancestors an upload carries (metadata.git.ancestry).
# The core accumulates these into a project-level commit graph and uses it to
# link a report past commits that were never measured for its target. ~8 KB
# of JSON; symbols dwarf it. Must not exceed the core's cap of the same value.
ANCESTRY_DEPTH = 200

# Timeout for the GitHub REST fallback; the whole ancestry step is best-effort.
_ANCESTRY_HTTP_TIMEOUT = 15


def _is_full_sha1(value: str) -> bool:
    """Return True if value is a 40-character hex git SHA-1."""
    return bool(_FULL_SHA1_RE.fullmatch((value or '').strip().lower()))


@dataclass
class GitContext:
    """Git context information for metadata building."""
    commit_sha: str
    parent_sha: Optional[str]
    branch_name: str
    repo_name: str


def run_git_command(command: list) -> Optional[str]:
    """Run a git command and return stdout, or None on error."""
    try:
        result = subprocess.run(
            ['git'] + command,
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except Exception:  # pylint: disable=broad-exception-caught
        return None


def git_checkout(ref: str) -> None:
    """Checkout a git ref. Raises RuntimeError on failure."""
    result = subprocess.run(
        ['git', 'checkout', ref, '--quiet'],
        capture_output=True,
        check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to checkout {ref}")


def git_submodule_update() -> None:
    """Update submodules to match the current checkout."""
    subprocess.run(
        ['git', 'submodule', 'update', '--init', '--recursive', '--quiet'],
        capture_output=True, check=False
    )


def git_clean() -> None:
    """Remove all untracked and gitignored files (full clean build)."""
    subprocess.run(
        ['git', 'clean', '-fdx'],
        capture_output=True, check=False
    )


def get_parent_commit() -> Optional[str]:
    """
    Get the parent commit SHA of the current HEAD.

    Returns:
        Parent commit SHA (HEAD~1), or None if no parent exists (first commit).
    """
    return run_git_command(['rev-parse', 'HEAD~1'])


def _rev_list_first_parent(start_sha: str) -> List[str]:
    """First-parent line from start_sha using whatever objects are local."""
    output = run_git_command(
        ['rev-list', '--first-parent', f'--max-count={ANCESTRY_DEPTH}', start_sha])
    if not output:
        return []
    line = []
    for entry in output.splitlines():
        entry = entry.strip().lower()
        if not _is_full_sha1(entry):
            return []
        line.append(entry)
    return line


def _deepen_history(start_sha: str) -> bool:
    """Fetch up to ANCESTRY_DEPTH commits leading to start_sha, objects only.

    actions/checkout defaults to fetch-depth 1, so `git rev-list` alone yields
    one commit. `--filter=tree:0` downloads commit objects only - tens of
    kilobytes even on a large repository - and the checkout's persisted
    credentials cover private repositories. Note that a filtered fetch turns
    the checkout into a partial clone, so a LATER git step that needs trees or
    blobs the filter skipped will lazy-fetch them; the upload is the last step
    in every known workflow.
    """
    result = run_git_command(
        ['fetch', '--no-tags', '--filter=tree:0', f'--depth={ANCESTRY_DEPTH}',
         'origin', start_sha])
    return result is not None


def _github_api_ancestry(start_sha: str) -> List[str]:
    """First-parent line via the GitHub REST API, for checkouts that cannot
    fetch (persist-credentials: false). Needs GITHUB_REPOSITORY and a token.

    The commits listing is not first-parent only, so the line is rebuilt from
    each commit's `parents` by following the first parent through the pages.
    """
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN') or ''
    if not repo or not token:
        return []

    api = os.environ.get('GITHUB_API_URL', 'https://api.github.com').rstrip('/')
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    first_parent: Dict[str, Optional[str]] = {}
    for page in (1, 2):
        try:
            resp = requests.get(
                f'{api}/repos/{repo}/commits',
                params={'sha': start_sha, 'per_page': 100, 'page': page},
                headers=headers, timeout=_ANCESTRY_HTTP_TIMEOUT)
        except requests.RequestException as exc:
            logger.debug("Ancestry API request failed: %s", exc)
            return []
        if resp.status_code != 200:
            logger.debug("Ancestry API returned %s", resp.status_code)
            return []
        commits = resp.json()
        if not isinstance(commits, list) or not commits:
            break
        for commit in commits:
            sha = str(commit.get('sha', '')).lower()
            parents = commit.get('parents') or []
            parent = str(parents[0].get('sha', '')).lower() if parents else None
            if _is_full_sha1(sha):
                first_parent[sha] = parent if _is_full_sha1(parent or '') else None
        if len(commits) < 100:
            break

    line: List[str] = []
    current: Optional[str] = start_sha.lower()
    while current and current in first_parent and len(line) < ANCESTRY_DEPTH:
        line.append(current)
        current = first_parent[current]
    return line


def get_ancestry(start_sha: str, fetch: bool = True) -> List[str]:
    """The first-parent line from start_sha, newest first, up to ANCESTRY_DEPTH.

    Each entry's first parent is the next entry; the last entry's parent is
    unknown (the list is truncated). Every step is best-effort and logged at
    debug: ancestry collection must never fail an upload. Returns whatever was
    learned, possibly just start_sha, possibly nothing.

    Fallback order, each step only when the previous produced fewer than two
    entries: local `git rev-list`; a commit-only deepening fetch (skipped when
    fetch=False, e.g. onboard's full clone, or when start_sha is not a full
    SHA); the GitHub REST API; give up.
    """
    if not start_sha:
        return []
    try:
        line = _rev_list_first_parent(start_sha)
        if len(line) >= 2:
            return line

        if fetch and _is_full_sha1(start_sha):
            if _deepen_history(start_sha):
                line = _rev_list_first_parent(start_sha) or line
                if len(line) >= 2:
                    return line
            else:
                logger.debug("Could not deepen history for %s", start_sha)

            api_line = _github_api_ancestry(start_sha)
            if len(api_line) >= 2:
                return api_line

        if len(line) < 2:
            logger.debug("Ancestry for %s limited to %d entries", start_sha, len(line))
        return line
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("Ancestry collection failed for %s: %s", start_sha, exc)
        return []


def get_commit_tags(commit_sha: str) -> list:
    """
    Get all tags pointing at a specific commit.

    Args:
        commit_sha: Git commit SHA to check for tags

    Returns:
        List of tag names pointing at the commit, or empty list if none.
    """
    if not commit_sha:
        return []
    result = run_git_command(['tag', '--points-at', commit_sha])
    if not result:
        return []
    return [tag.strip() for tag in result.splitlines() if tag.strip()]


def _parse_pull_request_event(event_data: Dict[str, Any]) -> tuple:
    """Extract metadata from pull request event."""
    pr = event_data.get('pull_request', {})
    base_sha = pr.get('base', {}).get('sha', '')
    branch_name = pr.get('head', {}).get('ref', '')
    pr_number = str(pr.get('number', ''))
    head_sha = pr.get('head', {}).get('sha', '')
    pr_name = pr.get('title', '')
    # PR author info (user who opened the PR)
    pr_user = pr.get('user', {})
    pr_author_name = pr_user.get('login', '')
    # Note: GitHub API doesn't expose email for privacy, use login as fallback
    pr_author_email = ''
    return (base_sha, branch_name, pr_number, head_sha, pr_name,
            pr_author_name, pr_author_email)


def _parse_workflow_run_event(event_data: Dict[str, Any]) -> tuple:
    """Extract metadata from a workflow_run event.

    On workflow_run, GITHUB_SHA is the DEFAULT branch's last commit, not the
    commit the triggering run built, so a job that checks out
    workflow_run.head_sha would otherwise report (and overwrite) the default
    branch tip. The payload carries the real head and, for PR-triggered runs,
    the PR number and base.
    """
    run = event_data.get('workflow_run', {}) or {}
    head_sha = run.get('head_sha', '') or ''
    branch_name = run.get('head_branch', '') or ''
    pull_requests = run.get('pull_requests') or []
    base_sha, pr_number = '', ''
    if pull_requests:
        pr = pull_requests[0] or {}
        pr_number = str(pr.get('number', '') or '')
        base_sha = (pr.get('base') or {}).get('sha', '') or ''
    return base_sha, branch_name, pr_number, head_sha, '', '', ''


def _parse_push_event(event_data: Dict[str, Any]) -> tuple:
    """Extract metadata from push event."""
    base_sha = event_data.get('before', '')
    # Try to get branch from git, fall back to env var
    branch_name = (
        run_git_command(['symbolic-ref', '--short', 'HEAD']) or
        run_git_command(['for-each-ref', '--points-at', 'HEAD',
                         '--format=%(refname:short)', 'refs/heads/']) or
        os.environ.get('GITHUB_REF_NAME', 'unknown')
    )
    # Push events don't have PR author info
    return base_sha, branch_name, '', '', '', '', ''


def _parse_github_event(event_name: str, event_path: str) -> tuple:
    """Parse GitHub event payload."""
    base_sha, branch_name, pr_number, head_sha, pr_name = '', '', '', '', ''
    pr_author_name, pr_author_email = '', ''

    if not event_path or not os.path.exists(event_path):
        return (base_sha, branch_name, pr_number, head_sha, pr_name,
                pr_author_name, pr_author_email)

    try:
        with open(event_path, 'r', encoding='utf-8') as f:
            event_data = json.load(f)

        if event_name == 'pull_request':
            (base_sha, branch_name, pr_number, head_sha, pr_name,
             pr_author_name, pr_author_email) = _parse_pull_request_event(event_data)
        elif event_name == 'push':
            (base_sha, branch_name, pr_number, head_sha, pr_name,
             pr_author_name, pr_author_email) = _parse_push_event(event_data)
        elif event_name == 'workflow_run':
            (base_sha, branch_name, pr_number, head_sha, pr_name,
             pr_author_name, pr_author_email) = _parse_workflow_run_event(event_data)
    except Exception:  # pylint: disable=broad-exception-caught
        pass

    return (base_sha, branch_name, pr_number, head_sha, pr_name,
            pr_author_name, pr_author_email)


def _get_branch_name(branch_name: str) -> str:
    """Get branch name from git or fallback."""
    if branch_name:
        return branch_name

    return (
        run_git_command(['symbolic-ref', '--short', 'HEAD']) or
        run_git_command(['for-each-ref', '--points-at', 'HEAD',
                         '--format=%(refname:short)', 'refs/heads/']) or
        'unknown'
    )


def _get_repo_name() -> str:
    """Extract repository name from git remote URL."""
    remote_url = run_git_command(['config', '--get', 'remote.origin.url'])
    if not remote_url:
        return 'unknown'

    parts = remote_url.rstrip('.git').split('/')
    return parts[-1] if parts else 'unknown'


def _get_commit_details(commit_sha: str) -> tuple:
    """Get commit message, timestamp, author name and email."""
    defaults = (
        'Unknown commit message',
        datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'Unknown',
        'unknown@example.com'
    )

    if not commit_sha:
        return defaults

    commit_message = (
        run_git_command(['log', '-1', '--pretty=format:%B', commit_sha]) or
        defaults[0]
    )
    commit_timestamp = (
        run_git_command(['log', '-1', '--pretty=format:%cI', commit_sha]) or
        defaults[1]
    )
    author_name = (
        run_git_command(['log', '-1', '--pretty=format:%an', commit_sha]) or
        defaults[2]
    )
    author_email = (
        run_git_command(['log', '-1', '--pretty=format:%ae', commit_sha]) or
        defaults[3]
    )

    return commit_message, commit_timestamp, author_name, author_email


def detect_git_metadata(include_ancestry: bool = True) -> Dict[str, Any]:
    """
    Detect Git metadata from local git repository.

    Runs git commands to extract commit SHA, branch name, author info, etc.
    This works in any git repository without requiring GitHub Actions environment.

    Args:
        include_ancestry: Also collect the first-parent ancestry line from
            HEAD (metadata.git.ancestry). detect_github_metadata passes
            False and collects it from the commit the upload will report.

    Returns:
        Dict with metadata in metadata['git'] format:
        {
            'commit_hash': str,
            'base_commit_hash': str,    # Parent commit (HEAD~1)
            'branch_name': str,
            'repository': str,
            'commit_message': str,
            'commit_timestamp': str,
            'author_name': str,
            'author_email': str,
            'pr_number': None,          # Not available from git alone
            'pr_name': None,
            'pr_author_name': None,
            'pr_author_email': None,
            'ancestry': [str, ...]      # Only when non-empty
        }
    """
    # Get commit SHA
    commit_sha = run_git_command(['rev-parse', 'HEAD']) or ''

    # Get parent commit
    parent_sha = get_parent_commit()

    # Get branch name
    branch_name = _get_branch_name('')

    # Get repo name
    repo_name = _get_repo_name()

    # Get commit details
    commit_message, commit_timestamp, author_name, author_email = _get_commit_details(commit_sha)

    # Get tags if commit is tagged
    tags = get_commit_tags(commit_sha)

    metadata = {
        'commit_hash': commit_sha or None,
        'base_commit_hash': parent_sha or None,
        'branch_name': branch_name or None,
        'repository': repo_name or None,
        'commit_message': commit_message or None,
        'commit_timestamp': commit_timestamp or None,
        'author_name': author_name or None,
        'author_email': author_email or None,
        'tags': tags,
        'pr_number': None,
        'pr_name': None,
        'pr_author_name': None,
        'pr_author_email': None
    }

    if include_ancestry and commit_sha:
        ancestry = get_ancestry(commit_sha)
        if ancestry:
            metadata['ancestry'] = ancestry

    return metadata


def _build_metadata_result(
    git_context: GitContext,
    commit_details: tuple,
    pr_info: tuple
) -> Dict[str, Any]:
    """Build the metadata result dictionary."""
    commit_message, commit_timestamp, author_name, author_email = commit_details
    pr_number, pr_name, pr_author_name, pr_author_email = pr_info

    tags = get_commit_tags(git_context.commit_sha)

    return {
        'commit_hash': git_context.commit_sha or None,
        'base_commit_hash': git_context.parent_sha or None,
        'branch_name': git_context.branch_name or None,
        'repository': git_context.repo_name or None,
        'commit_message': commit_message or None,
        'commit_timestamp': commit_timestamp or None,
        'author_name': author_name or None,
        'author_email': author_email or None,
        'tags': tags,
        'pr_number': pr_number or None,
        'pr_name': pr_name or None,
        'pr_author_name': pr_author_name or None,
        'pr_author_email': pr_author_email or None
    }


def detect_github_metadata() -> Dict[str, Any]:
    """
    Detect Git metadata from GitHub Actions environment.

    Combines GitHub-specific data (from environment variables and event payload)
    with git command data. GitHub-specific values override git values where available.

    Returns:
        Dict with metadata in metadata['git'] format:
        {
            'commit_hash': str,
            'base_commit_hash': str,    # Parent commit (HEAD~1)
            'branch_name': str,
            'repository': str,
            'commit_message': str,
            'commit_timestamp': str,
            'author_name': str,
            'author_email': str,
            'pr_number': str,
            'pr_name': str,
            'pr_author_name': str,      # PR author (user who opened the PR)
            'pr_author_email': str      # PR author email (if available)
        }
    """
    # Start with git metadata as base. Ancestry is collected below, from the
    # commit the upload will actually report rather than from git HEAD.
    metadata = detect_git_metadata(include_ancestry=False)

    # Get GitHub environment variables
    event_name = os.environ.get('GITHUB_EVENT_NAME', '')
    commit_sha = os.environ.get('GITHUB_SHA', '')
    event_path = os.environ.get('GITHUB_EVENT_PATH', '')

    # Parse event payload if available
    (base_sha, branch_name, pr_number, head_sha, pr_name,
     pr_author_name, pr_author_email) = _parse_github_event(event_name, event_path)

    # For pull_request events, use the PR head SHA instead of the merge commit SHA
    # GITHUB_SHA points to a temporary merge commit in PR events, not the actual commit.
    # For workflow_run events GITHUB_SHA is the default branch tip, not the
    # commit the triggering run built; the payload's head_sha is.
    if event_name in ('pull_request', 'workflow_run') and head_sha:
        commit_sha = head_sha

    # Override with GitHub-specific values where available
    if commit_sha:
        metadata['commit_hash'] = commit_sha
        # Re-fetch commit details and tag for the GitHub commit SHA
        (commit_message, commit_timestamp,
         author_name, author_email) = _get_commit_details(commit_sha)
        metadata['commit_message'] = commit_message
        metadata['commit_timestamp'] = commit_timestamp
        metadata['author_name'] = author_name
        metadata['author_email'] = author_email
        metadata['tags'] = get_commit_tags(commit_sha)

    if branch_name:
        metadata['branch_name'] = branch_name

    # Use the event's base_sha as the parent instead of the git parent (HEAD~1):
    #   * pull_request -> pr.base.sha (the PR target tip)
    #   * push         -> event 'before' (the branch tip prior to this push)
    # For push this matters on multi-commit pushes: GitHub fires a single event
    # for the tip, so the tip's git parent is an intermediate commit that never
    # built. Basing on 'before' (the previous built tip) bridges over those
    # unbuilt intermediates and keeps the report chain intact. The all-zero
    # 'before' (branch creation / first push) is not a real commit, so skip it
    # and let the git parent stand. Guard against malformed event payloads by
    # only accepting a well-formed 40-hex SHA.
    if event_name in ('pull_request', 'push', 'workflow_run') and _is_full_sha1(base_sha) \
            and base_sha != _ZERO_SHA:
        metadata['base_commit_hash'] = base_sha

    # First-parent ancestry for the core's commit graph. A PR upload is based
    # on the target branch tip, so its line must walk the target branch, not
    # the PR branch: start at the PR base. Everything else starts at the
    # commit the upload reports (which passes through 'before' on a normal
    # push, so a multi-commit push's intermediates land in the graph too).
    if pr_number and _is_full_sha1(base_sha):
        ancestry_start = base_sha
    else:
        ancestry_start = commit_sha or metadata.get('commit_hash') or ''
    ancestry = get_ancestry(ancestry_start)
    if ancestry:
        metadata['ancestry'] = ancestry

    # Add PR-specific metadata
    if pr_number:
        metadata['pr_number'] = pr_number
    if pr_name:
        metadata['pr_name'] = pr_name
    if pr_author_name:
        metadata['pr_author_name'] = pr_author_name
    if pr_author_email:
        metadata['pr_author_email'] = pr_author_email

    return metadata


def get_commit_metadata(commit_sha: str) -> Dict[str, Any]:
    """
    Get metadata for a specific commit.

    Args:
        commit_sha: Git commit SHA

    Returns:
        Dictionary with commit metadata.
    """
    metadata = {
        'commit_sha': commit_sha,
        'parent_sha': None,
        'commit_message': 'Unknown commit message',
        'commit_timestamp': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'author_name': 'Unknown',
        'author_email': 'unknown@example.com',
        'tags': [],
    }

    # Get parent commit
    parent_sha = run_git_command(['rev-parse', f'{commit_sha}~1'])
    if parent_sha:
        metadata['parent_sha'] = parent_sha

    # Get commit message (full message body)
    msg = run_git_command(['log', '-1', '--pretty=format:%B', commit_sha])
    if msg:
        metadata['commit_message'] = msg

    # Get commit timestamp
    ts = run_git_command(['log', '-1', '--pretty=format:%cI', commit_sha])
    if ts:
        metadata['commit_timestamp'] = ts

    # Get commit author name
    auth_name = run_git_command(['log', '-1', '--pretty=format:%an', commit_sha])
    if auth_name:
        metadata['author_name'] = auth_name

    # Get commit author email
    auth_email = run_git_command(['log', '-1', '--pretty=format:%ae', commit_sha])
    if auth_email:
        metadata['author_email'] = auth_email

    # Get tags if commit is tagged
    metadata['tags'] = get_commit_tags(commit_sha)

    return metadata
