"""GitHub PR comment utilities for posting memory analysis results."""

import argparse
import json
import logging
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple, Optional, Union

from jinja2 import TemplateError as Jinja2TemplateError

from .summary_formatter import (
    build_summary_template_context,
    enrich_files,
    summarize_file_changes,
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

MEMBROWSE_URL = "https://membrowse.com"
_LOGO = f'<img src="{MEMBROWSE_URL}/membrowse-logo.svg" height="24" align="top">'


def _wrap_comment_body(
    body: str,
    dashboard_url: Optional[str] = None,
    footer: bool = True,
) -> str:
    """
    Wrap a rendered body with the MemBrowse marker, header and footer.

    The header includes an "Explore what changed" link when a project URL is
    available. The footer links to membrowse.com and can be disabled.
    """
    title = "MemBrowse Memory Report"
    if dashboard_url:
        title += f" &middot; [Explore what changed →]({dashboard_url})"
    header = f"{COMMENT_MARKER}\n## {_LOGO} {title}\n"
    if not footer:
        return f"{header}\n{body.rstrip()}\n"
    footer_text = (
        f"\n---\n<sub>Catch memory regressions in CI with [MemBrowse]({MEMBROWSE_URL}). "
        "Free for open source.</sub>\n"
    )
    return f"{header}\n{body.rstrip()}\n{footer_text}"


class ChangeThreshold(NamedTuple):
    """The smallest region change that makes a new PR comment worth posting:
    ``value`` bytes, or ``value`` percent of the region's previous usage."""
    value: float
    percent: bool = False

    def __str__(self) -> str:
        return f"{self.value:g}%" if self.percent else f"{self.value:g} bytes"


# Any change at all: what skip_unchanged has always meant.
ANY_CHANGE = ChangeThreshold(1)

_UNITS = {'': 1, 'b': 1, 'k': 1024, 'kb': 1024, 'kib': 1024,
          'm': 1024 ** 2, 'mb': 1024 ** 2, 'mib': 1024 ** 2}
_THRESHOLD_RE = re.compile(r'^\s*(\d+(?:\.\d+)?)\s*(%|[a-z]*)\s*$', re.IGNORECASE)


def parse_min_change(text: str) -> ChangeThreshold:
    """
    Parse a --min-change value: bytes ("512", "512B", "2KB", "1.5MB"; KB and
    MB are 1024-based) or a percentage of a region's previous usage ("0.5%").

    Raises:
        ValueError: If the value is not a non-negative number with a known unit.
    """
    match = _THRESHOLD_RE.match(text or '')
    unit = match.group(2).lower() if match else None
    if unit is None or (unit != '%' and unit not in _UNITS):
        raise ValueError(
            f"Invalid minimum change {text!r}: expected bytes (e.g. 512, 2KB, 1MB) "
            "or a percentage (e.g. 0.5%)"
        )
    value = float(match.group(1))
    if unit == '%':
        return ChangeThreshold(value, percent=True)
    return ChangeThreshold(value * _UNITS[unit])


def _resolve_threshold(
    skip_unchanged: bool,
    min_change: Union[ChangeThreshold, str, None],
) -> Optional[ChangeThreshold]:
    """The threshold a new comment must reach, or None to always comment.
    min_change wins over skip_unchanged, which means any change at all."""
    if isinstance(min_change, str):
        min_change = parse_min_change(min_change) if min_change.strip() else None
    if min_change is not None:
        return min_change
    return ANY_CHANGE if skip_unchanged else None


def _region_reaches(region: dict, threshold: ChangeThreshold) -> bool:
    """True if one changed region (from enrich_regions) moved by at least threshold."""
    delta = abs(region.get('delta', 0))
    if not threshold.percent:
        return delta >= threshold.value
    old_used = (region.get('old') or {}).get('used_size') or 0
    if old_used <= 0:
        # Growing from nothing is an infinite relative change.
        return delta > 0
    percent = delta / old_used * 100
    # Inclusive even when float rounding lands just below the threshold:
    # 55 / 10000 * 100 is 0.5499999999999999, which must still reach 0.55%.
    return percent >= threshold.value or math.isclose(percent, threshold.value, rel_tol=1e-9)


def _has_memory_changes(context: dict, threshold: ChangeThreshold = ANY_CHANGE) -> bool:
    """True if any target in a template context has budget alerts, or changed
    a region by at least threshold (by default, changed a region at all)."""
    return any(
        target.get('has_alerts')
        or (threshold == ANY_CHANGE and target.get('has_changes'))
        or any(_region_reaches(region, threshold) for region in target.get('regions', []))
        for target in context.get('targets', [])
    )


def _should_create(context: dict, threshold: Optional[ChangeThreshold]) -> bool:
    """Whether a new comment may be created (an existing one is always updated)."""
    if threshold is None or _has_memory_changes(context, threshold):
        return True
    logger.info("No region changed by at least %s and no budget alerts; "
                "not creating a PR comment", threshold)
    return False


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
    template_path: Optional[str] = None,
    footer: bool = True,
    skip_unchanged: bool = False,
    min_change: Union[ChangeThreshold, str, None] = None,
) -> None:
    """
    Post a single PR comment with combined memory analysis results from multiple targets.

    Args:
        results: List of result dicts, each containing comparison_url, api_response,
            target_name, pr_number
        template_path: Optional path to custom Jinja2 template file. If None, uses
            the default template format.
        footer: Whether to append the MemBrowse footer.
        skip_unchanged: Do not create a comment when no target has memory changes
            or budget alerts; an existing comment is still updated.
        min_change: Do not create a comment unless some region changed by at
            least this much (ChangeThreshold or a parse_min_change string) or a
            budget alert fired; implies skip_unchanged.
    """
    threshold = _resolve_threshold(skip_unchanged, min_change)
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
        comment_body = _render_comment_body(context, template_path, footer)
    except FileNotFoundError as e:
        logger.error("Template error: %s", e)
        raise
    except Jinja2TemplateError as e:
        logger.error("Template syntax error: %s", e)
        raise

    try:
        create_or_update_comment(
            comment_body, pr_number, COMMENT_MARKER,
            create_if_missing=_should_create(context, threshold),
        )
        logger.debug("Posted combined PR comment for %d targets", len(results))
    except subprocess.CalledProcessError as e:
        handle_comment_error(e, "PR comment")
    except Exception as e:  # pylint: disable=broad-exception-caught
        handle_comment_error(e, "PR comment")


def post_pr_comment_from_body(body: str, pr_number: str, footer: bool = True) -> None:
    """
    Post a pre-rendered body as a PR comment, wrapped with the MemBrowse header.

    Used by the comment-action when piping output from 'membrowse summary'.

    Args:
        body: Pre-rendered markdown body (e.g., from membrowse summary)
        pr_number: PR number to post the comment on
        footer: Whether to append the MemBrowse footer
    """
    if not is_gh_cli_available():
        logger.warning("GitHub CLI (gh) not available, skipping PR comment")
        return

    comment_body = _wrap_comment_body(body, footer=footer)

    try:
        create_or_update_comment(comment_body, pr_number, COMMENT_MARKER)
        logger.debug("Posted PR comment")
    except subprocess.CalledProcessError as e:
        handle_comment_error(e, "PR comment")
    except Exception as e:  # pylint: disable=broad-exception-caught
        handle_comment_error(e, "PR comment")


def _build_template_context(results: list[dict]) -> dict:  # pylint: disable=too-many-locals
    """
    Build template context from results data.

    Passes API response data through directly, only adding computed fields
    (delta, delta_str, delta_pct_str, utilization_pct) that don't exist in the raw data.

    Args:
        results: List of result dicts from each target

    Returns:
        Dictionary with template variables:
        - targets: List of target data with regions, sections, symbols, alerts
          and files (enrich_files), each with has_changes, has_alerts and
          has_file_changes
        - has_alerts: True if any target has budget alerts
        - file_changes: One row per changed source file across targets
          (summarize_file_changes)
        - targets_with_file_changes: How many targets carry per-file changes
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
        files = enrich_files(changes_data.get('files'), data.get('memory_layout', {}))

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
            'files': files,
            'alerts': alerts,
            'has_changes': bool(regions),
            'has_alerts': bool(alerts),
            'has_file_changes': bool(files),
        })

    return {
        'targets': targets,
        'has_alerts': has_any_alerts,
        'file_changes': summarize_file_changes(targets),
        'targets_with_file_changes': sum(1 for target in targets if target['has_file_changes']),
    }


def _get_default_template_path() -> Path:
    """Get the path to the default template file."""
    return Path(__file__).parent / 'templates' / 'default_comment.j2'


def _render_template(template_path: str, context: dict, footer: bool = True) -> str:
    """
    Render a Jinja2 template with comment marker and header prepended.

    Raises:
        FileNotFoundError: If template file doesn't exist
        Jinja2TemplateError: If template has syntax errors
    """
    rendered = render_jinja2_template(template_path, context)
    return _wrap_comment_body(rendered, context.get('dashboard_url'), footer)


def _render_comment_body(
    context: dict,
    template_path: Optional[str] = None,
    footer: bool = True,
) -> str:
    """
    Render comment body from a template context.

    Args:
        context: Template context dict with 'targets' and 'has_alerts'
        template_path: Path to custom template file, or None for default
        footer: Whether to append the MemBrowse footer

    Returns:
        str: Markdown-formatted comment body
    """
    if template_path:
        logger.debug("Rendering comment using custom template: %s", template_path)
        return _render_template(template_path, context, footer)

    # Use default template
    default_template = _get_default_template_path()
    return _render_template(str(default_template), context, footer)


def post_summary_comment(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    summary_json_path: str,
    pr_number: Optional[str] = None,
    template_path: Optional[str] = None,
    footer: bool = True,
    skip_unchanged: bool = False,
    min_change: Union[ChangeThreshold, str, None] = None,
) -> None:
    """
    Post a PR comment from a saved /summary API response JSON file.

    Extracts pr_number from the response if not provided, renders the
    template, and posts the comment. Single entry point for the
    comment-action's API mode.

    Args:
        summary_json_path: Path to the saved /summary JSON response
        pr_number: PR number override (auto-extracted from JSON if None)
        template_path: Custom Jinja2 template path, or None for default
        footer: Whether to append the MemBrowse footer
        skip_unchanged: Do not create a comment when no target has memory
            changes or budget alerts; an existing comment is still updated
        min_change: Do not create a comment unless some region changed by at
            least this much (ChangeThreshold or a parse_min_change string) or a
            budget alert fired; implies skip_unchanged
    """
    threshold = _resolve_threshold(skip_unchanged, min_change)
    with open(summary_json_path, 'r', encoding='utf-8') as f:
        response = json.load(f)

    if not isinstance(response.get('data'), dict):
        data_type = type(response.get('data'))
        raise ValueError(
            f"Invalid summary JSON: expected 'data' object, got {data_type}"
        )

    # Extract PR number from API response if not provided
    if not pr_number:
        pr_number = response.get('data', {}).get('pr_number')
        if pr_number:
            pr_number = str(pr_number)
            logger.debug("Resolved PR number %s from API response", pr_number)

    if not pr_number:
        logger.warning("Could not resolve PR number — skipping comment")
        print("::warning::Could not resolve PR number — skipping comment")
        return

    # Render template from the same response
    context = build_summary_template_context(response)
    body = _render_comment_body(context, template_path, footer)

    # body already includes the header/marker from _render_comment_body,
    # so post directly instead of going through post_pr_comment_from_body
    # which would add the header a second time.
    if not is_gh_cli_available():
        logger.warning("GitHub CLI (gh) not available, skipping PR comment")
        return

    try:
        create_or_update_comment(
            body, pr_number, COMMENT_MARKER,
            create_if_missing=_should_create(context, threshold),
        )
        logger.debug("Posted summary PR comment")
    except subprocess.CalledProcessError as e:
        handle_comment_error(e, "PR comment")
    except Exception as e:  # pylint: disable=broad-exception-caught
        handle_comment_error(e, "PR comment")


def _min_change_arg(text: str) -> Optional[ChangeThreshold]:
    """argparse type for --min-change; an empty value means no threshold."""
    if not text.strip():
        return None
    try:
        return parse_min_change(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def main():
    """
    Main entry point for combined GitHub comment posting.

    Supports three modes:
    - Summary mode: reads /summary API JSON, extracts PR number, renders and posts
    - Body mode: posts pre-rendered content (e.g., from 'membrowse summary')
    - File mode: reads JSON result files from --output-raw-response
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
        '--summary-json',
        dest='summary_json',
        help='Path to saved /summary API response JSON file'
    )
    parser.add_argument(
        '--body',
        dest='body_file',
        help='File with pre-rendered comment body (e.g., from membrowse summary)'
    )
    parser.add_argument(
        '--pr-number',
        dest='pr_number',
        help='PR number to post comment on (auto-detected from summary JSON)'
    )
    parser.add_argument(
        '--comment-template',
        dest='template_path',
        help='Path to custom Jinja2 template file for comment formatting'
    )
    parser.add_argument(
        '--no-footer',
        dest='footer',
        action='store_false',
        help='Omit the MemBrowse footer from the comment'
    )
    parser.add_argument(
        '--skip-unchanged',
        dest='skip_unchanged',
        action='store_true',
        help='Do not create a comment when no target has memory changes or budget '
             'alerts; an existing MemBrowse comment is still updated'
    )
    parser.add_argument(
        '--min-change',
        dest='min_change',
        type=_min_change_arg,
        help='Do not create a comment unless some region of some target changed by '
             'at least this much: bytes (512, 2KB, 1MB) or percent of the region\'s '
             'previous usage (0.5%%). Budget alerts always create a comment; an '
             'existing MemBrowse comment is still updated. Implies --skip-unchanged'
    )
    args = parser.parse_args()

    # Summary JSON mode: extract PR number, render, and post in one step
    if args.summary_json:
        try:
            post_summary_comment(
                args.summary_json,
                pr_number=args.pr_number,
                template_path=args.template_path,
                footer=args.footer,
                skip_unchanged=args.skip_unchanged,
                min_change=args.min_change,
            )
        except (json.JSONDecodeError, IOError, ValueError) as e:
            logger.error("Failed to post summary comment: %s", e)
            sys.exit(1)
        return

    # Body mode: post pre-rendered content
    if args.body_file:
        if not args.pr_number:
            parser.error("--pr-number is required with --body")
        try:
            body = Path(args.body_file).read_text(encoding='utf-8')
        except IOError as e:
            logger.error("Failed to read body file: %s", e)
            sys.exit(1)
        post_pr_comment_from_body(body, args.pr_number, footer=args.footer)
        return

    # File mode
    _handle_file_mode(parser, args)


def _handle_file_mode(parser, args):
    """Handle file mode: load JSON result files and post combined comment."""
    result_files = []
    if args.files:
        result_files = [Path(f) for f in args.files]
    elif args.directory:
        result_files = list(Path(args.directory).glob('*.json'))
    else:
        parser.error(
            "Either provide JSON files, use --dir, --summary-json, or use --body"
        )

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
                logger.debug("Loaded result from %s", filepath)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Failed to load %s: %s", filepath, e)

    if not results:
        logger.error("No valid results loaded")
        sys.exit(1)

    # Sort results by target name for consistent ordering
    results.sort(key=lambda r: r.get('target_name', ''))

    # Post combined PR comment with optional custom template
    try:
        post_combined_pr_comment(
            results, template_path=args.template_path, footer=args.footer,
            skip_unchanged=args.skip_unchanged, min_change=args.min_change,
        )
    except (FileNotFoundError, Jinja2TemplateError) as e:
        logger.error("Failed to generate comment: %s", e)
        sys.exit(1)


if __name__ == '__main__':
    configure_logging()
    main()
