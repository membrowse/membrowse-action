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

from membrowse.core.exceptions import UploadError, BudgetAlertError

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

    def upload_report(
            self, report_data: Dict[str, Any], fail_on_alerts: bool = True
    ) -> Dict[str, Any]:
        """
        Upload report to MemBrowse API using requests

        Args:
            report_data: The memory report data to upload
            fail_on_alerts: If True, raise exception when budget alerts are present

        Returns:
            Dict containing the parsed API response

        Raises:
            UploadError: On upload failure
            BudgetAlertError: When alerts present with fail_on_alerts=True
        """
        try:
            print(f"Uploading report to MemBrowse: {self.api_endpoint}")
            # Make the POST request directly with the data
            response = self.session.post(
                self.api_endpoint,
                json=report_data,
                timeout=30
            )

            # Parse response
            try:
                response_data = response.json()
            except json.JSONDecodeError as exc:
                error_msg = f"HTTP {response.status_code}: Invalid JSON response"
                print(f"Failed to upload report: {error_msg}", file=sys.stderr)
                raise UploadError(error_msg) from exc

            # Check response success field
            if response.status_code in (200, 201) and response_data.get('success'):
                print("✓ Report uploaded successfully to MemBrowse")

                # Extract response data
                data = response_data.get('data', {})
                changes_summary = data.get('changes_summary', {})
                alerts = data.get('alerts', {})
                is_overwritten = data.get('is_overwritten', False)

                # Display overwrite notification
                if is_overwritten:
                    print("\n⚠ Warning: This upload overwrote existing data")

                # Display changes summary
                if changes_summary:
                    self._display_changes_summary(changes_summary)

                # Display alerts
                budget_alerts = alerts.get('budgets', [])
                if budget_alerts:
                    self._display_budget_alerts(budget_alerts)

                    # Fail if alerts present and fail_on_alerts is True
                    if fail_on_alerts:
                        raise BudgetAlertError(
                            f"Budget alerts detected: {len(budget_alerts)} budget(s) exceeded. "
                            "Use --dont-fail-on-alerts to continue despite alerts."
                        )

                return response_data

            # Handle error response
            error = response_data.get('error', 'Unknown error')
            error_type = response_data.get('type', 'UnknownError')
            upgrade_url = response_data.get('upgrade_url')

            error_msg = f"HTTP {response.status_code}: {error_type} - {error}"
            if upgrade_url:
                error_msg += f"\nUpgrade at: {upgrade_url}"

            print(f"Failed to upload report: {error_msg}", file=sys.stderr)
            raise UploadError(error_msg)

        except requests.exceptions.Timeout as exc:
            error_msg = "Upload error: Request timed out"
            print(error_msg, file=sys.stderr)
            raise UploadError(error_msg) from exc
        except requests.exceptions.ConnectionError as exc:
            error_msg = "Upload error: Failed to connect to MemBrowse API"
            print(error_msg, file=sys.stderr)
            raise UploadError(error_msg) from exc
        except requests.exceptions.RequestException as exc:
            error_msg = f"Upload error: {exc}"
            print(error_msg, file=sys.stderr)
            raise UploadError(error_msg) from exc

    def _display_changes_summary(self, changes_summary: Dict[str, Any]) -> None:
        """Display memory changes summary in human-readable format"""
        print("\n📊 Memory Changes Summary:")

        for region_name, changes in changes_summary.items():
            if not changes:
                continue

            print(f"\n  {region_name}:")
            used_change = changes.get('used_change', 0)
            free_change = changes.get('free_change', 0)

            if used_change != 0:
                direction = "↑" if used_change > 0 else "↓"
                print(f"    Used: {direction} {abs(used_change):,} bytes")

            if free_change != 0:
                direction = "↑" if free_change > 0 else "↓"
                print(f"    Free: {direction} {abs(free_change):,} bytes")

    def _display_budget_alerts(self, budget_alerts: list) -> None:
        """Display budget alerts in human-readable format"""
        print("\n⚠️  Budget Alerts:")

        for alert in budget_alerts:
            region = alert.get('region', 'Unknown')
            budget_type = alert.get('budget_type', 'unknown')
            threshold = alert.get('threshold', 0)
            current = alert.get('current', 0)
            exceeded_by = alert.get('exceeded_by', 0)

            print(f"\n  {region} ({budget_type}):")
            print(f"    Threshold: {threshold:,} bytes")
            print(f"    Current:   {current:,} bytes")
            print(f"    Exceeded by: {exceeded_by:,} bytes ({exceeded_by/threshold*100:.1f}%)")


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
