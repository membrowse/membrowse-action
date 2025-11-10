"""URL utilities for MemBrowse API endpoints."""

from typing import Optional


def normalize_api_url(base_url: str) -> str:
    """
    Normalize a base URL to a full MemBrowse API endpoint.

    Automatically appends '/api/upload' suffix to base URLs.
    Handles trailing slashes.

    Args:
        base_url: Base URL (e.g., 'https://www.membrowse.com')

    Returns:
        Full API endpoint URL with '/api/upload' suffix

    Examples:
        >>> normalize_api_url('https://www.membrowse.com')
        'https://www.membrowse.com/api/upload'

        >>> normalize_api_url('https://www.membrowse.com/')
        'https://www.membrowse.com/api/upload'
    """
    # Strip trailing slashes
    url = base_url.rstrip('/')

    # Append /api/upload suffix
    return f"{url}/api/upload"


def build_comparison_url(
    base_url: str,
    project_id: str,
    target_name: str,
    base_commit: str,
    head_commit: str
) -> Optional[str]:
    """
    Build URL for build comparison page.

    Args:
        base_url: Base URL of MemBrowse (e.g., 'https://www.membrowse.com')
        project_id: Project ID
        target_name: Target name (e.g., 'esp32', 'stm32')
        base_commit: Base/parent commit SHA
        head_commit: Head/current commit SHA

    Returns:
        Comparison URL string, or None if any required parameter is missing

    Example:
        >>> build_comparison_url(
        ...     'https://www.membrowse.com',
        ...     'proj123',
        ...     'esp32',
        ...     'abc123',
        ...     'def456'
        ... )
        'https://www.membrowse.com/project/proj123/target/esp32/compare?base=abc123&head=def456'
    """
    # Validate all required parameters are present
    if not all([base_url, project_id, target_name, base_commit, head_commit]):
        return None

    # Strip trailing slashes from base URL
    url = base_url.rstrip('/')

    # Build comparison URL
    return (
        f"{url}/project/{project_id}/target/{target_name}/compare"
        f"?base={base_commit}&head={head_commit}"
    )
