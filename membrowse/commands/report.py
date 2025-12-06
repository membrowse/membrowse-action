"""Report subcommand - generates memory footprint reports from ELF files."""

import os
import json
import argparse
import logging
from importlib.metadata import version
from typing import Dict, Any, Optional

from ..utils.git import detect_github_metadata
from ..utils.url import normalize_api_url
from ..utils.budget_alerts import iter_budget_alerts
from ..utils.formatter import format_report_human_readable
from ..utils.github import is_fork_pr
from ..linker.parser import LinkerScriptParser
from ..core.generator import ReportGenerator
from ..api.client import MemBrowseUploader
from ..auth.strategy import determine_auth_strategy

# Set up logger
logger = logging.getLogger(__name__)

# Default MemBrowse API base URL (automatically appends /api/upload)
DEFAULT_API_URL = 'https://www.membrowse.com'


def print_upload_response(response_data: dict) -> str:
    """
    Print upload response details including changes summary and budget alerts.

    Args:
        response_data: The API response data from MemBrowse

    Returns:
        str: Comparison URL if available, None otherwise
    """
    # Check if upload was successful
    success = response_data.get('success', False)
    comparison_url = None

    if success:
        logger.info("Report uploaded successfully to MemBrowse")

        # Display comparison link if available and capture URL
        comparison_url = _display_comparison_link(response_data)
    else:
        logger.error("Upload failed")

    logger.debug("Full API Response:")
    logger.debug(json.dumps(response_data, indent=2))

    # Display API message if present
    api_message = response_data.get('message')
    if api_message:
        logger.info("%s", api_message)

    # Handle error responses
    if not success:
        error = response_data.get('error', 'Unknown error')
        error_type = response_data.get('type', 'UnknownError')
        logger.error("Error: %s - %s", error_type, error)

        # Display upload limit details if present
        if error_type == 'UploadLimitExceededError':
            _display_upload_limit_error(response_data)

        # Display upgrade URL if present
        upgrade_url = response_data.get('upgrade_url')
        if upgrade_url:
            logger.error("Upgrade at: %s", upgrade_url)

        return None  # Don't display changes/alerts for failed uploads

    # Extract response data (only for successful uploads)
    data = response_data.get('data', {})

    # Display overwrite warning
    if data.get('is_overwritten', False):
        logger.warning("This upload overwrote existing data")

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

    return comparison_url


def _display_changes_summary(changes_summary: dict) -> None:
    """Display memory changes summary in human-readable format"""
    logger.info("Memory Changes Summary:")

    # Check if changes_summary is empty or None
    if not changes_summary:
        logger.info("  No changes detected")
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
        logger.info("  %s:", region_name)

        if used_change != 0:
            direction = "increased" if used_change > 0 else "decreased"
            logger.info("    Used: %s by %s bytes", direction, f"{abs(used_change):,}")

        if free_change != 0:
            direction = "increased" if free_change > 0 else "decreased"
            logger.info("    Free: %s by %s bytes", direction, f"{abs(free_change):,}")

    # If we processed regions but found no changes
    if not has_changes:
        logger.info("  No changes detected")


def _display_budget_alerts(budget_alerts: list) -> None:
    """Display budget alerts in human-readable format"""
    logger.info("Budget Alerts:")

    current_budget = None
    for alert in iter_budget_alerts(budget_alerts):
        # Print budget name header when we encounter a new budget
        if current_budget != alert.budget_name:
            current_budget = alert.budget_name
            logger.info("  %s:", alert.budget_name)

        # Display region alert
        logger.info("    %s: %s bytes (exceeded by %s bytes)",
                    alert.region, f"{alert.usage:,}", f"{alert.exceeded:,}")


def _display_upload_limit_error(response_data: dict) -> None:
    """Display detailed upload limit error information"""
    logger.error("Upload Limit Details:")

    upload_count_monthly = response_data.get('upload_count_monthly')
    monthly_limit = response_data.get('monthly_upload_limit')
    upload_count_total = response_data.get('upload_count_total')
    period_start = response_data.get('period_start')
    period_end = response_data.get('period_end')

    if upload_count_monthly is not None and monthly_limit is not None:
        logger.error("  Monthly uploads: %s / %s", upload_count_monthly, monthly_limit)

    if upload_count_total is not None:
        logger.error("  Total uploads: %s", upload_count_total)

    if period_start and period_end:
        logger.error("  Billing period: %s to %s", period_start, period_end)


def _display_comparison_link(response_data: dict) -> str:
    """
    Display link to build comparison page from API response.

    Args:
        response_data: The API response data from MemBrowse

    Returns:
        str: Comparison URL from API response, or None if not available
    """
    if not response_data:
        return None

    # Extract comparison URL directly from API response
    data = response_data.get('data', {})
    comparison_url = data.get('comparison_url')

    # Display URL if available
    if comparison_url:
        logger.info("View build comparison: %s", comparison_url)

    return comparison_url


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


def _validate_upload_arguments(
    api_key: Optional[str],
    target_name: str,
    is_github_mode: bool = False
) -> tuple[bool, str]:
    """
    Validate arguments required for uploading reports.

    Args:
        api_key: Optional API key for upload
        target_name: Target name for upload
        is_github_mode: Whether --github flag is set (enables tokenless for fork PRs)

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Target name always required for uploads
    if not target_name:
        return False, "--target-name is required when using --upload or --github"

    # In GitHub mode, allow tokenless for fork PRs
    if is_github_mode and not api_key and is_fork_pr():
        logger.info("Fork PR detected without API key - will use tokenless upload")
        return True, ""

    # Otherwise API key is required
    if not api_key:
        error_msg = "--api-key is required when using --upload or --github"
        if is_github_mode:
            error_msg += ". For fork PRs to public repositories, api_key can be omitted."
        return False, error_msg

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
  # Local mode - human-readable output (default)
  membrowse report firmware.elf "linker.ld"

  # Show all symbols instead of top 20
  membrowse report firmware.elf "linker.ld" --all-symbols

  # Output as JSON
  membrowse report firmware.elf "linker.ld" --json

  # Save JSON to file
  membrowse report firmware.elf "linker.ld" --json > report.json

  # Upload to MemBrowse
  membrowse report firmware.elf "linker.ld" --upload \\
      --api-key "$API_KEY" --target-name esp32 \\
      --api-url https://www.membrowse.com

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
        help='MemBrowse API base URL (default: %(default)s, /api/upload appended automatically)'
    )

    # Optional Git metadata (for --upload mode without --github)
    git_group = parser.add_argument_group(
        'git metadata options',
        'Optional Git metadata (auto-detected in --github mode)'
    )
    git_group.add_argument('--commit-sha', help='Git commit SHA')
    git_group.add_argument('--base-sha', help='Git base commit SHA (for comparison URLs)')
    git_group.add_argument('--parent-sha', help='Git parent commit SHA (actual git parent)')
    git_group.add_argument('--branch-name', help='Git branch name')
    git_group.add_argument('--repo-name', help='Repository name')
    git_group.add_argument('--commit-message', help='Commit message')
    git_group.add_argument(
        '--commit-timestamp',
        help='Commit timestamp (ISO format)')
    git_group.add_argument('--author-name', help='Commit author name')
    git_group.add_argument('--author-email', help='Commit author email')
    git_group.add_argument('--pr-number', help='Pull request number')
    git_group.add_argument('--pr-name', help='Pull request name/title')
    git_group.add_argument('--pr-author-name', help='Pull request author name')
    git_group.add_argument('--pr-author-email', help='Pull request author email')

    # Performance options
    perf_group = parser.add_argument_group('performance options')
    perf_group.add_argument(
        '--skip-line-program',
        action='store_true',
        help='Skip DWARF line program processing for faster analysis'
    )
    perf_group.add_argument(
        '--def',
        dest='linker_defs',
        action='append',
        metavar='VAR=VALUE',
        help='Define linker script variable (can be specified multiple times, '
             'e.g., --def __flash_size__=4096K)'
    )

    # Alert handling
    alert_group = parser.add_argument_group('alert options')
    alert_group.add_argument(
        '--dont-fail-on-alerts',
        action='store_true',
        help='Continue even if budget alerts are detected (default: fail on alerts)'
    )

    # Output options
    output_group = parser.add_argument_group('output options')
    output_group.add_argument(
        '--json',
        action='store_true',
        help='Output report as JSON (default is human-readable format)'
    )
    output_group.add_argument(
        '--all-symbols',
        action='store_true',
        help='Display all symbols instead of just top 20 (human-readable mode only)'
    )
    output_group.add_argument(
        '--output-raw-response',
        action='store_true',
        help='Output raw API response as JSON to stdout (for piping to GitHub Actions PR comment)'
    )

    return parser


def generate_report(
    elf_path: str,
    ld_scripts: str,
    skip_line_program: bool = False,
    linker_variables: Optional[Dict[str, Any]] = None
) -> dict:
    """
    Generate a memory footprint report from ELF and linker scripts.

    Args:
        elf_path: Path to ELF file
        ld_scripts: Space-separated linker script paths
        skip_line_program: Skip DWARF line program processing for faster analysis
        linker_variables: Optional dict of user-defined linker script variables

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
    logger.debug("Parsing memory regions from linker scripts...")
    try:
        parser = LinkerScriptParser(ld_array, elf_file=elf_path,
                                     user_variables=linker_variables)
        memory_regions_data = parser.parse_memory_regions()
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to parse memory regions: %s", e)
        raise ValueError(f"Failed to parse memory regions: {e}") from e

    # Generate JSON report
    logger.debug("Generating memory report...")
    try:
        generator = ReportGenerator(
            elf_path,
            memory_regions_data,
            skip_line_program=skip_line_program
        )
        report = generator.generate_report()
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to generate memory report: %s", e)
        raise ValueError(f"Failed to generate memory report: {e}") from e

    logger.info("Memory report generated successfully")
    return report


def upload_report(  # pylint: disable=too-many-arguments
    report: dict,
    commit_info: dict,
    target_name: str,
    api_key: Optional[str],
    *,
    api_url: str = DEFAULT_API_URL,
    build_failed: bool = None,
    is_github_mode: bool = False
) -> tuple[dict, str]:
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
        api_key: MemBrowse API key (None for tokenless fork PR uploads)
        api_url: MemBrowse API base URL (e.g., 'https://www.membrowse.com')
                 The /api/upload endpoint suffix is added automatically
        build_failed: Whether the build failed (keyword-only)
        is_github_mode: Whether --github flag is set (enables tokenless for fork PRs)

    Returns:
        tuple[dict, str]: (API response data, comparison URL if available)

    Raises:
        ValueError: If upload arguments are invalid
        RuntimeError: If upload fails
    """
    # Validate upload arguments
    is_valid, error_message = _validate_upload_arguments(
        api_key, target_name, is_github_mode=is_github_mode
    )
    if not is_valid:
        raise ValueError(error_message)

    # Set up log prefix
    log_prefix = _get_log_prefix(commit_info)

    logger.warning("%s: Uploading report to MemBrowse...", log_prefix)
    logger.info("Target: %s", target_name)

    # Build and enrich report
    enriched_report = _build_enriched_report(report, commit_info, target_name, build_failed)

    # Upload to MemBrowse
    response_data = _perform_upload(
        enriched_report, api_key, api_url, log_prefix, is_github_mode=is_github_mode
    )

    # Always print upload response details (success or failure)
    comparison_url = print_upload_response(response_data)

    # Validate upload success
    _validate_upload_success(response_data, log_prefix)

    logger.info("%s: Memory report uploaded successfully", log_prefix)
    return response_data, comparison_url


def _get_log_prefix(commit_info: dict) -> str:
    """Get log prefix from commit info."""
    if commit_info.get('commit_hash'):
        return f"({commit_info.get('commit_hash')})"
    return "MemBrowse"


def _build_enriched_report(
    report: dict,
    commit_info: dict,
    target_name: str,
    build_failed: bool = None
) -> dict:
    """Build enriched report with metadata."""
    metadata = {
        'git': commit_info,
        'repository': commit_info.get('repository'),
        'target_name': target_name,
        'analysis_version': version('membrowse')
    }

    # Add build_failed directly to metadata if provided
    if build_failed is not None:
        metadata['build_failed'] = build_failed

    return {
        'metadata': metadata,
        'memory_analysis': report
    }


def _perform_upload(
    enriched_report: dict,
    api_key: Optional[str],
    api_url: str,
    log_prefix: str,
    is_github_mode: bool = False
) -> dict:
    """Perform the actual upload to MemBrowse."""
    # Normalize API URL (append /api/upload)
    upload_endpoint = normalize_api_url(api_url)

    try:
        # Determine authentication strategy
        auth_context = determine_auth_strategy(
            api_key=api_key,
            auto_detect_fork=is_github_mode
        )
        uploader = MemBrowseUploader(auth_context, upload_endpoint)
        return uploader.upload_report(enriched_report)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("%s: Failed to upload report to %s: %s", log_prefix, upload_endpoint, e)
        raise RuntimeError(f"Failed to upload report to {upload_endpoint}: {e}") from e


def _validate_upload_success(response_data: dict, log_prefix: str) -> None:
    """Validate that upload was successful."""
    if not response_data.get('success'):
        logger.error("%s: Upload failed - see response details above", log_prefix)
        raise RuntimeError("Upload failed - see response details above")


def _check_budget_alerts(response_data: dict, commit_info: dict) -> None:
    """Check for budget alerts and fail if necessary."""
    data = response_data.get('data', {})
    log_prefix = _get_log_prefix(commit_info)
    alerts = data.get('alerts') or {}
    budget_alerts = alerts.get('budgets', [])

    if budget_alerts:
        error_msg = (
            f"Budget Alert Error: {len(budget_alerts)} budget(s) exceeded. "
            "Use --dont-fail-on-alerts to continue despite alerts."
        )
        logger.error("%s: %s", log_prefix, error_msg)
        raise RuntimeError(
            f"Budget alerts detected: {len(budget_alerts)} budget(s) exceeded"
        )


def _parse_linker_definitions(linker_defs: list) -> Optional[Dict[str, str]]:
    """
    Parse --def linker variable definitions from command line.

    Args:
        linker_defs: List of KEY=VALUE strings from --def arguments

    Returns:
        Dictionary of parsed variables, or None if no valid definitions
    """
    if not linker_defs:
        return None

    linker_variables = {}
    for def_str in linker_defs:
        if '=' not in def_str:
            logger.warning("Ignoring invalid --def argument (missing '='): %s", def_str)
            continue
        key, value = def_str.split('=', 1)
        key = key.strip()
        value = value.strip()
        if not key:
            logger.warning("Ignoring invalid --def argument (empty key): %s", def_str)
            continue
        linker_variables[key] = value
        logger.debug("User-defined linker variable: %s = %s", key, value)

    return linker_variables if linker_variables else None


def _handle_upload_and_alerts(
    report: dict,
    args: argparse.Namespace,
    commit_info: dict,
) -> int:
    """
    Handle report upload and budget alert checking.

    Args:
        report: The generated memory report
        args: Parsed command-line arguments
        commit_info: Git commit metadata
        verbose: Verbose logging flag

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        response_data, comparison_url = upload_report(
            report=report,
            commit_info=commit_info,
            target_name=getattr(args, 'target_name', None),
            api_key=getattr(args, 'api_key', None),
            api_url=getattr(args, 'api_url', DEFAULT_API_URL),
            is_github_mode=getattr(args, 'github', False),
        )

        # Check for budget alerts first to determine exit code
        exit_code = 0
        if not getattr(args, 'dont_fail_on_alerts', False):
            try:
                _check_budget_alerts(response_data, commit_info)
            except RuntimeError:
                # Budget alerts detected - should fail CI
                exit_code = 1

        # Output raw API response to stdout if requested (for piping to PR comment script)
        if getattr(args, 'output_raw_response', False):
            output_data = {
                'comparison_url': comparison_url or '',
                'api_response': response_data or {},
                'target_name': getattr(args, 'target_name', ''),
                'pr_number': commit_info.get('pr_number', '')
            }
            print(json.dumps(output_data, indent=2))
            return exit_code

        # If we reach here and have alerts, re-raise to fail
        if exit_code != 0:
            raise RuntimeError("Budget alerts detected")

        return 0
    except (ValueError, RuntimeError) as e:
        logger.error("Failed to upload report: %s", e)
        return 1


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
    # Parse linker variable definitions
    linker_variables = _parse_linker_definitions(getattr(args, 'linker_defs', None))

    # Generate report
    try:
        report = generate_report(
            elf_path=args.elf_path,
            ld_scripts=args.ld_scripts,
            skip_line_program=getattr(args, 'skip_line_program', False),
            linker_variables=linker_variables
        )
    except ValueError as e:
        logger.error("Failed to generate report: %s", e)
        return 1

    # Check if upload mode is enabled
    upload_mode = getattr(args, 'upload', False) or getattr(args, 'github', False)

    # If not uploading, output report to stdout
    if not upload_mode:
        if getattr(args, 'json', False):
            print(json.dumps(report, indent=2))
        else:
            show_all_symbols = getattr(args, 'all_symbols', False)
            print(format_report_human_readable(report, show_all_symbols=show_all_symbols))
        return 0

    # Build commit_info dict in metadata['git'] format
    arg_to_metadata_map = {
        'commit_sha': 'commit_hash',
        'parent_sha': 'parent_commit_hash',
        'base_sha': 'base_commit_hash',
        'branch_name': 'branch_name',
        'repo_name': 'repository',
        'commit_message': 'commit_message',
        'commit_timestamp': 'commit_timestamp',
        'author_name': 'author_name',
        'author_email': 'author_email',
        'pr_number': 'pr_number',
        'pr_name': 'pr_name',
        'pr_author_name': 'pr_author_name',
        'pr_author_email': 'pr_author_email',
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

    # Upload report and handle alerts
    return _handle_upload_and_alerts(report, args, commit_info)
