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

    def upload_report(self, report_data: Dict[str, Any]) -> bool:
        """Upload report to MemBrowse API using requests"""
        try:
            print(f"Uploading report to MemBrowse: {self.api_endpoint}")
            # Make the POST request directly with the data
            response = self.session.post(
                self.api_endpoint,
                json=report_data,
                timeout=30
            )
            # Check response
            if response.status_code in (200, 201):
                print("Report uploaded successfully to MemBrowse")
                return True
            error_msg = f"HTTP {response.status_code}: {response.text}"
            print(f"Failed to upload report: {error_msg}", file=sys.stderr)
            return False
        except requests.exceptions.Timeout:
            print("Upload error: Request timed out", file=sys.stderr)
            return False
        except requests.exceptions.ConnectionError:
            print(
                "Upload error: Failed to connect to MemBrowse API",
                file=sys.stderr)
            return False
        except requests.exceptions.RequestException as e:
            print(f"Upload error: {e}", file=sys.stderr)
            return False


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
        success = uploader.upload_report(enriched_report)
        if not success:
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
