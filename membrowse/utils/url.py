"""URL utilities for MemBrowse API endpoints."""


def normalize_api_url(base_url: str) -> str:
    """
    Normalize a base URL to a full MemBrowse API endpoint.

    Automatically appends '/api/upload' suffix to base URLs.
    Handles trailing slashes and detects if suffix already present.

    Args:
        base_url: Base URL (e.g., 'https://www.membrowse.com')
                 or full endpoint URL (e.g., 'https://www.membrowse.com/api/upload')

    Returns:
        Full API endpoint URL with '/api/upload' suffix

    Examples:
        >>> normalize_api_url('https://www.membrowse.com')
        'https://www.membrowse.com/api/upload'

        >>> normalize_api_url('https://www.membrowse.com/')
        'https://www.membrowse.com/api/upload'

        >>> normalize_api_url('https://www.membrowse.com/api/upload')
        'https://www.membrowse.com/api/upload'
    """
    # Strip trailing slashes
    url = base_url.rstrip('/')

    # Check if /api/upload already present (backwards compatibility)
    if url.endswith('/api/upload'):
        return url

    # Append /api/upload suffix
    return f"{url}/api/upload"
