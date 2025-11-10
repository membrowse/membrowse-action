"""GitHub PR comment utilities for posting memory analysis results."""

import argparse
import os
import subprocess
import logging

logger = logging.getLogger(__name__)

# Unique marker to identify MemBrowse comments
COMMENT_MARKER = "<!-- membrowse-pr-comment -->"


def post_or_update_pr_comment(comparison_url: str = None) -> None:
    """
    Post or update a PR comment with memory analysis results.

    This function will:
    - Find an existing MemBrowse comment and update it (if found)
    - Create a new comment if no existing comment is found
    - Handle cases where no comparison URL is available

    Args:
        comparison_url: URL to build comparison page (can be None)
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
    comment_body = _build_comment_body(comparison_url)

    # Try to find and update existing comment, or create new one
    try:
        existing_comment_id = _find_existing_comment()
        if existing_comment_id:
            _update_comment(existing_comment_id, comment_body)
            logger.info("Updated existing PR comment")
        else:
            _create_comment(comment_body)
            logger.info("Created new PR comment")
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


def _build_comment_body(comparison_url: str = None) -> str:
    """
    Build the PR comment body with memory analysis results.

    Args:
        comparison_url: URL to build comparison page (can be None)

    Returns:
        str: Markdown-formatted comment body
    """
    # Start with header and marker
    body_parts = [
        COMMENT_MARKER,
        "## MemBrowse Memory Analysis",
        ""
    ]

    if comparison_url:
        body_parts.extend([
            f"[View Build Comparison]({comparison_url})",
            "",
            "Memory footprint analysis has been uploaded to MemBrowse."
        ])
    else:
        body_parts.extend([
            "Memory footprint analysis completed.",
            "",
            "*Build comparison not available (this may be the first build for this project)*"
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


def _create_comment(body: str) -> None:
    """
    Create a new PR comment.

    Args:
        body: Comment body
    """
    subprocess.run(
        ['gh', 'pr', 'comment', '--body', body],
        check=True,
        capture_output=True,
        timeout=30
    )


def main():
    """
    Main entry point for GitHub comment posting.

    Reads comparison URL from file specified by --url-file argument.
    """
    parser = argparse.ArgumentParser(description='Post MemBrowse PR comment')
    parser.add_argument(
        '--url-file',
        required=True,
        help='File containing comparison URL'
    )
    args = parser.parse_args()

    # Read comparison URL from file
    comparison_url = None
    try:
        with open(args.url_file, 'r', encoding='utf-8') as f:
            url_content = f.read().strip()
            comparison_url = url_content if url_content else None
    except FileNotFoundError:
        logger.warning("URL file not found: %s", args.url_file)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("Failed to read URL file: %s", e)

    # Post or update PR comment
    post_or_update_pr_comment(comparison_url)


if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )
    main()
