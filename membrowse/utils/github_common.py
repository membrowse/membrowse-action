"""Common GitHub utilities shared between comment modules."""

import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

# Timeout constants for subprocess calls (in seconds)
GH_VERSION_TIMEOUT = 5
GH_COMMENT_TIMEOUT = 30


def is_gh_cli_available() -> bool:
    """Check if GitHub CLI (gh) is available and executable."""
    try:
        subprocess.run(
            ['gh', '--version'],
            check=True,
            capture_output=True,
            timeout=GH_VERSION_TIMEOUT
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def get_pr_number(pr_number: Optional[str] = None) -> str:
    """
    Get PR number from provided value.

    Args:
        pr_number: PR number (e.g., from JSON report file)

    Returns:
        str: PR number

    Raises:
        ValueError: If PR number is not provided or invalid
    """
    if not pr_number:
        raise ValueError("PR number is required")

    pr_str = str(pr_number).strip()
    if not pr_str.isdigit():
        raise ValueError(f"Invalid PR number: {pr_number}")

    return pr_str


def create_comment(body: str, pr_number: Optional[str] = None) -> None:
    """
    Create a new PR comment using GitHub CLI.

    Args:
        body: The markdown content for the comment
        pr_number: Optional PR number override (for workflow_run context)

    Raises:
        subprocess.CalledProcessError: If gh command fails
        ValueError: If PR number cannot be determined
    """
    pr_num = get_pr_number(pr_number)

    subprocess.run(
        ['gh', 'pr', 'comment', pr_num, '--body', body],
        check=True,
        capture_output=True,
        timeout=GH_COMMENT_TIMEOUT
    )


def build_memory_change_row(region: dict) -> Optional[dict]:
    """
    Build a single table row for memory changes.

    Args:
        region: Region data with current and old values

    Returns:
        dict: Row data with formatted strings, or None if no changes
    """
    current_used = region.get('used_size', 0)
    old_data = region.get('old', {})
    old_used = old_data.get('used_size')

    # Only show if used_size changed
    if old_used is None or old_used == current_used:
        return None

    # Calculate delta
    delta = current_used - old_used
    delta_pct = (delta / old_used * 100) if old_used > 0 else 0

    # Format delta with sign
    delta_str = f"+{delta:,}" if delta >= 0 else f"{delta:,}"
    delta_pct_str = f"+{delta_pct:.1f}%" if delta >= 0 else f"{delta_pct:.1f}%"

    return {
        'delta': delta,
        'delta_str': delta_str,
        'delta_pct_str': delta_pct_str,
        'current_used': current_used,
        'region_name': region.get('name', 'Unknown'),
        'limit_size': region.get('limit_size', 0)
    }


def handle_comment_error(error: Exception, context: str = "PR comment") -> None:
    """
    Handle errors from comment creation with consistent logging.

    Args:
        error: The exception that occurred
        context: Description of the operation for logging
    """
    if isinstance(error, subprocess.CalledProcessError):
        error_msg = f"Failed to post {context}: {error}"
        if error.stderr:
            stderr_output = (
                error.stderr.decode('utf-8') if isinstance(error.stderr, bytes)
                else error.stderr
            )
            error_msg += f"\ngh stderr: {stderr_output.strip()}"
        logger.warning(error_msg)
    else:
        logger.warning("Failed to post %s: %s", context, error)


def configure_logging() -> None:
    """Configure basic logging for main entry points."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )
