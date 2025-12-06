"""GitHub fork PR detection and context extraction for tokenless uploads."""

import os
import json
import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class ForkPRContext:
    """Context information for fork PR uploads."""
    pr_number: int
    fork_repo_full_name: str  # e.g., "user/repo" (where PR comes from)
    base_repo_full_name: str  # e.g., "org/repo" (where PR targets)
    head_sha: str
    pr_author_login: str
    branch_name: str


def _read_github_event() -> Optional[Dict[str, Any]]:
    """
    Read and parse the GitHub event payload.

    Returns:
        Parsed event data dict, or None if not available
    """
    event_path = os.environ.get('GITHUB_EVENT_PATH', '')
    if not event_path or not os.path.exists(event_path):
        return None

    try:
        with open(event_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.debug("Failed to read GitHub event file: %s", e)
        return None


def is_fork_pr() -> bool:
    """
    Detect if this is a pull request from a forked repository.

    Returns:
        True if this is a fork PR, False otherwise

    Note:
        Returns False on any error for graceful degradation.
        Requires GITHUB_EVENT_NAME='pull_request' and GITHUB_EVENT_PATH
        environment variables from GitHub Actions.
    """
    # Check if we're in a PR event
    event_name = os.environ.get('GITHUB_EVENT_NAME', '')
    if event_name != 'pull_request':
        logger.debug("Not a pull request event (event_name=%s)", event_name)
        return False

    # Parse event payload
    event_data = _read_github_event()
    if not event_data:
        logger.debug("Cannot read GitHub event payload")
        return False

    try:
        pr_data = event_data.get('pull_request', {})
        # Note: head.repo can be None if the fork repository was deleted
        head_repo = pr_data.get('head', {}).get('repo')
        base_repo = pr_data.get('base', {}).get('repo')

        # Handle case where fork repository was deleted (head.repo is null)
        if not head_repo or not base_repo:
            logger.debug("head_repo or base_repo is null (fork may have been deleted)")
            return False

        # Check if PR is from a fork by comparing repository full names
        head_repo_name = head_repo.get('full_name', '')
        base_repo_name = base_repo.get('full_name', '')

        is_fork = head_repo_name != base_repo_name and bool(head_repo_name) and bool(base_repo_name)

        logger.debug(
            "Fork PR detection: head_repo=%s, base_repo=%s, is_fork=%s",
            head_repo_name, base_repo_name, is_fork
        )
        return is_fork

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.debug("Failed to detect fork PR: %s", e)
        return False


def get_fork_pr_context() -> ForkPRContext:
    """
    Extract GitHub PR context for tokenless upload authentication.

    Returns:
        ForkPRContext with required fields for tokenless upload

    Raises:
        ValueError: If not in fork PR context or required fields missing
    """
    # Reuse helper function to read event file
    event_data = _read_github_event()
    if not event_data:
        raise ValueError(
            "Cannot extract fork PR context: GITHUB_EVENT_PATH not found or invalid. "
            "This feature only works in GitHub Actions pull_request events."
        )

    # Extract pull request data
    pr_data = event_data.get('pull_request')
    if not pr_data:
        raise ValueError(
            "Cannot extract fork PR context: No pull_request data in event payload"
        )

    # Extract repository data (note: head.repo can be None if fork was deleted)
    base_repo = pr_data.get('base', {}).get('repo')
    head_repo = pr_data.get('head', {}).get('repo')
    user_data = pr_data.get('user', {})

    # Handle case where fork repository was deleted
    if not base_repo:
        raise ValueError(
            "Cannot extract fork PR context: base_repo is null in event payload"
        )

    base_repo_full_name = base_repo.get('full_name')
    # head_repo can be None if fork was deleted - use base_repo as fallback
    fork_repo_full_name = head_repo.get('full_name') if head_repo else None
    pr_number = pr_data.get('number')
    pr_author_login = user_data.get('login')
    head_sha = pr_data.get('head', {}).get('sha')
    branch_name = pr_data.get('head', {}).get('ref', 'unknown')

    # Validate required fields
    required_fields = {
        'base_repo_full_name': base_repo_full_name,
        'pr_number': pr_number,
        'pr_author_login': pr_author_login,
        'head_sha': head_sha
    }

    missing = [k for k, v in required_fields.items() if not v]
    if missing:
        raise ValueError(
            f"Cannot extract fork PR context: Missing required fields: {', '.join(missing)}"
        )

    # Log warning if fork repo is missing (deleted fork)
    if not fork_repo_full_name:
        logger.warning(
            "Fork repository appears to be deleted, using base repo name as fallback"
        )

    return ForkPRContext(
        pr_number=pr_number,
        fork_repo_full_name=fork_repo_full_name or base_repo_full_name,
        base_repo_full_name=base_repo_full_name,
        head_sha=head_sha,
        pr_author_login=pr_author_login,
        branch_name=branch_name
    )
