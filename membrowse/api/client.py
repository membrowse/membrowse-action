"""
Upload Memory Reports to MemBrowse

Provides MemBrowseUploader class for uploading memory analysis reports
to the MemBrowse API using the requests library.
"""

from importlib.metadata import version
from typing import Dict, Any

import requests

PACKAGE_VERSION = version('membrowse')


class MemBrowseUploader:  # pylint: disable=too-few-public-methods
    """Handles uploading reports to MemBrowse API"""

    def __init__(self, api_key: str, api_endpoint: str):
        self.api_key = api_key
        self.api_endpoint = api_endpoint
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'User-Agent': f'MemBrowse-Action/{PACKAGE_VERSION}'
        })

    def upload_report(self, report_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Upload report to MemBrowse API using requests

        Args:
            report_data: The memory report data to upload

        Returns:
            Dict containing the parsed API response

        Raises:
            requests.exceptions.Timeout: If the request times out
            requests.exceptions.ConnectionError: If connection fails
            requests.exceptions.RequestException: For other request errors
            json.JSONDecodeError: If response cannot be parsed as JSON
        """
        response = self.session.post(
            self.api_endpoint,
            json=report_data,
            timeout=30
        )

        return response.json()
