"""
MemBrowse API Client

Provides MemBrowseClient class for interacting with the MemBrowse API:
uploading memory analysis reports and retrieving summaries.
"""

import copy
import logging
import random
import time
from importlib.metadata import version
from typing import Dict, Any

import requests

from ..auth.strategy import AuthContext

logger = logging.getLogger(__name__)

PACKAGE_VERSION = version('membrowse')


class MemBrowseClient:
    """Handles API requests to MemBrowse (upload reports, get summaries)."""

    def __init__(self, auth_context: AuthContext, api_base_url: str):
        """
        Initialize client with authentication context.

        Args:
            auth_context: Authentication context with strategy and credentials
            api_base_url: API base URL (e.g., 'https://api.membrowse.com')
        """
        self.auth_context = auth_context
        self.api_base_url = api_base_url.rstrip('/')
        self.session = requests.Session()

        # Build headers based on auth strategy
        headers = auth_context.build_headers()
        headers['User-Agent'] = f'MemBrowse-Action/{PACKAGE_VERSION}'
        self.session.headers.update(headers)

    def upload_report(self, report_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Upload report to MemBrowse API.

        Args:
            report_data: The memory report data to upload

        Returns:
            Dict containing the parsed API response

        Raises:
            requests.exceptions.Timeout: If the request times out after all retries
            requests.exceptions.ConnectionError: If connection fails
            requests.exceptions.RequestException: For other request errors
            json.JSONDecodeError: If response cannot be parsed as JSON
        """
        # Create a copy to avoid mutating the input
        report_to_send = copy.deepcopy(report_data)

        # Add auth-specific metadata (e.g., github_context for tokenless uploads)
        metadata_additions = self.auth_context.get_metadata_additions()
        if metadata_additions:
            if 'metadata' not in report_to_send:
                report_to_send['metadata'] = {}
            report_to_send['metadata'].update(metadata_additions)

        url = f"{self.api_base_url}/upload"
        return self._request_with_retry('POST', url, json=report_to_send)

    def get_summary(self, commit_sha: str) -> Dict[str, Any]:
        """
        Get memory footprint summary for a commit from MemBrowse API.

        Args:
            commit_sha: Git commit SHA to retrieve summary for

        Returns:
            Dict containing the parsed API response

        Raises:
            requests.exceptions.Timeout: If the request times out after all retries
            requests.exceptions.ConnectionError: If connection fails
            requests.exceptions.RequestException: For other request errors
        """
        url = f"{self.api_base_url}/summary"
        return self._request_with_retry('GET', url, params={'commit': commit_sha})

    def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Make HTTP request with retry logic.

        Args:
            method: HTTP method ('GET' or 'POST')
            url: Request URL
            **kwargs: Additional arguments passed to requests

        Returns:
            Parsed JSON response
        """
        max_attempts = 5
        retry_delays = [10, 30, 60, 120]  # seconds between attempts
        timeout_seconds = 120

        for attempt in range(1, max_attempts + 1):
            try:
                logger.warning(
                    "%s %s (attempt %d of %d)...",
                    method, url, attempt, max_attempts
                )
                response = self.session.request(
                    method, url, timeout=timeout_seconds, **kwargs
                )
                response.raise_for_status()

                # Parse and return JSON response
                try:
                    return response.json()
                except ValueError as e:
                    raise ValueError(
                        f"Failed to parse JSON response from {url}: {e}"
                    ) from e

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                if attempt < max_attempts:
                    delay = retry_delays[attempt - 1] * random.uniform(1, 1.5)
                    logger.warning(
                        "Request failed: %s. Retrying in %.1f seconds...",
                        str(e), delay
                    )
                    time.sleep(delay)
                    continue
                logger.error(
                    "Request failed after %d attempts: %s", max_attempts, str(e)
                )
                raise type(e)(
                    f"Request to {url} failed after {max_attempts} "
                    f"attempts: {e}"
                ) from e
            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response is not None else None
                # Retry on 429 Too Many Requests, 503 Service Unavailable,
                # and gateway errors (502, 504)
                if status_code in (429, 502, 503, 504) and attempt < max_attempts:
                    delay = retry_delays[attempt - 1] * random.uniform(1, 1.5)
                    logger.warning(
                        "Request failed with HTTP %d: %s. Retrying in %.1f seconds...",
                        status_code, str(e), delay
                    )
                    time.sleep(delay)
                    continue
                # Include error field from response in error message
                error_detail = ""
                if e.response is not None:
                    try:
                        response_json = e.response.json()
                        if 'error' in response_json:
                            error_detail = f"\nError: {response_json['error']}"
                    except Exception:  # pylint: disable=broad-exception-caught
                        pass
                raise requests.exceptions.HTTPError(
                    f"HTTP error from {url}: {e}{error_detail}"
                ) from e
            except requests.exceptions.RequestException as e:
                raise requests.exceptions.RequestException(
                    f"Request to {url} failed: {e}"
                ) from e

        # This should never be reached, but added for safety
        raise requests.exceptions.RequestException(
            "Unexpected error: reached end of retry loop without success or exception"
        )


# Backward compatibility alias
MemBrowseUploader = MemBrowseClient
