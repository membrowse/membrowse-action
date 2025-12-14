"""
Upload Memory Reports to MemBrowse

Provides MemBrowseUploader class for uploading memory analysis reports
to the MemBrowse API using the requests library.
"""

import copy
import logging
import time
from importlib.metadata import version
from typing import Dict, Any

import requests

from ..auth.strategy import AuthContext

logger = logging.getLogger(__name__)

PACKAGE_VERSION = version('membrowse')


class MemBrowseUploader:  # pylint: disable=too-few-public-methods
    """Handles uploading reports to MemBrowse API"""

    def __init__(self, auth_context: AuthContext, api_endpoint: str):
        """
        Initialize uploader with authentication context.

        Args:
            auth_context: Authentication context with strategy and credentials
            api_endpoint: API endpoint URL
        """
        self.auth_context = auth_context
        self.api_endpoint = api_endpoint
        self.session = requests.Session()

        # Build headers based on auth strategy
        headers = auth_context.build_headers()
        headers['User-Agent'] = f'MemBrowse-Action/{PACKAGE_VERSION}'
        self.session.headers.update(headers)

    def upload_report(self, report_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Upload report to MemBrowse API using requests

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

        max_attempts = 5
        retry_delays = [10, 30, 60, 120]  # seconds between attempts
        timeout_seconds = 120

        for attempt in range(1, max_attempts + 1):
            try:
                logger.warning(
                    "Uploading report to MemBrowse (attempt %d of %d)...",
                    attempt, max_attempts
                )
                response = self.session.post(
                    self.api_endpoint,
                    json=report_to_send,
                    timeout=timeout_seconds
                )
                response.raise_for_status()

                # Parse and return JSON response
                try:
                    return response.json()
                except ValueError as e:
                    raise ValueError(
                        f"Failed to parse JSON response from {self.api_endpoint}: {e}"
                    ) from e

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                if attempt < max_attempts:
                    delay = retry_delays[attempt - 1]
                    logger.warning(
                        "Upload failed: %s. Retrying in %d seconds...",
                        str(e), delay
                    )
                    time.sleep(delay)
                    continue
                logger.error(
                    "Upload failed after %d attempts: %s", max_attempts, str(e)
                )
                raise type(e)(
                    f"Request to {self.api_endpoint} failed after {max_attempts} "
                    f"attempts: {e}"
                ) from e
            except requests.exceptions.HTTPError as e:
                # Retry on gateway errors (502 Bad Gateway, 504 Gateway Timeout)
                status_code = e.response.status_code if e.response is not None else None
                if status_code in (502, 504) and attempt < max_attempts:
                    delay = retry_delays[attempt - 1]
                    logger.warning(
                        "Upload failed with HTTP %d: %s. Retrying in %d seconds...",
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
                    f"HTTP error from {self.api_endpoint}: {e}{error_detail}"
                ) from e
            except requests.exceptions.RequestException as e:
                raise requests.exceptions.RequestException(
                    f"Request to {self.api_endpoint} failed: {e}"
                ) from e

        # This should never be reached, but added for safety
        raise requests.exceptions.RequestException(
            "Unexpected error: reached end of retry loop without success or exception"
        )
