"""Summary subcommand — retrieve memory footprint summaries from MemBrowse API."""

import json
import argparse
import logging
from pathlib import Path
from typing import Dict, Any

from jinja2 import TemplateError as Jinja2TemplateError

from ..api.client import MemBrowseClient
from ..auth.strategy import AuthContext, AuthType
from ..utils.summary_formatter import build_summary_template_context, render_jinja2_template

logger = logging.getLogger(__name__)

DEFAULT_API_URL = 'https://api.membrowse.com'
DEFAULT_TEMPLATE = Path(__file__).parent.parent / 'utils' / 'templates' / 'default_comment.j2'


def add_summary_parser(subparsers) -> argparse.ArgumentParser:
    """Add 'summary' subcommand parser."""
    parser = subparsers.add_parser(
        'summary',
        help='Retrieve memory footprint summary for a commit',
        description=(
            'Retrieve and display a memory footprint summary from the MemBrowse API.\n\n'
            'Shows memory region changes, section changes, and layout\n'
            'for all targets associated with the specified commit.'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        'commit_sha',
        help='Git commit SHA to retrieve summary for',
    )
    parser.add_argument(
        '--api-key',
        required=True,
        help='MemBrowse API key for authentication',
    )
    parser.add_argument(
        '--api-url',
        default=DEFAULT_API_URL,
        help=f'MemBrowse API base URL (default: {DEFAULT_API_URL})',
    )

    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        '--json',
        action='store_true',
        help='Output raw JSON response from API',
    )
    output_group.add_argument(
        '--template',
        type=str,
        metavar='PATH',
        help='Path to custom Jinja2 template (default: built-in template)',
    )

    return parser


def _fetch_summary(
    commit_sha: str,
    api_key: str,
    api_url: str,
) -> Dict[str, Any]:
    """
    Fetch summary from MemBrowse API.

    Returns:
        Summary response dictionary

    Raises:
        RuntimeError: If API request fails or returns an error
    """
    auth_context = AuthContext(
        auth_type=AuthType.API_KEY,
        api_key=api_key,
    )
    client = MemBrowseClient(auth_context, api_url)
    response = client.get_summary(commit_sha)

    if not response.get('success'):
        error_msg = response.get('error', 'Unknown error')
        raise RuntimeError(f"API request failed: {error_msg}")

    return response


def run_summary(args) -> int:
    """
    Run summary subcommand.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        response = _fetch_summary(
            commit_sha=args.commit_sha,
            api_key=args.api_key,
            api_url=args.api_url,
        )

        if args.json:
            print(json.dumps(response, indent=2))
        else:
            context = build_summary_template_context(response)
            template_path = args.template or str(DEFAULT_TEMPLATE)
            output = render_jinja2_template(template_path, context)
            print(output)

        return 0

    except (FileNotFoundError, Jinja2TemplateError) as e:
        logger.error("Template error: %s", e)
        return 1
    except RuntimeError as e:
        logger.error("%s", e)
        return 1
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Summary command failed: %s", e)
        return 1
