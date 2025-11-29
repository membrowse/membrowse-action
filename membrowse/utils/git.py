"""Git metadata detection utilities."""

import os
import subprocess
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any


@dataclass
class GitContext:
    """Git context information for metadata building."""
    commit_sha: str
    parent_sha: Optional[str]
    base_sha: str
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


def get_parent_commit() -> Optional[str]:
    """
    Get the parent commit SHA of the current HEAD.

    Returns:
        Parent commit SHA (HEAD~1), or None if no parent exists (first commit).
    """
    return run_git_command(['rev-parse', 'HEAD~1'])


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


def _build_metadata_result(
    git_context: GitContext,
    commit_details: tuple,
    pr_info: tuple
) -> Dict[str, Any]:
    """Build the metadata result dictionary."""
    commit_message, commit_timestamp, author_name, author_email = commit_details
    pr_number, pr_name, pr_author_name, pr_author_email = pr_info

    return {
        'commit_hash': git_context.commit_sha or None,
        'parent_commit_hash': git_context.parent_sha or None,
        'base_commit_hash': git_context.base_sha or None,
        'branch_name': git_context.branch_name or None,
        'repository': git_context.repo_name or None,
        'commit_message': commit_message or None,
        'commit_timestamp': commit_timestamp or None,
        'author_name': author_name or None,
        'author_email': author_email or None,
        'pr_number': pr_number or None,
        'pr_name': pr_name or None,
        'pr_author_name': pr_author_name or None,
        'pr_author_email': pr_author_email or None
    }


def detect_github_metadata() -> Dict[str, Any]:
    """
    Detect Git metadata from GitHub Actions environment.

    Reads GitHub environment variables and event payload to extract
    commit SHA, branch name, PR number, etc.

    Returns:
        Dict with metadata in metadata['git'] format:
        {
            'commit_hash': str,
            'parent_commit_hash': str,  # Actual git parent (HEAD~1)
            'base_commit_hash': str,    # For comparison (target branch in PRs, parent in pushes)
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
    # Get GitHub environment variables
    event_name = os.environ.get('GITHUB_EVENT_NAME', '')
    commit_sha = os.environ.get('GITHUB_SHA', '')
    event_path = os.environ.get('GITHUB_EVENT_PATH', '')

    # Parse event payload if available
    (base_sha, branch_name, pr_number, head_sha, pr_name,
     pr_author_name, pr_author_email) = _parse_github_event(event_name, event_path)

    # For pull_request events, use the PR head SHA instead of the merge commit SHA
    # GITHUB_SHA points to a temporary merge commit in PR events, not the actual commit
    if event_name == 'pull_request' and head_sha:
        commit_sha = head_sha

    # Fallback: detect from git if not from GitHub env
    commit_sha = commit_sha or run_git_command(['rev-parse', 'HEAD']) or ''
    branch_name = _get_branch_name(branch_name)

    # Get parent commit (actual git parent)
    parent_sha = get_parent_commit()

    # For push events, use parent commit as comparison base
    # For PR events, base_sha is already set to target branch tip
    if event_name == 'push' and parent_sha:
        base_sha = parent_sha

    git_context = GitContext(
        commit_sha=commit_sha,
        parent_sha=parent_sha,
        base_sha=base_sha,
        branch_name=branch_name,
        repo_name=_get_repo_name()
    )
    return _build_metadata_result(
        git_context=git_context,
        commit_details=_get_commit_details(commit_sha),
        pr_info=(pr_number, pr_name, pr_author_name, pr_author_email)
    )


def get_commit_metadata(commit_sha: str) -> Dict[str, Any]:
    """
    Get metadata for a specific commit.

    Args:
        commit_sha: Git commit SHA

    Returns:
        Dictionary with commit metadata (note: uses old key names for backwards compatibility)
        Use commit_sha, base_sha keys (not commit_hash, base_commit_hash)
    """
    metadata = {
        'commit_sha': commit_sha,
        'base_sha': None,
        'commit_message': 'Unknown commit message',
        'commit_timestamp': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'author_name': 'Unknown',
        'author_email': 'unknown@example.com',
    }

    # Get parent commit
    base_sha = run_git_command(['rev-parse', f'{commit_sha}~1'])
    if base_sha:
        metadata['base_sha'] = base_sha

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

    return metadata
