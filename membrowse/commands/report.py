"""Report subcommand - generates memory footprint reports from ELF files."""

import os
import sys
import json
import argparse
import logging
from importlib.metadata import version

from ..utils.git import detect_github_metadata
from ..linker.parser import LinkerScriptParser
from ..core.generator import ReportGenerator
from ..api.client import MemBrowseUploader

# Set up logger
logger = logging.getLogger(__name__)

# Default MemBrowse API endpoint
DEFAULT_API_URL = 'https://www.membrowse.com/api/upload'


def print_upload_response(response_data: dict, verbose: bool = False) -> None:
    """
    Print upload response details including changes summary and budget alerts.

    Args:
        response_data: The API response data from MemBrowse
        verbose: If True, print full JSON response for debugging
    """
    # Check if upload was successful
    success = response_data.get('success', False)

    if success:
        print("Report uploaded successfully to MemBrowse")
    else:
        print("Upload failed", file=sys.stderr)

    # In verbose mode, log the full API response for debugging
    if verbose:
        logger.debug("Full API Response:")
        logger.debug(json.dumps(response_data, indent=2))

    # Display API message if present
    api_message = response_data.get('message')
    if api_message:
        print(f"\n{api_message}")

    # Handle error responses
    if not success:
        error = response_data.get('error', 'Unknown error')
        error_type = response_data.get('type', 'UnknownError')
        print(f"\nError: {error_type} - {error}", file=sys.stderr)

        # Display upload limit details if present
        if error_type == 'UploadLimitExceededError':
            _display_upload_limit_error(response_data)

        # Display upgrade URL if present
        upgrade_url = response_data.get('upgrade_url')
        if upgrade_url:
            print(f"\nUpgrade at: {upgrade_url}", file=sys.stderr)

        return  # Don't display changes/alerts for failed uploads

    # Extract response data (only for successful uploads)
    data = response_data.get('data', {})

    # Display overwrite warning
    if data.get('is_overwritten', False):
        print("\nWarning: This upload overwrote existing data")

    # Display changes summary
    changes_summary = data.get('changes_summary', {})
    logger.debug("changes_summary present: %s", bool(changes_summary))
    if changes_summary:
        logger.debug("changes_summary keys: %s", list(changes_summary.keys()))
        _display_changes_summary(changes_summary)

    # Display budget alerts
    alerts = data.get('alerts') or {}
    budget_alerts = alerts.get('budgets', [])
    logger.debug("alerts present: %s", bool(alerts))
    logger.debug("budget_alerts count: %d", len(budget_alerts))

    if budget_alerts:
        _display_budget_alerts(budget_alerts)


def _display_changes_summary(changes_summary: dict) -> None:
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


def _display_budget_alerts(budget_alerts: list) -> None:
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


def _display_upload_limit_error(response_data: dict) -> None:
    """Display detailed upload limit error information"""
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


def _validate_file_paths(elf_path: str, ld_script_paths: list[str]) -> tuple[bool, str]:
    """
    Validate that ELF file and linker scripts exist.

    Args:
        elf_path: Path to ELF file
        ld_script_paths: List of linker script paths

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Validate ELF file exists
    if not os.path.exists(elf_path):
        return False, f"ELF file not found: {elf_path}"

    # Validate linker scripts exist
    for ld_script in ld_script_paths:
        if not os.path.exists(ld_script):
            return False, f"Linker script not found: {ld_script}"

    return True, ""


def _validate_upload_arguments(api_key: str, target_name: str) -> tuple[bool, str]:
    """
    Validate arguments required for uploading reports.

    Args:
        api_key: API key for upload
        target_name: Target name for upload

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not api_key:
        return False, "--api-key is required when using --upload or --github"

    if not target_name:
        return False, "--target-name is required when using --upload or --github"

    return True, ""


def add_report_parser(subparsers) -> argparse.ArgumentParser:
    """
    Add 'report' subcommand parser.

    Args:
        subparsers: Subparsers object from argparse

    Returns:
        The report parser
    """
    parser = subparsers.add_parser(
        'report',
        help='Generate memory footprint report from ELF and linker scripts',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  # Local mode - output JSON to stdout
  membrowse report firmware.elf "linker.ld"

  # Save to file
  membrowse report firmware.elf "linker.ld" > report.json

  # Upload to MemBrowse
  membrowse report firmware.elf "linker.ld" --upload \\
      --api-key "$API_KEY" --target-name esp32 \\
      --api-url https://www.membrowse.com/api/upload

  # GitHub Actions mode (auto-detects Git metadata)
  membrowse report firmware.elf "linker.ld" --github \\
      --target-name stm32f4 --api-key "$API_KEY"
        """
    )

    # Required arguments
    parser.add_argument('elf_path', help='Path to ELF file')
    parser.add_argument(
        'ld_scripts',
        help='Space-separated linker script paths (quoted)')

    # Mode flags
    mode_group = parser.add_argument_group('mode options')
    mode_group.add_argument(
        '--upload',
        action='store_true',
        help='Upload report to MemBrowse platform'
    )
    mode_group.add_argument(
        '--github',
        action='store_true',
        help='GitHub Actions mode - auto-detect Git metadata and upload'
    )

    # Upload parameters (only relevant with --upload or --github)
    upload_group = parser.add_argument_group(
        'upload options',
        'Required when using --upload or --github'
    )
    upload_group.add_argument('--api-key', help='MemBrowse API key')
    upload_group.add_argument(
        '--target-name',
        help='Build configuration/target (e.g., esp32, stm32, x86)')
    upload_group.add_argument(
        '--api-url',
        default=DEFAULT_API_URL,
        help='MemBrowse API endpoint (default: %(default)s)'
    )

    # Optional Git metadata (for --upload mode without --github)
    git_group = parser.add_argument_group(
        'git metadata options',
        'Optional Git metadata (auto-detected in --github mode)'
    )
    git_group.add_argument('--commit-sha', help='Git commit SHA')
    git_group.add_argument('--base-sha', help='Git base/parent commit SHA')
    git_group.add_argument('--branch-name', help='Git branch name')
    git_group.add_argument('--repo-name', help='Repository name')
    git_group.add_argument('--commit-message', help='Commit message')
    git_group.add_argument(
        '--commit-timestamp',
        help='Commit timestamp (ISO format)')
    git_group.add_argument('--author-name', help='Commit author name')
    git_group.add_argument('--author-email', help='Commit author email')
    git_group.add_argument('--pr-number', help='Pull request number')

    # Performance options
    perf_group = parser.add_argument_group('performance options')
    perf_group.add_argument(
        '--skip-line-program',
        action='store_true',
        help='Skip DWARF line program processing for faster analysis'
    )
    perf_group.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose output'
    )

    # Alert handling
    alert_group = parser.add_argument_group('alert options')
    alert_group.add_argument(
        '--dont-fail-on-alerts',
        action='store_true',
        help='Continue even if budget alerts are detected (default: fail on alerts)'
    )

    return parser


def generate_report(
    elf_path: str,
    ld_scripts: str,
    skip_line_program: bool = False,
    verbose: bool = False
) -> dict:
    """
    Generate a memory footprint report from ELF and linker scripts.

    Args:
        elf_path: Path to ELF file
        ld_scripts: Space-separated linker script paths
        skip_line_program: Skip DWARF line program processing for faster analysis
        verbose: Enable verbose output

    Returns:
        dict: Memory analysis report (JSON-serializable)

    Raises:
        ValueError: If file paths are invalid or parsing fails
    """
    # Split linker scripts
    ld_array = ld_scripts.split()

    # Validate file paths
    is_valid, error_message = _validate_file_paths(elf_path, ld_array)
    if not is_valid:
        raise ValueError(error_message)

    logger.info("Started Memory Report generation")
    logger.info("ELF file: %s", elf_path)
    logger.info("Linker scripts: %s", ld_scripts)

    # Parse memory regions from linker scripts
    logger.warning("Parsing memory regions from linker scripts...")
    try:
        parser = LinkerScriptParser(ld_array, elf_file=elf_path)
        memory_regions_data = parser.parse_memory_regions()
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to parse memory regions: %s", e)
        raise ValueError(f"Failed to parse memory regions: {e}") from e

    # Generate JSON report
    logger.warning("Generating memory report...")
    try:
        generator = ReportGenerator(
            elf_path,
            memory_regions_data,
            skip_line_program=skip_line_program
        )
        report = generator.generate_report(verbose)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to generate memory report: %s", e)
        raise ValueError(f"Failed to generate memory report: {e}") from e

    logger.info("Memory report generated successfully")
    return report


def upload_report(  # pylint: disable=too-many-arguments
    report: dict,
    commit_info: dict,
    target_name: str,
    api_key: str,
    api_url: str = DEFAULT_API_URL,
    *,
    verbose: bool = False,
    dont_fail_on_alerts: bool = False
) -> dict:
    """
    Upload a memory footprint report to MemBrowse platform.

    Args:
        report: Memory analysis report (from generate_report)
        commit_info: Dict with Git metadata in metadata['git'] format
            {
                'commit_hash': str,
                'base_commit_hash': str,
                'branch_name': str,
                'repository': str,
                'commit_message': str,
                'commit_timestamp': str,
                'author_name': str,
                'author_email': str,
                'pr_number': str
            }
        target_name: Build configuration/target (e.g., esp32, stm32, x86)
        api_key: MemBrowse API key
        api_url: MemBrowse API endpoint URL
        verbose: Enable verbose output (keyword-only)
        dont_fail_on_alerts: Continue even if budget alerts are detected (keyword-only)

    Returns:
        dict: API response data if upload succeeded

    Raises:
        ValueError: If upload arguments are invalid
        RuntimeError: If upload fails or budget alerts are triggered
    """
    # Validate upload arguments
    is_valid, error_message = _validate_upload_arguments(api_key, target_name)
    if not is_valid:
        raise ValueError(error_message)

    # Set up log prefix
    log_prefix = _get_log_prefix(commit_info)

    logger.warning("%s: Uploading report to MemBrowse...", log_prefix)
    logger.info("Target: %s", target_name)

    # Build and enrich report
    enriched_report = _build_enriched_report(report, commit_info, target_name)

    # Upload to MemBrowse
    response_data = _perform_upload(enriched_report, api_key, api_url, log_prefix)

    # Always print upload response details (success or failure)
    print_upload_response(response_data, verbose=verbose)

    # Validate upload success
    _validate_upload_success(response_data, log_prefix)

    # Check for budget alerts if fail_on_alerts is enabled
    _check_budget_alerts(response_data, dont_fail_on_alerts, log_prefix)

    logger.info("%s: Memory report uploaded successfully", log_prefix)
    return response_data


def _get_log_prefix(commit_info: dict) -> str:
    """Get log prefix from commit info."""
    if commit_info.get('commit_hash'):
        return f"({commit_info.get('commit_hash')})"
    return "MemBrowse"


def _build_enriched_report(report: dict, commit_info: dict, target_name: str) -> dict:
    """Build enriched report with metadata."""
    metadata = {
        'git': commit_info,
        'repository': commit_info.get('repository'),
        'target_name': target_name,
        'analysis_version': version('membrowse')
    }

    return {
        'metadata': metadata,
        'memory_analysis': report
    }


def _perform_upload(enriched_report: dict, api_key: str, api_url: str, log_prefix: str) -> dict:
    """Perform the actual upload to MemBrowse."""
    try:
        uploader = MemBrowseUploader(api_key, api_url)
        return uploader.upload_report(enriched_report)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("%s: Failed to upload report: %s", log_prefix, e)
        raise RuntimeError(f"Failed to upload report: {e}") from e


def _validate_upload_success(response_data: dict, log_prefix: str) -> None:
    """Validate that upload was successful."""
    if not response_data.get('success'):
        logger.error("%s: Upload failed - see response details above", log_prefix)
        raise RuntimeError("Upload failed - see response details above")


def _check_budget_alerts(response_data: dict, dont_fail_on_alerts: bool, log_prefix: str) -> None:
    """Check for budget alerts and fail if necessary."""
    if dont_fail_on_alerts:
        return

    data = response_data.get('data', {})
    alerts = data.get('alerts') or {}
    budget_alerts = alerts.get('budgets', [])

    if budget_alerts:
        error_msg = (
            f"Budget Alert Error: {len(budget_alerts)} budget(s) exceeded. "
            "Use --dont-fail-on-alerts to continue despite alerts."
        )
        logger.error("%s: %s", log_prefix, error_msg)
        print(f"\n{error_msg}", file=sys.stderr)
        raise RuntimeError(
            f"Budget alerts detected: {len(budget_alerts)} budget(s) exceeded"
        )


def run_report(args: argparse.Namespace) -> int:
    """
    Execute the report subcommand.

    This function converts argparse.Namespace to function parameters
    and calls generate_report() and optionally upload_report().

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    verbose = getattr(args, 'verbose', False)

    # Generate report
    try:
        report = generate_report(
            elf_path=args.elf_path,
            ld_scripts=args.ld_scripts,
            skip_line_program=getattr(args, 'skip_line_program', False),
            verbose=verbose
        )
    except ValueError as e:
        logger.error("Failed to generate report: %s", e)
        return 1

    # Check if upload mode is enabled
    upload_mode = getattr(args, 'upload', False) or getattr(args, 'github', False)

    # If not uploading, print report to stdout and exit
    if not upload_mode:
        logger.info("Local mode - outputting report to stdout")
        print(json.dumps(report, indent=2))
        return 0

    # Build commit_info dict in metadata['git'] format
    arg_to_metadata_map = {
        'commit_sha': 'commit_hash',
        'base_sha': 'base_commit_hash',
        'branch_name': 'branch_name',
        'repo_name': 'repository',
        'commit_message': 'commit_message',
        'commit_timestamp': 'commit_timestamp',
        'author_name': 'author_name',
        'author_email': 'author_email',
        'pr_number': 'pr_number',
    }

    commit_info = {
        metadata_key: getattr(args, arg_key, None)
        for arg_key, metadata_key in arg_to_metadata_map.items()
        if getattr(args, arg_key, None) is not None
    }

    # Auto-detect Git metadata if --github flag is set
    if getattr(args, 'github', False):
        detected_metadata = detect_github_metadata()
        # Update commit_info with detected metadata (only if not already set)
        commit_info = {k: commit_info.get(k) or v for k, v in detected_metadata.items()}

    # Upload report
    try:
        upload_report(
            report=report,
            commit_info=commit_info,
            target_name=getattr(args, 'target_name', None),
            api_key=getattr(args, 'api_key', None),
            api_url=getattr(args, 'api_url', DEFAULT_API_URL),
            verbose=verbose,
            dont_fail_on_alerts=getattr(args, 'dont_fail_on_alerts', False)
        )
        return 0
    except (ValueError, RuntimeError) as e:
        logger.error("Failed to upload report: %s", e)
        return 1
