"""GitHub PR comment utilities for posting memory analysis results."""

import argparse
import json
import os
import subprocess
import logging

logger = logging.getLogger(__name__)

# Unique marker to identify MemBrowse comments
COMMENT_MARKER = "<!-- membrowse-pr-comment -->"


def post_or_update_pr_comment(comparison_url: str = None, api_response: dict = None) -> None:
    """
    Post or update a PR comment with memory analysis results.

    This function will:
    - Find an existing MemBrowse comment and update it (if found)
    - Create a new comment if no existing comment is found
    - Handle cases where no comparison URL is available

    Args:
        comparison_url: URL to build comparison page (can be None)
        api_response: Full API response data including changes and alerts (optional)
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
    comment_body = _build_comment_body(comparison_url, api_response)

    # Try to find and update existing comment, or create new one
    try:
        existing_comment_id = _find_existing_comment()
        if existing_comment_id:
            _update_comment(existing_comment_id, comment_body)
            logger.info("Updated existing PR comment")
        else:
            _create_comment(comment_body)
            logger.info("Created new PR comment")
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

    # Calculate utilization if limit_size available
    limit_size = region.get('limit_size', 0)
    if limit_size > 0:
        util_pct = current_used / limit_size * 100
        util_str = f"{util_pct:.1f}%"
    else:
        util_str = "N/A"

    return {
        'name': region.get('name', 'Unknown'),
        'used': f"{current_used:,} B",
        'change': f"{delta_str} B ({delta_pct_str})",
        'utilization': util_str
    }


def _format_table_with_alignment(rows: list) -> str:
    """
    Format rows into aligned markdown table.

    Args:
        rows: List of row dictionaries with name, used, change, utilization

    Returns:
        str: Formatted markdown table
    """
    # Calculate column widths
    max_name = max(max(len(row['name']) for row in rows), len("Region"))
    max_used = max(max(len(row['used']) for row in rows), len("Used"))
    max_change = max(max(len(row['change']) for row in rows), len("Change"))
    max_util = max(max(len(row['utilization']) for row in rows), len("Utilization"))

    lines = []
    # Header row
    header = (
        f"| {'Region'.ljust(max_name)} | {'Used'.rjust(max_used)} | "
        f"{'Change'.rjust(max_change)} | {'Utilization'.rjust(max_util)} |"
    )
    lines.append(header)
    # Separator row
    separator = (
        f"|{'-' * (max_name + 2)}|{'-' * (max_used + 2)}:|"
        f"{'-' * (max_change + 2)}:|{'-' * (max_util + 2)}:|"
    )
    lines.append(separator)

    # Data rows
    for row in rows:
        lines.append(
            f"| {row['name'].ljust(max_name)} | "
            f"{row['used'].rjust(max_used)} | "
            f"{row['change'].rjust(max_change)} | "
            f"{row['utilization'].rjust(max_util)} |"
        )

    return "\n".join(lines)


def _format_memory_changes(changes: dict) -> str:
    """
    Format memory changes into a markdown table.

    Args:
        changes: Changes data from API response with 'regions' key

    Returns:
        str: Markdown formatted table of memory changes
    """
    if not changes:
        return ""

    regions_data = changes.get('regions', {})
    modified_regions = regions_data.get('modified', [])

    if not modified_regions:
        return ""

    # Build table rows
    rows = []
    for region in modified_regions:
        row = _build_memory_change_row(region)
        if row:
            rows.append(row)

    if not rows:
        return ""

    # Build and return formatted table
    table = _format_table_with_alignment(rows)
    return f"### Memory Changes\n\n{table}\n"


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

    for budget in budgets:
        budget_name = budget.get('budget_name', 'Unknown')
        exceeded_regions = budget.get('exceeded_regions', [])
        exceeded_by = budget.get('exceeded_by', {})
        current_usage = budget.get('current_usage', {})
        limits = budget.get('limits', {})

        lines.append(f"**{budget_name}**")

        for region in exceeded_regions:
            usage = current_usage.get(region, 0)
            limit = limits.get(region, 0)
            exceeded = exceeded_by.get(region, 0)

            if limit > 0:
                pct = exceeded / limit * 100
                lines.append(
                    f"- **{region}**: {usage:,} B / {limit:,} B "
                    f"(exceeded by {exceeded:,} B, +{pct:.1f}%)"
                )
            else:
                lines.append(f"- **{region}**: {usage:,} B (exceeded by {exceeded:,} B)")

        lines.append("")

    return "\n".join(lines)


def _build_comment_body(comparison_url: str = None, api_response: dict = None) -> str:
    """
    Build the PR comment body with memory analysis results.

    Args:
        comparison_url: URL to build comparison page (can be None)
        api_response: Full API response data including changes and alerts (optional)

    Returns:
        str: Markdown-formatted comment body
    """
    # Start with header and marker
    body_parts = [
        COMMENT_MARKER,
        "## MemBrowse Memory Analysis",
        ""
    ]

    # Extract data from API response
    data = api_response.get('data', {}) if api_response else {}
    changes = data.get('changes', {})
    alerts = data.get('alerts')

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


def _find_existing_comment() -> str:
    """
    Find the ID of an existing MemBrowse comment on the current PR.

    Returns:
        str: Comment ID if found, None otherwise
    """
    try:
        # List all comments on the PR and search for our marker
        result = subprocess.run(
            ['gh', 'pr', 'view', '--json', 'comments', '--jq',
             f'.comments[] | select(.body | contains("{COMMENT_MARKER}")) | .id'],
            check=True,
            capture_output=True,
            text=True,
            timeout=30
        )

        comment_id = result.stdout.strip()
        return comment_id if comment_id else None

    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.debug("Failed to find existing comment: %s", e)
        return None


def _update_comment(comment_id: str, body: str) -> None:
    """
    Update an existing PR comment.

    Args:
        comment_id: ID of the comment to update
        body: New comment body
    """
    subprocess.run(
        ['gh', 'api', '-X', 'PATCH',
         f'repos/{{owner}}/{{repo}}/issues/comments/{comment_id}',
         '-f', f'body={body}'],
        check=True,
        capture_output=True,
        timeout=30
    )


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
    try:
        with open(args.url_file, 'r', encoding='utf-8') as f:
            # Try to read as JSON first
            try:
                data = json.load(f)
                comparison_url = data.get('comparison_url')
                api_response = data.get('api_response')
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

    # Post or update PR comment
    post_or_update_pr_comment(comparison_url, api_response)


if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )
    main()
