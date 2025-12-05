"""Authentication strategy implementation for MemBrowse API."""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Any

from ..utils.github import is_fork_pr, get_fork_pr_context, ForkPRContext

logger = logging.getLogger(__name__)


class AuthType(Enum):
    """Supported authentication types for MemBrowse API."""
    API_KEY = "api-key"
    GITHUB_TOKENLESS = "github-tokenless"


@dataclass
class AuthContext:
    """Authentication context for API uploads."""
    auth_type: AuthType
    api_key: Optional[str] = None
    github_context: Optional[Dict[str, Any]] = field(default=None)

    def build_headers(self) -> Dict[str, str]:
        """
        Build authentication headers based on auth type.

        Returns:
            Dict of HTTP headers for authentication
        """
        headers: Dict[str, str] = {
            'Content-Type': 'application/json'
        }

        if self.auth_type == AuthType.API_KEY:
            if not self.api_key:
                raise ValueError("API key required for API_KEY auth type")
            headers['Authorization'] = f'Bearer {self.api_key}'
        elif self.auth_type == AuthType.GITHUB_TOKENLESS:
            headers['X-Auth-Type'] = 'github-tokenless'

        return headers

    def get_metadata_additions(self) -> Dict[str, Any]:
        """
        Get additional metadata fields to include in upload request.

        Returns:
            Dict of metadata fields to add (e.g., github_context for tokenless)
        """
        if self.auth_type == AuthType.GITHUB_TOKENLESS and self.github_context:
            return {'github_context': self.github_context}
        return {}


def _fork_context_to_dict(fork_context: ForkPRContext) -> Dict[str, Any]:
    """Convert ForkPRContext dataclass to dict for API payload."""
    return {
        'pr_number': fork_context.pr_number,
        'fork_repository': fork_context.fork_repo_full_name,
        'repository': fork_context.base_repo_full_name,
        'commit_sha': fork_context.head_sha,
        'pr_author': fork_context.pr_author_login,
        'branch_name': fork_context.branch_name
    }


def determine_auth_strategy(
    api_key: Optional[str],
    auto_detect_fork: bool = False
) -> AuthContext:
    """
    Determine authentication strategy based on inputs.

    Args:
        api_key: Optional API key for standard authentication
        auto_detect_fork: Whether to auto-detect fork PR context (enabled by --github flag)

    Returns:
        AuthContext with determined strategy and credentials

    Raises:
        ValueError: If authentication cannot be determined
    """
    # If API key provided, always use standard auth
    if api_key:
        logger.debug("Using API key authentication")
        return AuthContext(
            auth_type=AuthType.API_KEY,
            api_key=api_key
        )

    # If auto-detect enabled and we're in fork PR, use tokenless
    if auto_detect_fork and is_fork_pr():
        logger.info("Fork PR detected, using tokenless upload mode")
        try:
            fork_context = get_fork_pr_context()
            github_context = _fork_context_to_dict(fork_context)
            logger.debug("Fork PR context: %s", github_context)
            return AuthContext(
                auth_type=AuthType.GITHUB_TOKENLESS,
                github_context=github_context
            )
        except ValueError as e:
            raise ValueError(
                f"Failed to extract fork PR context for tokenless upload: {e}"
            ) from e

    # No valid authentication available
    error_msg = "--api-key is required when using --upload or --github"
    if auto_detect_fork:
        error_msg += (
            ". For fork PRs to public repositories, "
            "api_key can be omitted to use tokenless upload."
        )
    raise ValueError(error_msg)
