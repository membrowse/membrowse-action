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
from typing import Dict, Any, NoReturn

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
            response = self.session.post(
                self.api_endpoint,
                json=report_data,
                timeout=30
            )

            response_data = self._parse_response(response)

            if response.status_code in (200, 201) and response_data.get('success'):
                return self._handle_success_response(response_data, fail_on_alerts)

            # Handle error response (always raises UploadError)
            self._handle_error_response(response, response_data)

        except requests.exceptions.Timeout as exc:
            self._raise_upload_error("Request timed out", exc)
        except requests.exceptions.ConnectionError as exc:
            self._raise_upload_error("Failed to connect to MemBrowse API", exc)
        except requests.exceptions.RequestException as exc:
            self._raise_upload_error(str(exc), exc)

    def _parse_response(self, response: requests.Response) -> Dict[str, Any]:
        """Parse JSON response and handle decoding errors"""
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            error_msg = f"HTTP {response.status_code}: Invalid JSON response"
            print(f"Failed to upload report: {error_msg}", file=sys.stderr)
            raise UploadError(error_msg) from exc

    def _handle_success_response(
            self, response_data: Dict[str, Any], fail_on_alerts: bool
    ) -> Dict[str, Any]:
        """Handle successful API response with changes and alerts"""
        print("Report uploaded successfully to MemBrowse")

        # Display API message if present
        api_message = response_data.get('message')
        if api_message:
            print(f"\n{api_message}")

        # Extract response data
        data = response_data.get('data', {})

        # Display overwrite warning
        if data.get('is_overwritten', False):
            print("\nWarning: This upload overwrote existing data")

        # Display changes summary
        changes_summary = data.get('changes_summary', {})
        if changes_summary:
            self._display_changes_summary(changes_summary)

        # Display and handle budget alerts
        alerts = data.get('alerts', {})
        budget_alerts = alerts.get('budgets', [])
        if budget_alerts:
            self._display_budget_alerts(budget_alerts)
            if fail_on_alerts:
                raise BudgetAlertError(
                    f"Budget alerts detected: {len(budget_alerts)} budget(s) exceeded. "
                    "Use --dont-fail-on-alerts to continue despite alerts."
                )

        return response_data

    def _handle_error_response(
            self, response: requests.Response, response_data: Dict[str, Any]
    ) -> NoReturn:
        """Handle API error response and raise UploadError"""
        error = response_data.get('error', 'Unknown error')
        error_type = response_data.get('type', 'UnknownError')
        upgrade_url = response_data.get('upgrade_url')

        error_msg = f"HTTP {response.status_code}: {error_type} - {error}"

        if error_type == 'UploadLimitExceededError':
            self._display_upload_limit_error(error_msg, response_data, upgrade_url)
        else:
            if upgrade_url:
                error_msg += f"\nUpgrade at: {upgrade_url}"
            print(f"Failed to upload report: {error_msg}", file=sys.stderr)

        raise UploadError(error_msg)

    def _display_upload_limit_error(
            self, error_msg: str, response_data: Dict[str, Any], upgrade_url: str
    ) -> None:
        """Display detailed upload limit error information"""
        print(f"Failed to upload report: {error_msg}", file=sys.stderr)
        print("\nUpload Limit Details:", file=sys.stderr)

        upload_count_monthly = response_data.get('upload_count_monthly')
        monthly_limit = response_data.get('monthly_upload_limit')
        upload_count_total = response_data.get('upload_count_total')
        period_start = response_data.get('period_start')
        period_end = response_data.get('period_end')

        if upload_count_monthly is not None and monthly_limit is not None:
            print(
                f"  Monthly uploads: {upload_count_monthly} / {monthly_limit}",
                file=sys.stderr
            )

        if upload_count_total is not None:
            print(f"  Total uploads: {upload_count_total}", file=sys.stderr)

        if period_start and period_end:
            print(f"  Billing period: {period_start} to {period_end}", file=sys.stderr)

        if upgrade_url:
            print(f"\nUpgrade at: {upgrade_url}", file=sys.stderr)

    @staticmethod
    def _raise_upload_error(message: str, exc: Exception) -> NoReturn:
        """Helper to raise UploadError with consistent formatting"""
        error_msg = f"Upload error: {message}"
        print(error_msg, file=sys.stderr)
        raise UploadError(error_msg) from exc

    def _display_changes_summary(self, changes_summary: Dict[str, Any]) -> None:
        """Display memory changes summary in human-readable format"""
        print("\nMemory Changes Summary:")

        # Check if changes_summary is empty or None
        if not changes_summary:
            print("\n  No changes detected")
            return

        # Track if we found any actual changes
        has_changes = False

        for region_name, changes in changes_summary.items():
            # Skip if changes is falsy (None, empty dict, etc.)
            if not changes or not isinstance(changes, dict):
                continue

            used_change = changes.get('used_change', 0)
            free_change = changes.get('free_change', 0)

            # Skip regions with no actual changes
            if used_change == 0 and free_change == 0:
                continue

            # We found at least one change
            has_changes = True
            print(f"\n  {region_name}:")

            if used_change != 0:
                direction = "increased" if used_change > 0 else "decreased"
                print(f"    Used: {direction} by {abs(used_change):,} bytes")

            if free_change != 0:
                direction = "increased" if free_change > 0 else "decreased"
                print(f"    Free: {direction} by {abs(free_change):,} bytes")

        # If we processed regions but found no changes
        if not has_changes:
            print("\n  No changes detected")

    def _display_budget_alerts(self, budget_alerts: list) -> None:
        """Display budget alerts in human-readable format"""
        print("\nBudget Alerts:")

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
