"""GitHub PR comment utilities for posting memory analysis results."""

import argparse
import json
import os
import subprocess
import logging

from .budget_alerts import iter_budget_alerts

logger = logging.getLogger(__name__)

# Unique marker to identify MemBrowse comments
COMMENT_MARKER = "<!-- membrowse-pr-comment -->"


def post_pr_comment(
    comparison_url: str = None,
    api_response: dict = None,
    target_name: str = None
) -> None:
    """
    Post a PR comment with memory analysis results.

    This function will create a new comment on each run.

    Args:
        comparison_url: URL to build comparison page (can be None)
        api_response: Full API response data including changes and alerts (optional)
        target_name: Target name (e.g., esp32, stm32f4) (optional)
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

    # Build comment body
    comment_body = _build_comment_body(comparison_url, api_response, target_name)

    # Create new PR comment
    try:
        _create_comment(comment_body)
        logger.info("Created PR comment")
    except subprocess.CalledProcessError as e:
        # Include stderr output from gh command for debugging
        error_msg = f"Failed to post PR comment: {e}"
        if e.stderr:
            stderr_output = e.stderr.decode('utf-8') if isinstance(e.stderr, bytes) else e.stderr
            error_msg += f"\ngh stderr: {stderr_output.strip()}"
        logger.warning(error_msg)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("Failed to post PR comment: %s", e)


def _is_gh_cli_available() -> bool:
    """Check if GitHub CLI (gh) is available."""
    try:
        subprocess.run(
            ['gh', '--version'],
            check=True,
            capture_output=True,
            timeout=5
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _build_memory_change_row(region: dict) -> dict:
    """
    Build a single table row for memory changes.

    Args:
        region: Region data with current and old values

    Returns:
        dict: Row data with formatted strings, or None if no changes
    """
    current_used = region.get('used_size', 0)
    old_data = region.get('old', {})
    old_used = old_data.get('used_size')

    # Only show if used_size changed
    if old_used is None or old_used == current_used:
        return None

    # Calculate delta
    delta = current_used - old_used
    delta_pct = (delta / old_used * 100) if old_used > 0 else 0

    # Format delta with sign
    delta_str = f"+{delta:,}" if delta >= 0 else f"{delta:,}"
    delta_pct_str = f"+{delta_pct:.1f}%" if delta >= 0 else f"{delta_pct:.1f}%"

    # Build usage string: delta (current used [out of limit, utilization%])
    limit_size = region.get('limit_size', 0)
    if limit_size > 0:
        util_pct = current_used / limit_size * 100
        usage_str = (
            f"{delta_str} B ({delta_pct_str}, "
            f"{current_used:,} B used out of {limit_size:,} B, {util_pct:.1f}%)"
        )
    else:
        usage_str = f"{delta_str} B ({delta_pct_str}, {current_used:,} B used)"

    return {
        'region': region.get('name', 'Unknown'),
        'section': '',
        'usage': usage_str
    }


def _format_table_with_alignment(rows: list) -> str:
    """
    Format rows into aligned markdown table.

    Args:
        rows: List of row dictionaries with region, section, usage

    Returns:
        str: Formatted markdown table
    """
    # Calculate column widths
    max_region = max(max(len(row['region']) for row in rows), len("Region"))
    max_section = max(max(len(row['section']) for row in rows), len("Section"))
    max_usage = max(max(len(row['usage']) for row in rows), len("Changes"))

    lines = []
    # Header row
    header = (
        f"| {'Region'.ljust(max_region)} | {'Section'.ljust(max_section)} | "
        f"{'Changes'.ljust(max_usage)} |"
    )
    lines.append(header)
    # Separator row
    separator = (
        f"|{'-' * (max_region + 2)}|{'-' * (max_section + 2)}|"
        f"{'-' * (max_usage + 2)}|"
    )
    lines.append(separator)

    # Data rows
    for row in rows:
        lines.append(
            f"| {row['region'].ljust(max_region)} | "
            f"{row['section'].ljust(max_section)} | "
            f"{row['usage'].ljust(max_usage)} |"
        )

    return "\n".join(lines)


def _get_sections_for_region(section_changes: dict, region_name: str) -> list:
    """
    Get modified sections that belong to a specific region.

    Args:
        section_changes: Section changes data with 'modified' key
        region_name: Name of the parent region to filter by

    Returns:
        list: List of formatted row dictionaries for sections in this region
    """
    if not section_changes:
        return []

    modified_sections = section_changes.get('modified', [])
    section_rows = []

    for section in modified_sections:
        # Only include sections that belong to this region
        if section.get('region') != region_name:
            continue

        section_name = section.get('name', 'Unknown')
        current_size = section.get('size', 0)
        old_data = section.get('old', {})
        old_size = old_data.get('size')

        # Skip if no size change (shouldn't happen in modified, but be safe)
        if old_size is None or old_size == current_size:
            continue

        # Calculate delta
        delta = current_size - old_size

        # Format delta with sign
        delta_str = f"+{delta:,}" if delta >= 0 else f"{delta:,}"

        # Build usage string: delta (current used)
        usage_str = f"{delta_str} B ({current_size:,} B used)"

        # Create row with section in its own column
        section_rows.append({
            'region': '',
            'section': section_name,
            'usage': usage_str
        })

    return section_rows


def _format_memory_changes(changes: dict) -> str:
    """
    Format memory changes into a markdown table.

    Args:
        changes: Changes data from API response with 'regions' and 'sections' keys

    Returns:
        str: Markdown formatted table of memory changes
    """
    if not changes:
        return ""

    regions_data = changes.get('regions', {})
    modified_regions = regions_data.get('modified', [])

    if not modified_regions:
        return ""

    # Get section changes for matching sections to regions
    section_changes = changes.get('sections', {})

    # Build table rows (regions and their sections)
    rows = []
    for region in modified_regions:
        # Add region row
        row = _build_memory_change_row(region)
        if row:
            rows.append(row)

            # Add section rows nested under this region
            region_name = region.get('name', 'Unknown')
            section_rows = _get_sections_for_region(section_changes, region_name)
            rows.extend(section_rows)

    if not rows:
        return ""

    # Build and return formatted table
    table = _format_table_with_alignment(rows)
    return f"{table}\n"


def _format_budget_alerts(alerts: dict) -> str:
    """
    Format budget alerts into markdown.

    Args:
        alerts: Alerts data from API response with 'budgets' key

    Returns:
        str: Markdown formatted budget alerts
    """
    if not alerts:
        return ""

    budgets = alerts.get('budgets', [])
    if not budgets:
        return ""

    lines = ["### Budget Alerts ⚠️", ""]

    current_budget = None
    for alert in iter_budget_alerts(budgets):
        # Add budget name header when we encounter a new budget
        if current_budget != alert.budget_name:
            current_budget = alert.budget_name
            lines.append(f"**{alert.budget_name}**")

        # Add region alert
        if alert.percentage is not None:
            lines.append(
                f"- **{alert.region}**: {alert.usage:,} B / {alert.limit:,} B "
                f"(exceeded by {alert.exceeded:,} B, +{alert.percentage:.1f}%)"
            )
        else:
            lines.append(
                f"- **{alert.region}**: {alert.usage:,} B "
                f"(exceeded by {alert.exceeded:,} B)"
            )

    # Add final empty line
    lines.append("")

    return "\n".join(lines)


def _build_comment_body(
    comparison_url: str = None,
    api_response: dict = None,
    target_name: str = None
) -> str:
    """
    Build the PR comment body with memory analysis results.

    Args:
        comparison_url: URL to build comparison page (can be None)
        api_response: Full API response data including changes and alerts (optional)
        target_name: Target name (e.g., esp32, stm32f4) (optional)

    Returns:
        str: Markdown-formatted comment body
    """
    # Start with header and marker
    body_parts = [
        COMMENT_MARKER,
        "## MemBrowse Memory Report",
        ""
    ]

    # Extract data from API response
    data = api_response.get('data', {}) if api_response else {}
    changes = data.get('changes', {})
    alerts = data.get('alerts')

    # Display target name if available
    if target_name:
        body_parts.extend([
            f"**Target:** {target_name}",
            ""
        ])

    # Add memory changes table if available
    memory_changes_text = _format_memory_changes(changes)
    if memory_changes_text:
        body_parts.append(memory_changes_text)

    # Add budget alerts if available
    budget_alerts_text = _format_budget_alerts(alerts)
    if budget_alerts_text:
        body_parts.append(budget_alerts_text)

    # Add comparison link
    if comparison_url:
        body_parts.extend([
            f"[View detailed comparison →]({comparison_url})",
            ""
        ])
    else:
        body_parts.extend([
            "*Build comparison not available (this may be the first build for this project)*",
            ""
        ])

    return "\n".join(body_parts)


def _get_pr_number() -> str:
    """
    Extract PR number from GITHUB_REF environment variable.

    Returns:
        str: PR number

    Raises:
        ValueError: If PR number cannot be determined from GITHUB_REF
    """
    github_ref = os.environ.get('GITHUB_REF', '')

    # Expected format: refs/pull/123/merge
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
    Create a new PR comment.

    Args:
        body: Comment body
    """
    pr_number = _get_pr_number()

    subprocess.run(
        ['gh', 'pr', 'comment', pr_number, '--body', body],
        check=True,
        capture_output=True,
        timeout=30
    )


def main():
    """
    Main entry point for GitHub comment posting.

    Reads comparison URL and API response from JSON file specified by --url-file argument.
    """
    parser = argparse.ArgumentParser(description='Post MemBrowse PR comment')
    parser.add_argument(
        '--url-file',
        required=True,
        help='File containing comparison URL and API response data (JSON format)'
    )
    args = parser.parse_args()

    # Read comparison URL and API response from file
    comparison_url = None
    api_response = None
    target_name = None
    try:
        with open(args.url_file, 'r', encoding='utf-8') as f:
            # Try to read as JSON first
            try:
                data = json.load(f)
                comparison_url = data.get('comparison_url')
                api_response = data.get('api_response')
                target_name = data.get('target_name')
            except json.JSONDecodeError:
                # Fall back to plain text for backwards compatibility
                f.seek(0)
                url_content = f.read().strip()
                comparison_url = url_content if url_content else None
                logger.debug("Read plain text format (backwards compatibility)")

    except FileNotFoundError:
        logger.warning("URL file not found: %s", args.url_file)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("Failed to read URL file: %s", e)

    # Post PR comment
    post_pr_comment(comparison_url, api_response, target_name)


if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )
    main()
