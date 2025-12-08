"""GitHub PR comment utilities for posting memory analysis results."""

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

from .budget_alerts import iter_budget_alerts
from .github_common import (
    is_gh_cli_available,
    create_or_update_comment,
    build_memory_change_row,
    handle_comment_error,
    configure_logging,
)

logger = logging.getLogger(__name__)

# Unique marker to identify MemBrowse comments
COMMENT_MARKER = "<!-- membrowse-pr-comment -->"


def _extract_pr_number(results: list[dict]) -> str:
    """
    Extract PR number from results.

    Args:
        results: List of result dicts

    Returns:
        PR number as string

    Raises:
        ValueError: If no PR number found in results
    """
    for result in results:
        pr_number = result.get('pr_number')
        if pr_number:
            return str(pr_number)

    raise ValueError("No PR number found in results")


def post_combined_pr_comment(results: list[dict]) -> None:
    """
    Post a single PR comment with combined memory analysis results from multiple targets.

    Args:
        results: List of result dicts, each containing comparison_url, api_response,
            target_name, pr_number
    """
    if not is_gh_cli_available():
        logger.warning("GitHub CLI (gh) not available, skipping PR comment")
        return

    try:
        pr_number = _extract_pr_number(results)
    except ValueError as e:
        logger.warning("Cannot post PR comment: %s", e)
        return

    comment_body = _build_combined_comment_body(results)

    try:
        create_or_update_comment(comment_body, pr_number, COMMENT_MARKER)
        logger.info("Posted combined PR comment for %d targets", len(results))
    except subprocess.CalledProcessError as e:
        handle_comment_error(e, "PR comment")
    except Exception as e:  # pylint: disable=broad-exception-caught
        handle_comment_error(e, "PR comment")


def _format_section_delta(section: dict) -> str | None:
    """
    Format a section's size change.

    Args:
        section: Section dict with 'name', 'size', and 'old' containing 'size'

    Returns:
        Formatted string like '.bss +400 B' or None if no size change
    """
    current_size = section.get('size', 0)
    old_data = section.get('old', {})
    old_size = old_data.get('size')

    # Only show if size changed
    if old_size is None or old_size == current_size:
        return None

    delta = current_size - old_size
    delta_str = f"+{delta:,}" if delta >= 0 else f"{delta:,}"
    return f"{section.get('name', 'unknown')} {delta_str} B"


def _group_sections_by_region(sections_data: dict) -> dict[str, list[dict]]:
    """
    Group modified sections by their region name.

    Args:
        sections_data: Dict with 'modified' list of section dicts

    Returns:
        Dict mapping region name to list of modified sections
    """
    sections_by_region: dict[str, list[dict]] = {}
    modified_sections = sections_data.get('modified', [])

    for section in modified_sections:
        region_name = section.get('region', 'Unknown')
        if region_name not in sections_by_region:
            sections_by_region[region_name] = []
        sections_by_region[region_name].append(section)

    return sections_by_region


def _format_memory_change_row(region: dict, section_changes: list[str]) -> dict | None:
    """
    Format a memory change row for display.

    Args:
        region: Dictionary containing region data
        section_changes: List of formatted section change strings

    Returns:
        Dictionary with 'region' and 'usage' keys, or None if no change
    """
    row_data = build_memory_change_row(region)
    if row_data is None:
        return None

    limit_size = row_data['limit_size']
    current_used = row_data['current_used']

    # Build section changes string
    sections_str = ', '.join(section_changes) if section_changes else ''

    if limit_size > 0:
        util_pct = current_used / limit_size * 100
        if sections_str:
            usage_str = (
                f"{sections_str} ({row_data['delta_pct_str']}, "
                f"{current_used:,} B / {limit_size:,} B, total: {util_pct:.0f}% used)"
            )
        else:
            usage_str = (
                f"{row_data['delta_str']} B ({row_data['delta_pct_str']}, "
                f"{current_used:,} B / {limit_size:,} B, total: {util_pct:.0f}% used)"
            )
    else:
        if sections_str:
            usage_str = (
                f"{sections_str} ({row_data['delta_pct_str']}, "
                f"{current_used:,} B)"
            )
        else:
            usage_str = (
                f"{row_data['delta_str']} B ({row_data['delta_pct_str']}, "
                f"{current_used:,} B)"
            )

    return {
        'region': row_data['region_name'],
        'usage': usage_str
    }


def _format_target_changes(changes: dict) -> list[str]:
    """
    Format memory changes for a single target into markdown lines.

    Args:
        changes: Dictionary containing 'regions' and 'sections' with change data

    Returns:
        List of markdown-formatted strings describing memory changes
    """
    if not changes:
        return []

    regions_data = changes.get('regions', {})
    sections_data = changes.get('sections', {})
    modified_regions = regions_data.get('modified', [])

    if not modified_regions:
        return []

    # Group section changes by region
    sections_by_region = _group_sections_by_region(sections_data)

    lines = []
    for region in modified_regions:
        region_name = region.get('name', 'Unknown')

        # Get section changes for this region
        region_sections = sections_by_region.get(region_name, [])
        section_changes = []
        for section in region_sections:
            delta_str = _format_section_delta(section)
            if delta_str:
                section_changes.append(delta_str)

        row = _format_memory_change_row(region, section_changes)
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


def _process_target_result(result: dict) -> tuple[str | None, str, str | None, list[str]]:
    """
    Process a single target result and extract section data.

    Args:
        result: Dictionary containing target analysis result

    Returns:
        Tuple of (section_markdown, target_name, comparison_url, alert_lines)
    """
    target_name = result.get('target_name', 'Unknown')
    comparison_url = result.get('comparison_url')
    data = result.get('api_response', {}).get('data', {})

    change_lines = _format_target_changes(data.get('changes', {}))
    alert_lines = _format_target_alerts(data.get('alerts'))

    section = _build_target_section(
        target_name,
        comparison_url,
        change_lines,
        alert_lines
    )
    return section, target_name, comparison_url, alert_lines


def _format_target_link(target_name: str, comparison_url: str | None) -> str:
    """
    Format a target name as a markdown link if URL is available.

    Args:
        target_name: Name of the target
        comparison_url: Optional URL to comparison view

    Returns:
        Markdown link if URL available, otherwise plain target name
    """
    if comparison_url:
        return f"[{target_name}]({comparison_url})"
    return target_name


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
        section, target_name, comparison_url, alert_lines = _process_target_result(result)

        if alert_lines:
            has_any_alerts = True

        if section:
            targets_with_changes.append(section)
        else:
            targets_without_changes.append((target_name, comparison_url))

    # Add targets with changes first
    if targets_with_changes:
        body_parts.extend(targets_with_changes)
        body_parts.append("")

    # Summarize targets without changes
    if targets_without_changes:
        body_parts.append("*No memory changes detected for:*")
        for target_name, comparison_url in targets_without_changes:
            target_link = _format_target_link(target_name, comparison_url)
            body_parts.append(f"- {target_link}")
        body_parts.append("")

    # Add warning banner if any alerts
    if has_any_alerts:
        body_parts.insert(3, "> :warning: **Budget alerts detected** - see details below")
        body_parts.insert(4, "")

    return "\n".join(body_parts)


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
    configure_logging()
    main()
