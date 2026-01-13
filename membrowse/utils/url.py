"""URL utilities for MemBrowse API endpoints."""


def normalize_api_url(base_url: str) -> str:
    """
    Normalize a base URL to a full MemBrowse API endpoint.

    Automatically appends '/upload' suffix to base URLs.
    Handles trailing slashes.

    Args:
        base_url: Base URL (e.g., 'https://api.membrowse.com')

    Returns:
        Full API endpoint URL with '/upload' suffix

    Examples:
        >>> normalize_api_url('https://api.membrowse.com')
        'https://api.membrowse.com/upload'

        >>> normalize_api_url('https://api.membrowse.com/')
        'https://api.membrowse.com/upload'
    """
    # Strip trailing slashes
    url = base_url.rstrip('/')

    # Append /upload suffix
    return f"{url}/upload"
