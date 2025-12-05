"""URL utilities for MemBrowse API endpoints."""


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
