"""GitHub PR comment backend (REST API).

Used outside GitHub Actions (e.g. CircleCI) where the ``gh`` CLI and its repo
auto-detection are not available. Comments are created or updated directly
against the GitHub REST API. Part of the provider-agnostic comment layer in
``vcs_comment`` — each backend exposes the same interface:

    get_token() -> str
    is_configured() -> bool
    create_or_update_comment(host, owner, repo, pr_number, body, marker) -> None
"""

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30


def get_token() -> str:
    """Return the GitHub token (GITHUB_TOKEN, GH_TOKEN, or MEMBROWSE_VCS_TOKEN)."""
    return (
        os.environ.get('GITHUB_TOKEN')
        or os.environ.get('GH_TOKEN')
        or os.environ.get('MEMBROWSE_VCS_TOKEN')
        or ''
    )


def is_configured() -> bool:
    """True if a usable GitHub token is present in the environment."""
    return bool(get_token())


def api_base(host: str) -> str:
    """Resolve the GitHub API base URL, honoring GitHub Enterprise hosts."""
    override = os.environ.get('GITHUB_API_URL')
    if override:
        return override.rstrip('/')
    if not host or host == 'github.com':
        return 'https://api.github.com'
    # GitHub Enterprise Server
    return f'https://{host}/api/v3'


def auth_headers(token: str) -> dict:
    """Authorization and API-version headers for a GitHub REST request."""
    return {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }


def find_existing_comment(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    base: str, owner: str, repo: str, pr_number: str, marker: str, token: str
) -> Optional[int]:
    """Return the ID of an existing comment containing ``marker``, or None."""
    url = f'{base}/repos/{owner}/{repo}/issues/{pr_number}/comments'
    headers = auth_headers(token)
    params = {'per_page': 100}
    try:
        while url:
            resp = requests.get(
                url, headers=headers, params=params, timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            for comment in resp.json():
                if marker in (comment.get('body') or ''):
                    return comment['id']
            url = resp.links.get('next', {}).get('url')
            params = None
        return None
    except requests.RequestException as e:
        logger.debug("Failed to list PR comments: %s", e)
        return None


def create_or_update_comment(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    host: str, owner: str, repo: str, pr_number: str, body: str, marker: str
) -> None:
    """Create a new PR comment, or update the existing one carrying ``marker``."""
    token = get_token()
    base = api_base(host)
    existing_id = find_existing_comment(base, owner, repo, pr_number, marker, token)
    if existing_id:
        logger.debug("Updating existing GitHub comment %d", existing_id)
        url = f'{base}/repos/{owner}/{repo}/issues/comments/{existing_id}'
        resp = requests.patch(
            url, headers=auth_headers(token), json={'body': body}, timeout=REQUEST_TIMEOUT
        )
    else:
        logger.debug("Creating new GitHub comment on PR #%s", pr_number)
        url = f'{base}/repos/{owner}/{repo}/issues/{pr_number}/comments'
        resp = requests.post(
            url, headers=auth_headers(token), json={'body': body}, timeout=REQUEST_TIMEOUT
        )
    resp.raise_for_status()
