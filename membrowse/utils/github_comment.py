"""GitHub PR comment utilities for posting memory analysis results."""

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, TemplateError as Jinja2TemplateError

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


def post_combined_pr_comment(
    results: list[dict],
    template_path: Optional[str] = None
) -> None:
    """
    Post a single PR comment with combined memory analysis results from multiple targets.

    Args:
        results: List of result dicts, each containing comparison_url, api_response,
            target_name, pr_number
        template_path: Optional path to custom Jinja2 template file. If None, uses
            the default template format.
    """
    if not is_gh_cli_available():
        logger.warning("GitHub CLI (gh) not available, skipping PR comment")
        return

    try:
        pr_number = _extract_pr_number(results)
    except ValueError as e:
        logger.warning("Cannot post PR comment: %s", e)
        return

    # Build comment body using template (custom or default)
    try:
        comment_body = _build_comment_body_from_template(results, template_path)
    except FileNotFoundError as e:
        logger.error("Template error: %s", e)
        raise
    except Jinja2TemplateError as e:
        logger.error("Template syntax error: %s", e)
        raise

    try:
        create_or_update_comment(comment_body, pr_number, COMMENT_MARKER)
        logger.info("Posted combined PR comment for %d targets", len(results))
    except subprocess.CalledProcessError as e:
        handle_comment_error(e, "PR comment")
    except Exception as e:  # pylint: disable=broad-exception-caught
        handle_comment_error(e, "PR comment")


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


def _build_template_context(results: list[dict]) -> dict:
    """
    Build template context from results data.

    Transforms API response data into a clean, structured format for Jinja2 templates.

    Args:
        results: List of result dicts from each target

    Returns:
        Dictionary with template variables:
        - targets: List of target data with regions, sections, alerts
        - has_alerts: True if any target has budget alerts
        - marker: Comment marker string
    """
    targets = []
    has_any_alerts = False

    for result in results:
        target_name = result.get('target_name', 'Unknown')
        comparison_url = result.get('comparison_url')
        data = result.get('api_response', {}).get('data', {})

        # Extract changes
        changes_data = data.get('changes', {})
        regions_data = changes_data.get('regions', {})
        sections_data = changes_data.get('sections', {})
        symbols_data = changes_data.get('symbols', {})

        # Extract alerts
        alerts_data = data.get('alerts', {})
        budgets = alerts_data.get('budgets', []) if alerts_data else []

        # Process alerts
        alerts = []
        for alert in iter_budget_alerts(budgets):
            alerts.append({
                'budget_name': alert.budget_name,
                'region': alert.region,
                'usage': alert.usage,
                'limit': alert.limit,
                'exceeded': alert.exceeded,
            })
            has_any_alerts = True

        # Process regions with changes
        regions = []
        for region in regions_data.get('modified', []):
            row_data = build_memory_change_row(region)
            if row_data:
                limit_size = row_data['limit_size']
                current_used = row_data['current_used']
                regions.append({
                    'name': row_data['region_name'],
                    'delta': row_data['delta'],
                    'delta_str': row_data['delta_str'],
                    'delta_pct_str': row_data['delta_pct_str'],
                    'current_used': current_used,
                    'limit_size': limit_size,
                    'utilization_pct': (current_used / limit_size * 100)
                                       if limit_size > 0 else 0,
                })

        # Process sections with changes
        sections = []
        sections_by_region_raw = _group_sections_by_region(sections_data)
        for region_name, region_sections in sections_by_region_raw.items():
            for section in region_sections:
                current_size = section.get('size', 0)
                old_size = section.get('old', {}).get('size')  # None if no baseline
                if old_size is not None and old_size != current_size:
                    delta = current_size - old_size
                    sections.append({
                        'name': section.get('name', 'unknown'),
                        'region': region_name,
                        'size': current_size,
                        'old_size': old_size,
                        'delta': delta,
                        'delta_str': f"+{delta:,}" if delta >= 0 else f"{delta:,}",
                    })

        # Group sections by region for easier template access
        sections_by_region = {}
        for section in sections:
            region_name = section['region']
            if region_name not in sections_by_region:
                sections_by_region[region_name] = []
            sections_by_region[region_name].append(section)

        # Process symbols (pass through raw lists, empty if not present)
        symbols = {
            'added': symbols_data.get('added', []),
            'removed': symbols_data.get('removed', []),
            'modified': symbols_data.get('modified', []),
            'moved': symbols_data.get('moved', []),
        } if symbols_data else {'added': [], 'removed': [], 'modified': [], 'moved': []}

        targets.append({
            'name': target_name,
            'comparison_url': comparison_url,
            'regions': regions,
            'sections': sections,
            'sections_by_region': sections_by_region,
            'symbols': symbols,
            'alerts': alerts,
            'has_changes': bool(regions),
            'has_alerts': bool(alerts),
        })

    return {
        'targets': targets,
        'has_alerts': has_any_alerts,
    }


def _get_default_template_path() -> Path:
    """Get the path to the default template file."""
    return Path(__file__).parent / 'templates' / 'default_comment.j2'


def _render_template(template_path: str, context: dict) -> str:
    """
    Render a Jinja2 template with the provided context.

    Args:
        template_path: Path to the Jinja2 template file
        context: Dictionary with template variables

    Returns:
        Rendered template as string with comment marker and header prepended

    Raises:
        FileNotFoundError: If template file doesn't exist
        Jinja2TemplateError: If template has syntax errors
    """
    template_file = Path(template_path)
    if not template_file.exists():
        raise FileNotFoundError(f"Template file not found: {template_path}")

    # Create Jinja2 environment
    env = Environment(
        loader=FileSystemLoader(template_file.parent),
        autoescape=False,  # Markdown doesn't need HTML escaping
        trim_blocks=True,
        lstrip_blocks=True,
    )

    template = env.get_template(template_file.name)
    rendered = template.render(**context)

    # Fixed header - always included for brand consistency
    logo = '<img src="https://membrowse.com/membrowse-logo.svg" height="24" align="top">'
    header = f"{COMMENT_MARKER}\n## {logo} MemBrowse Memory Report\n"

    return f"{header}\n{rendered}"


def _build_comment_body_from_template(
    results: list[dict],
    template_path: Optional[str] = None
) -> str:
    """
    Build comment body using Jinja2 template.

    Args:
        results: List of result dicts from each target
        template_path: Path to custom template file, or None for default

    Returns:
        str: Markdown-formatted comment body
    """
    context = _build_template_context(results)

    if template_path:
        logger.info("Rendering comment using custom template: %s", template_path)
        return _render_template(template_path, context)

    # Use default template
    default_template = _get_default_template_path()
    return _render_template(str(default_template), context)


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
    parser.add_argument(
        '--comment-template',
        dest='template_path',
        help='Path to custom Jinja2 template file for comment formatting'
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

    # Post combined PR comment with optional custom template
    try:
        post_combined_pr_comment(results, template_path=args.template_path)
    except (FileNotFoundError, Jinja2TemplateError) as e:
        logger.error("Failed to generate comment: %s", e)
        sys.exit(1)


if __name__ == '__main__':
    configure_logging()
    main()
