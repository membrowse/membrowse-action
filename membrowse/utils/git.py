"""Git metadata detection utilities."""

import os
import re
import subprocess
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse

import requests

from membrowse.utils import github_rest

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

# Timeouts for the ancestry fallbacks; the whole ancestry step is best-effort
# and must never stall an upload behind a hung remote or a credential prompt.
_ANCESTRY_HTTP_TIMEOUT = 15
_ANCESTRY_FETCH_TIMEOUT = 120


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


def run_git_command(command: list, timeout: Optional[float] = None,
                    env: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Run a git command and return stdout, or None on error or timeout.

    env adds to (or overrides) the inherited environment for this call only.
    """
    try:
        result = subprocess.run(
            ['git'] + command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env={**os.environ, **env} if env else None,
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


def _is_shallow_repository() -> bool:
    """True when the checkout is shallow, so a short rev-list may be truncated.

    A CI checkout at fetch-depth 2 yields exactly two entries, which is not
    "the whole history" but is not one entry either; only shallowness tells
    the two apart from a genuinely short repository.
    """
    return (run_git_command(['rev-parse', '--is-shallow-repository']) or '').strip() == 'true'


def _deepen_history(start_sha: str, shallow: bool) -> bool:
    """Fetch the commits leading to start_sha so `git rev-list` can walk them.

    actions/checkout defaults to fetch-depth 1, so `git rev-list` alone yields
    one commit; a shallow checkout deepens to ANCESTRY_DEPTH. A full clone
    that merely lacks the commit (a workflow_run job on the default branch
    reporting a feature-branch head) fetches it outright, since `--depth`
    would turn the full clone shallow. The checkout's persisted credentials
    cover private repositories.

    No object filter: a filtered fetch registers origin as a promisor remote
    and git then applies the filter to every later fetch in that checkout, so
    a reused runner workspace would lazy-fetch trees and blobs one at a time
    from then on. The unfiltered cost is a few hundred commits of deltas
    against objects already local. Bounded, and never prompts for credentials.
    """
    command = ['fetch', '--no-tags']
    if shallow:
        command.append(f'--depth={ANCESTRY_DEPTH}')
    command += ['origin', start_sha]
    result = run_git_command(command, timeout=_ANCESTRY_FETCH_TIMEOUT,
                             env={'GIT_TERMINAL_PROMPT': '0'})
    return result is not None


def _github_api_ancestry(start_sha: str) -> List[str]:
    """First-parent line via the GitHub REST API, for checkouts that cannot
    fetch (persist-credentials: false). Needs GITHUB_REPOSITORY and a token.

    The commits listing is not first-parent only, so the line is rebuilt from
    each commit's `parents` by following the first parent through the pages.
    """
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    token = github_rest.get_token()
    if not repo or not token:
        return []

    host = urlparse(os.environ.get('GITHUB_SERVER_URL', '')).hostname or ''
    first_parent = _github_api_first_parents(
        github_rest.api_base(host), repo, token, start_sha)
    line: List[str] = []
    current: Optional[str] = start_sha.lower()
    while current and current in first_parent and len(line) < ANCESTRY_DEPTH:
        line.append(current)
        current = first_parent[current]
    return line


def _github_api_first_parents(
        api: str, repo: str, token: str, start_sha: str) -> Dict[str, Optional[str]]:
    """sha -> first parent for up to two pages of the commits listing."""
    headers = github_rest.auth_headers(token)
    first_parent: Dict[str, Optional[str]] = {}
    for page in (1, 2):
        try:
            resp = requests.get(
                f'{api}/repos/{repo}/commits',
                params={'sha': start_sha, 'per_page': 100, 'page': page},
                headers=headers, timeout=_ANCESTRY_HTTP_TIMEOUT)
            if resp.status_code != 200:
                logger.debug("Ancestry API returned %s", resp.status_code)
                return {}
            commits = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.debug("Ancestry API request failed: %s", exc)
            return {}
        if not isinstance(commits, list) or not commits:
            break
        for commit in commits:
            if not isinstance(commit, dict):
                continue
            sha = str(commit.get('sha', '')).lower()
            parents = commit.get('parents') or []
            parent = str(parents[0].get('sha', '')).lower() if parents else None
            if _is_full_sha1(sha):
                first_parent[sha] = parent if _is_full_sha1(parent or '') else None
        if len(commits) < 100:
            break
    return first_parent


def get_ancestry(start_sha: str, fetch: bool = True) -> List[str]:
    """The first-parent line from start_sha, newest first, up to ANCESTRY_DEPTH.

    Each entry's first parent is the next entry; the last entry's parent is
    unknown (the list is truncated). Every step is best-effort and logged at
    debug: ancestry collection must never fail an upload. Returns whatever was
    learned, possibly just start_sha, possibly nothing.

    Fallback order: local `git rev-list`, which is final when it yields the
    full depth, or anything at all from a non-shallow repository (a short
    line from a full clone IS the whole history); otherwise a fetch (skipped
    when fetch=False, e.g. onboard's full clone, or when start_sha is not a
    full SHA); otherwise the GitHub REST API; otherwise whatever is local. A
    CI checkout at fetch-depth 1 or 2 is the common case and must deepen; a
    full clone that lacks the reported commit altogether must fetch it.
    """
    if not start_sha:
        return []
    try:
        line = _rev_list_first_parent(start_sha)
        if len(line) >= ANCESTRY_DEPTH:
            return line
        if fetch and _is_full_sha1(start_sha):
            line = _extend_ancestry(start_sha, line)
        if len(line) < 2:
            logger.debug("Ancestry for %s limited to %d entries", start_sha, len(line))
        return line
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("Ancestry collection failed for %s: %s", start_sha, exc)
        return []


def _extend_ancestry(start_sha: str, line: List[str]) -> List[str]:
    """Lengthen a truncated local line by fetching, then via the GitHub API.

    Never returns less than `line`: a fallback that blows up must not throw
    away what `git rev-list` already produced.
    """
    shallow = _is_shallow_repository()
    if line and not shallow:
        return line
    if _deepen_history(start_sha, shallow):
        deeper = _rev_list_first_parent(start_sha)
        if len(deeper) > len(line):
            line = deeper
        if len(line) >= ANCESTRY_DEPTH or (line and not _is_shallow_repository()):
            return line
    else:
        logger.debug("Could not fetch history for %s", start_sha)
    try:
        api_line = _github_api_ancestry(start_sha)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("Ancestry API fallback failed for %s: %s", start_sha, exc)
        return line
    return api_line if len(api_line) > len(line) else line


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


@dataclass
class GitHubEvent:  # pylint: disable=too-many-instance-attributes
    """What a GitHub event payload says about the commit being reported.

    Every field is optional; an empty value means "not in this event" and
    the git-derived value stands.
    """
    base_sha: str = ''
    branch_name: str = ''
    pr_number: str = ''
    head_sha: str = ''
    pr_name: str = ''
    pr_author_name: str = ''
    pr_author_email: str = ''
    # push only: the ref was force-updated (GitHub's `forced`). The core holds
    # a branch head on a commit already in its history, since that is what a
    # CI re-run of an old commit looks like; a forced push says the branch
    # really was reset to that commit. A re-run replays the original push
    # payload, so it never reports forced for a normal push.
    forced: bool = False


def _parse_pull_request_event(event_data: Dict[str, Any]) -> GitHubEvent:
    """Extract metadata from pull request event."""
    pr = event_data.get('pull_request', {})
    return GitHubEvent(
        base_sha=pr.get('base', {}).get('sha', ''),
        branch_name=pr.get('head', {}).get('ref', ''),
        pr_number=str(pr.get('number', '')),
        head_sha=pr.get('head', {}).get('sha', ''),
        pr_name=pr.get('title', ''),
        # PR author (user who opened the PR). GitHub does not expose the
        # email for privacy; the login stands in.
        pr_author_name=pr.get('user', {}).get('login', ''),
    )


def _parse_workflow_run_event(event_data: Dict[str, Any]) -> GitHubEvent:
    """Extract metadata from a workflow_run event.

    On workflow_run, GITHUB_SHA is the DEFAULT branch's last commit, not the
    commit the triggering run built, so a job that checks out
    workflow_run.head_sha would otherwise report (and overwrite) the default
    branch tip. The payload carries the real head and, for PR-triggered runs,
    the PR number and base.
    """
    run = event_data.get('workflow_run', {}) or {}
    event = GitHubEvent(
        head_sha=run.get('head_sha', '') or '',
        branch_name=run.get('head_branch', '') or '',
    )
    pull_requests = run.get('pull_requests') or []
    if pull_requests:
        pr = pull_requests[0] or {}
        event.pr_number = str(pr.get('number', '') or '')
        event.base_sha = (pr.get('base') or {}).get('sha', '') or ''
    return event


def _parse_push_event(event_data: Dict[str, Any]) -> GitHubEvent:
    """Extract metadata from push event (no PR fields on a push)."""
    return GitHubEvent(
        base_sha=event_data.get('before', ''),
        # Try to get branch from git, fall back to env var
        branch_name=(
            run_git_command(['symbolic-ref', '--short', 'HEAD']) or
            run_git_command(['for-each-ref', '--points-at', 'HEAD',
                             '--format=%(refname:short)', 'refs/heads/']) or
            os.environ.get('GITHUB_REF_NAME', 'unknown')
        ),
        forced=bool(event_data.get('forced')),
    )


_EVENT_PARSERS = {
    'pull_request': _parse_pull_request_event,
    'push': _parse_push_event,
    'workflow_run': _parse_workflow_run_event,
}


def _parse_github_event(event_name: str, event_path: str) -> GitHubEvent:
    """Parse the GitHub event payload; an empty event when it cannot be read."""
    parser = _EVENT_PARSERS.get(event_name)
    if not parser or not event_path or not os.path.exists(event_path):
        return GitHubEvent()
    try:
        with open(event_path, 'r', encoding='utf-8') as f:
            return parser(json.load(f))
    except Exception:  # pylint: disable=broad-exception-caught
        return GitHubEvent()


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

    event = _parse_github_event(event_name, event_path)

    # For pull_request events, use the PR head SHA instead of the merge commit SHA
    # GITHUB_SHA points to a temporary merge commit in PR events, not the actual commit.
    # For workflow_run events GITHUB_SHA is the default branch tip, not the
    # commit the triggering run built; the payload's head_sha is.
    if event_name in ('pull_request', 'workflow_run') and event.head_sha:
        commit_sha = event.head_sha

    # Ancestry first: its fetch is what makes the reported commit local when
    # the checkout does not have it (a pull_request checkout at fetch-depth 1
    # holds only the merge ref; a workflow_run job holds the default branch),
    # and the commit details and parent below need the object.
    _attach_ancestry(metadata, commit_sha)

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

    if event.branch_name:
        metadata['branch_name'] = event.branch_name

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
    if event_name in ('pull_request', 'push', 'workflow_run') \
            and _is_full_sha1(event.base_sha) and event.base_sha != _ZERO_SHA:
        metadata['base_commit_hash'] = event.base_sha
    elif event_name == 'workflow_run' and commit_sha:
        # No PR in the payload (always so for fork PRs and for push-triggered
        # runs): the base is the reported commit's own parent. HEAD~1 is the
        # parent of whatever the job checked out, which per the documented
        # workflow_run pattern is the default branch, not head_sha.
        metadata['base_commit_hash'] = _first_parent(commit_sha, metadata.get('ancestry'))

    if event.forced and _is_first_run_attempt():
        metadata['forced'] = True

    # Add PR-specific metadata
    if event.pr_number:
        metadata['pr_number'] = event.pr_number
    if event.pr_name:
        metadata['pr_name'] = event.pr_name
    if event.pr_author_name:
        metadata['pr_author_name'] = event.pr_author_name
    if event.pr_author_email:
        metadata['pr_author_email'] = event.pr_author_email

    return metadata


def _is_first_run_attempt() -> bool:
    """False on a GitHub re-run, which replays the original push payload.

    A forced push's `forced` is a statement about the ref at that moment.
    After a reset to A and a later push to B, re-running A's workflow would
    send forced=True again and let the core reset the branch head back to
    A. Only the first attempt may pass the flag on; a re-run of a forced
    push is an ordinary upload, which the core holds in place.
    """
    return os.environ.get('GITHUB_RUN_ATTEMPT', '1').strip() in ('', '1')


def _first_parent(commit_sha: str, ancestry: Optional[List[str]]) -> Optional[str]:
    """The first parent of commit_sha: from git, else from the ancestry line
    (which the GitHub API may have supplied when the commit is not local),
    else unknown. Never some other commit's parent."""
    parent = run_git_command(['rev-parse', f'{commit_sha}~1'])
    if _is_full_sha1(parent or ''):
        return parent
    if ancestry and len(ancestry) > 1 and ancestry[0] == commit_sha.lower():
        return ancestry[1]
    return None


def _attach_ancestry(metadata: Dict[str, Any], commit_sha: str) -> None:
    """Add the first-parent ancestry for the core's commit graph.

    Always from the commit the upload reports. On a push that line passes
    through 'before', so a multi-commit push's intermediates land in the
    graph; on a PR it is the PR branch, which is what lets the core tell a
    re-run of an older PR commit from a new one and hold the PR head. The base
    branch's own line reaches the graph through the base branch's pushes.
    """
    ancestry = get_ancestry(commit_sha or metadata.get('commit_hash') or '')
    if ancestry:
        metadata['ancestry'] = ancestry


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
