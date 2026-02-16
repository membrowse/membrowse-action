"""GitHub PR comment utilities for posting memory analysis results."""

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

from jinja2 import TemplateError as Jinja2TemplateError

from .summary_formatter import (
    enrich_regions, enrich_sections, process_alerts, render_jinja2_template,
)
from .github_common import (
    is_gh_cli_available,
    create_or_update_comment,
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
        context = _build_template_context(results)
        comment_body = _render_comment_body(context, template_path)
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


def post_pr_comment_from_body(body: str, pr_number: str) -> None:
    """
    Post a pre-rendered body as a PR comment, wrapped with the MemBrowse header.

    Used by the comment-action when piping output from 'membrowse summary'.

    Args:
        body: Pre-rendered markdown body (e.g., from membrowse summary)
        pr_number: PR number to post the comment on
    """
    if not is_gh_cli_available():
        logger.warning("GitHub CLI (gh) not available, skipping PR comment")
        return

    logo = '<img src="https://membrowse.com/membrowse-logo.svg" height="24" align="top">'
    header = f"{COMMENT_MARKER}\n## {logo} MemBrowse Memory Report\n"
    comment_body = f"{header}\n{body}"

    try:
        create_or_update_comment(comment_body, pr_number, COMMENT_MARKER)
        logger.info("Posted PR comment")
    except subprocess.CalledProcessError as e:
        handle_comment_error(e, "PR comment")
    except Exception as e:  # pylint: disable=broad-exception-caught
        handle_comment_error(e, "PR comment")


def _build_template_context(results: list[dict]) -> dict:
    """
    Build template context from results data.

    Passes API response data through directly, only adding computed fields
    (delta, delta_str, delta_pct_str, utilization_pct) that don't exist in the raw data.

    Args:
        results: List of result dicts from each target

    Returns:
        Dictionary with template variables:
        - targets: List of target data with regions, sections, alerts
        - has_alerts: True if any target has budget alerts
    """
    targets = []
    has_any_alerts = False

    for result in results:
        data = result.get('api_response', {}).get('data', {})
        changes_data = data.get('changes', {})
        symbols_data = changes_data.get('symbols', {})

        alerts = process_alerts(data.get('alerts', {}))
        if alerts:
            has_any_alerts = True

        regions = enrich_regions(changes_data.get('regions', {}))
        sections, sections_by_region = enrich_sections(changes_data.get('sections', {}))

        symbols = {
            'added': symbols_data.get('added', []),
            'removed': symbols_data.get('removed', []),
            'modified': symbols_data.get('modified', []),
            'moved': symbols_data.get('moved', []),
        } if symbols_data else {'added': [], 'removed': [], 'modified': [], 'moved': []}

        targets.append({
            'name': result.get('target_name', 'Unknown'),
            'comparison_url': result.get('comparison_url'),
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
    Render a Jinja2 template with comment marker and header prepended.

    Raises:
        FileNotFoundError: If template file doesn't exist
        Jinja2TemplateError: If template has syntax errors
    """
    rendered = render_jinja2_template(template_path, context)

    logo = '<img src="https://membrowse.com/membrowse-logo.svg" height="24" align="top">'
    header = f"{COMMENT_MARKER}\n## {logo} MemBrowse Memory Report\n"

    return f"{header}\n{rendered}"


def _render_comment_body(
    context: dict,
    template_path: Optional[str] = None
) -> str:
    """
    Render comment body from a template context.

    Args:
        context: Template context dict with 'targets' and 'has_alerts'
        template_path: Path to custom template file, or None for default

    Returns:
        str: Markdown-formatted comment body
    """
    if template_path:
        logger.info("Rendering comment using custom template: %s", template_path)
        return _render_template(template_path, context)

    # Use default template
    default_template = _get_default_template_path()
    return _render_template(str(default_template), context)


def main():
    """
    Main entry point for combined GitHub comment posting.

    Supports two modes:
    - File mode: reads JSON result files from --output-raw-response
    - Body mode: posts pre-rendered content (e.g., from 'membrowse summary')
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
        '--body',
        dest='body_file',
        help='File with pre-rendered comment body (e.g., from membrowse summary)'
    )
    parser.add_argument(
        '--pr-number',
        dest='pr_number',
        help='PR number to post comment on (required with --body)'
    )
    parser.add_argument(
        '--comment-template',
        dest='template_path',
        help='Path to custom Jinja2 template file for comment formatting'
    )
    args = parser.parse_args()

    # Body mode: post pre-rendered content
    if args.body_file:
        if not args.pr_number:
            parser.error("--pr-number is required with --body")
        try:
            body = Path(args.body_file).read_text(encoding='utf-8')
        except IOError as e:
            logger.error("Failed to read body file: %s", e)
            sys.exit(1)
        post_pr_comment_from_body(body, args.pr_number)
        return

    # File mode
    result_files = []
    if args.files:
        result_files = [Path(f) for f in args.files]
    elif args.directory:
        result_files = list(Path(args.directory).glob('*.json'))
    else:
        parser.error("Either provide JSON files, use --dir, or use --body")

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
