"""Git metadata detection utilities."""

import os
import subprocess
import json
from datetime import datetime
from typing import Optional, Dict, Any


class GitMetadata:  # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """Container for Git metadata."""

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        commit_sha: Optional[str] = None,
        base_sha: Optional[str] = None,
        branch_name: Optional[str] = None,
        repo_name: Optional[str] = None,
        commit_message: Optional[str] = None,
        commit_timestamp: Optional[str] = None,
        author_name: Optional[str] = None,
        author_email: Optional[str] = None,
        pr_number: Optional[str] = None
    ):
        self.commit_sha = commit_sha
        self.base_sha = base_sha
        self.branch_name = branch_name
        self.repo_name = repo_name
        self.commit_message = commit_message
        self.commit_timestamp = commit_timestamp
        self.author_name = author_name
        self.author_email = author_email
        self.pr_number = pr_number


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


def detect_github_metadata() -> GitMetadata:  # pylint: disable=too-many-locals
    """
    Detect Git metadata from GitHub Actions environment.

    Reads GitHub environment variables and event payload to extract
    commit SHA, branch name, PR number, etc.

    Returns:
        GitMetadata object with detected information
    """
    # Get GitHub environment variables
    event_name = os.environ.get('GITHUB_EVENT_NAME', '')
    commit_sha = os.environ.get('GITHUB_SHA', '')
    event_path = os.environ.get('GITHUB_EVENT_PATH', '')

    base_sha = ''
    branch_name = ''
    pr_number = ''

    # Parse event payload if available
    if event_path and os.path.exists(event_path):
        try:
            with open(event_path, 'r', encoding='utf-8') as f:
                event_data = json.load(f)

            if event_name == 'pull_request':
                base_sha = event_data.get(
                    'pull_request',
                    {}).get(
                    'base',
                    {}).get(
                    'sha',
                    '')
                branch_name = event_data.get(
                    'pull_request',
                    {}).get(
                    'head',
                    {}).get(
                    'ref',
                    '')
                pr_number = str(
                    event_data.get(
                        'pull_request',
                        {}).get(
                        'number',
                        ''))
            elif event_name == 'push':
                base_sha = event_data.get('before', '')
                # Try to get branch from git, fall back to env var
                branch_name = (
                    run_git_command(['symbolic-ref', '--short', 'HEAD']) or
                    run_git_command(['for-each-ref', '--points-at', 'HEAD',
                                     '--format=%(refname:short)', 'refs/heads/']) or
                    os.environ.get('GITHUB_REF_NAME', 'unknown')
                )
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    # Fallback: detect from git if not from GitHub env
    if not commit_sha:
        commit_sha = run_git_command(['rev-parse', 'HEAD']) or ''

    if not branch_name:
        branch_name = (
            run_git_command(['symbolic-ref', '--short', 'HEAD']) or
            run_git_command(['for-each-ref', '--points-at', 'HEAD',
                             '--format=%(refname:short)', 'refs/heads/']) or
            'unknown'
        )

    # Get repository name from git remote
    repo_name = 'unknown'
    remote_url = run_git_command(['config', '--get', 'remote.origin.url'])
    if remote_url:
        # Extract repo name from URL like "https://github.com/user/repo.git"
        parts = remote_url.rstrip('.git').split('/')
        if parts:
            repo_name = parts[-1]

    # Get commit message, author, and timestamp
    commit_message = 'Unknown commit message'
    commit_timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    author_name = 'Unknown'
    author_email = 'unknown@example.com'

    if commit_sha:
        msg = run_git_command(['log', '-1', '--pretty=format:%B', commit_sha])
        if msg:
            commit_message = msg

        ts = run_git_command(['log', '-1', '--pretty=format:%cI', commit_sha])
        if ts:
            commit_timestamp = ts

        auth_name = run_git_command(
            ['log', '-1', '--pretty=format:%an', commit_sha])
        if auth_name:
            author_name = auth_name

        auth_email = run_git_command(
            ['log', '-1', '--pretty=format:%ae', commit_sha])
        if auth_email:
            author_email = auth_email

    return GitMetadata(
        commit_sha=commit_sha or None,
        base_sha=base_sha or None,
        branch_name=branch_name or None,
        repo_name=repo_name or None,
        commit_message=commit_message or None,
        commit_timestamp=commit_timestamp or None,
        author_name=author_name or None,
        author_email=author_email or None,
        pr_number=pr_number or None
    )


def get_commit_metadata(commit_sha: str) -> Dict[str, Any]:
    """
    Get metadata for a specific commit.

    Args:
        commit_sha: Git commit SHA

    Returns:
        Dictionary with commit metadata
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
