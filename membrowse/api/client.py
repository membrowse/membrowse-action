#!/usr/bin/env python3
"""
Upload Memory Reports to MemBrowse

This script enriches memory analysis reports with metadata and uploads
them to the MemBrowse API using the requests library.
"""

import argparse
import json
import sys
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
            Dict containing the parsed API response, or None on network errors
        """
        try:
            response = self.session.post(
                self.api_endpoint,
                json=report_data,
                timeout=30
            )

            response_data = self._parse_response(response)

            # Always return response data, regardless of success/failure
            return response_data

        except requests.exceptions.Timeout:
            # Network error - return None
            return None
        except requests.exceptions.ConnectionError:
            # Network error - return None
            return None
        except requests.exceptions.RequestException:
            # Network error - return None
            return None
        except json.JSONDecodeError:
            # JSON parsing error - return None
            return None

    def _parse_response(self, response: requests.Response) -> Dict[str, Any]:
        """Parse JSON response and handle decoding errors"""
        return response.json()


def main() -> None:
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Enrich memory reports with metadata and optionally upload to MemBrowse',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --base-report report.json --commit-sha abc123 --target test --timestamp 2024-01-01T12:00:00Z
  %(prog)s --base-report report.json --api-key secret --commit-sha abc123 --target test --timestamp 2024-01-01T12:00:00Z
        """)

    # Required arguments
    parser.add_argument(
        '--base-report',
        required=True,
        help='Path to base memory report JSON')
    parser.add_argument('--commit-sha', required=True, help='Git commit SHA')
    parser.add_argument(
        '--commit-message',
        required=True,
        help='Git commit message')
    parser.add_argument(
        '--target-name',
        required=True,
        help='Target platform name')
    parser.add_argument(
        '--timestamp',
        required=True,
        help='Committer timestamp in ISO format')

    # Optional metadata
    parser.add_argument(
        '--base-sha',
        default='',
        help='Base commit SHA for comparison')
    parser.add_argument('--branch-name', default='', help='Git branch name')
    parser.add_argument('--repository', default='', help='Repository name')
    parser.add_argument('--pr-number', default='', help='Pull request number')
    parser.add_argument(
        '--analysis-version',
        default=PACKAGE_VERSION,
        help=f'Analysis version (default: {PACKAGE_VERSION})')

    # Upload options
    parser.add_argument(
        '--api-key',
        required=True,
        help='MemBrowse API key')
    parser.add_argument(
        '--api-endpoint',
        required=True,
        help='MemBrowse API endpoint URL')
    parser.add_argument(
        '--print-report',
        action='store_true',
        help='Print report to stdout')
    args = parser.parse_args()
    try:
        # Create metadata structure with nested git info for database
        metadata = {
            'git': {
                'commit_hash': args.commit_sha,
                'commit_message': args.commit_message,
                'commit_timestamp': args.timestamp,
                'base_commit_hash': args.base_sha,
                'branch_name': args.branch_name,
                'pr_number': args.pr_number if args.pr_number else None
            },
            'repository': args.repository,
            'target_name': args.target_name,
            'analysis_version': args.analysis_version
        }
        # Load base report and merge with metadata
        with open(args.base_report, 'r', encoding='utf-8') as f:
            base_report = json.load(f)

        enriched_report = {
            'metadata': metadata,
            'memory_analysis': base_report
        }
        if args.print_report:
            print(json.dumps(enriched_report, indent=2))

        uploader = MemBrowseUploader(args.api_key, args.api_endpoint)
        try:
            uploader.upload_report(enriched_report)
        except UploadError as e:
            print(f"Upload failed: {e}", file=sys.stderr)
            sys.exit(1)
    except FileNotFoundError:
        print(
            f"Error: Base report file not found: {args.base_report}",
            file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in base report: {e}", file=sys.stderr)
        sys.exit(1)
    except (OSError, IOError) as e:
        print(f"Error: File system error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
