"""GitHub PR comment utilities for combined memory analysis results."""

import argparse
import json
import os
import subprocess
import logging
import sys
from pathlib import Path

from .budget_alerts import iter_budget_alerts

logger = logging.getLogger(__name__)

# Unique marker to identify MemBrowse combined comments
COMMENT_MARKER = "<!-- membrowse-pr-comment-combined -->"

# Timeout constants for subprocess calls (in seconds)
GH_VERSION_TIMEOUT = 5
GH_COMMENT_TIMEOUT = 30


def post_combined_pr_comment(results: list[dict]) -> None:
    """
    Post a single PR comment with combined memory analysis results from multiple targets.

    Args:
        results: List of result dicts, each containing comparison_url, api_response, target_name
    """
    # Verify we're running in a PR context
    event_name = os.environ.get('GITHUB_EVENT_NAME', '')
    if event_name != 'pull_request':
        logger.debug("Not a pull request event (%s), skipping PR comment", event_name)
        return

    # Verify gh CLI is available
    if not _is_gh_cli_available():
        logger.warning("GitHub CLI (gh) not available, skipping PR comment")
        return

    # Build combined comment body
    comment_body = _build_combined_comment_body(results)

    # Create new PR comment
    try:
        _create_comment(comment_body)
        logger.info("Created combined PR comment for %d targets", len(results))
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to post PR comment: {e}"
        if e.stderr:
            stderr_output = e.stderr.decode('utf-8') if isinstance(e.stderr, bytes) else e.stderr
            error_msg += f"\ngh stderr: {stderr_output.strip()}"
        logger.warning(error_msg)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("Failed to post PR comment: %s", e)


def _is_gh_cli_available() -> bool:
    """Check if GitHub CLI (gh) is available and executable."""
    try:
        subprocess.run(
            ['gh', '--version'],
            check=True,
            capture_output=True,
            timeout=GH_VERSION_TIMEOUT
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _build_memory_change_row(region: dict) -> dict | None:
    """
    Build a single table row for memory changes.

    Args:
        region: Dictionary containing region data with 'used_size', 'old', 'name', and 'limit_size'

    Returns:
        Dictionary with 'region' and 'usage' keys, or None if no change detected
    """
    current_used = region.get('used_size', 0)
    old_data = region.get('old', {})
    old_used = old_data.get('used_size')

    if old_used is None or old_used == current_used:
        return None

    delta = current_used - old_used
    delta_pct = (delta / old_used * 100) if old_used > 0 else 0

    delta_str = f"+{delta:,}" if delta >= 0 else f"{delta:,}"
    delta_pct_str = f"+{delta_pct:.1f}%" if delta >= 0 else f"{delta_pct:.1f}%"

    limit_size = region.get('limit_size', 0)
    if limit_size > 0:
        util_pct = current_used / limit_size * 100
        usage_str = (
            f"{delta_str} B ({delta_pct_str}, "
            f"{current_used:,} B / {limit_size:,} B, {util_pct:.1f}%)"
        )
    else:
        usage_str = f"{delta_str} B ({delta_pct_str}, {current_used:,} B)"

    return {
        'region': region.get('name', 'Unknown'),
        'usage': usage_str
    }


def _format_target_changes(changes: dict) -> list[str]:
    """
    Format memory changes for a single target into markdown lines.

    Args:
        changes: Dictionary containing 'regions' with 'modified' list

    Returns:
        List of markdown-formatted strings describing memory changes
    """
    if not changes:
        return []

    regions_data = changes.get('regions', {})
    modified_regions = regions_data.get('modified', [])

    if not modified_regions:
        return []

    lines = []
    for region in modified_regions:
        row = _build_memory_change_row(region)
        if row:
            lines.append(f"  - **{row['region']}**: {row['usage']}")

    return lines


def _format_target_alerts(alerts: dict) -> list[str]:
    """
    Format budget alerts for a single target into markdown lines.

    Args:
        alerts: Dictionary containing 'budgets' list with alert data

    Returns:
        List of markdown-formatted strings describing budget alerts
    """
    if not alerts:
        return []

    budgets = alerts.get('budgets', [])
    if not budgets:
        return []

    lines = []
    current_budget = None
    for alert in iter_budget_alerts(budgets):
        if current_budget != alert.budget_name:
            current_budget = alert.budget_name
            lines.append(f"  - **{alert.budget_name}**:")
        lines.append(
            f"    - {alert.region}: {alert.usage:,} B "
            f"(exceeded by {alert.exceeded:,} B)"
        )

    return lines


def _build_target_section(
    target_name: str,
    comparison_url: str | None,
    change_lines: list[str],
    alert_lines: list[str]
) -> str | None:
    """
    Build a markdown section for a single target's memory changes.

    Args:
        target_name: Name of the target
        comparison_url: Optional URL to comparison view
        change_lines: List of formatted memory change lines
        alert_lines: List of formatted budget alert lines

    Returns:
        Markdown string for the target section, or None if no changes
    """
    if not change_lines and not alert_lines:
        return None

    # Target header with link if available
    if comparison_url:
        header = f"### [{target_name}]({comparison_url})"
    else:
        header = f"### {target_name}"

    section_parts = [header]
    section_parts.extend(change_lines)

    if alert_lines:
        section_parts.append("")
        section_parts.append("**Budget Alerts:**")
        section_parts.extend(alert_lines)

    return '\n'.join(section_parts)


def _process_target_result(result: dict) -> tuple[str | None, str, list[str]]:
    """
    Process a single target result and extract section data.

    Args:
        result: Dictionary containing target analysis result

    Returns:
        Tuple of (section_markdown, target_name, alert_lines)
    """
    target_name = result.get('target_name', 'Unknown')
    data = result.get('api_response', {}).get('data', {})

    change_lines = _format_target_changes(data.get('changes', {}))
    alert_lines = _format_target_alerts(data.get('alerts'))

    section = _build_target_section(
        target_name,
        result.get('comparison_url'),
        change_lines,
        alert_lines
    )
    return section, target_name, alert_lines


def _build_combined_comment_body(results: list[dict]) -> str:
    """
    Build the combined PR comment body with memory analysis results from all targets.

    Args:
        results: List of result dicts from each target

    Returns:
        str: Markdown-formatted comment body
    """
    body_parts = [
        COMMENT_MARKER,
        "## MemBrowse Memory Report",
        ""
    ]

    has_any_alerts = False
    targets_with_changes = []
    targets_without_changes = []

    for result in results:
        section, target_name, alert_lines = _process_target_result(result)

        if alert_lines:
            has_any_alerts = True

        if section:
            targets_with_changes.append(section)
        else:
            targets_without_changes.append(target_name)

    # Add targets with changes first
    if targets_with_changes:
        body_parts.extend(targets_with_changes)
        body_parts.append("")

    # Summarize targets without changes
    if targets_without_changes:
        if len(targets_without_changes) == 1:
            body_parts.append(f"*No memory changes detected for {targets_without_changes[0]}*")
        else:
            targets_list = ', '.join(targets_without_changes)
            body_parts.append(f"*No memory changes detected for: {targets_list}*")
        body_parts.append("")

    # Add warning banner if any alerts
    if has_any_alerts:
        body_parts.insert(3, "> :warning: **Budget alerts detected** - see details below")
        body_parts.insert(4, "")

    return "\n".join(body_parts)


def _get_pr_number() -> str:
    """Extract PR number from GITHUB_REF environment variable."""
    github_ref = os.environ.get('GITHUB_REF', '')

    if not github_ref.startswith('refs/pull/'):
        raise ValueError(
            f"Cannot determine PR number: GITHUB_REF='{github_ref}' "
            "does not match expected format 'refs/pull/<number>/merge'"
        )

    parts = github_ref.split('/')
    if len(parts) < 3:
        raise ValueError(
            f"Cannot parse PR number from GITHUB_REF='{github_ref}'"
        )

    pr_number = parts[2]
    if not pr_number.isdigit():
        raise ValueError(
            f"Invalid PR number '{pr_number}' extracted from GITHUB_REF='{github_ref}'"
        )

    return pr_number


def _create_comment(body: str) -> None:
    """
    Create a new PR comment using GitHub CLI.

    Args:
        body: The markdown content for the comment

    Raises:
        subprocess.CalledProcessError: If gh command fails
        ValueError: If PR number cannot be determined
    """
    pr_number = _get_pr_number()

    subprocess.run(
        ['gh', 'pr', 'comment', pr_number, '--body', body],
        check=True,
        capture_output=True,
        timeout=GH_COMMENT_TIMEOUT
    )


def main():
    """
    Main entry point for combined GitHub comment posting.

    Reads JSON result files from command line arguments or a directory.
    """
    parser = argparse.ArgumentParser(
        description='Post combined MemBrowse PR comment from multiple target results'
    )
    parser.add_argument(
        'files',
        nargs='*',
        help='JSON result files to combine (or use --dir)'
    )
    parser.add_argument(
        '--dir',
        dest='directory',
        help='Directory containing JSON result files'
    )
    args = parser.parse_args()

    # Collect result files
    result_files = []
    if args.files:
        result_files = [Path(f) for f in args.files]
    elif args.directory:
        result_files = list(Path(args.directory).glob('*.json'))
    else:
        parser.error("Either provide JSON files as arguments or use --dir")

    if not result_files:
        logger.error("No result files found")
        sys.exit(1)

    # Load all results
    results = []
    for filepath in result_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                results.append(data)
                logger.info("Loaded result from %s", filepath)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Failed to load %s: %s", filepath, e)

    if not results:
        logger.error("No valid results loaded")
        sys.exit(1)

    # Sort results by target name for consistent ordering
    results.sort(key=lambda r: r.get('target_name', ''))

    # Post combined PR comment
    post_combined_pr_comment(results)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )
    main()
