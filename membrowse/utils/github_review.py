"""Request changes on a pull request when memory crosses a limit.

The comment-action's ``request_changes`` option submits a PR review with the
"Request changes" verdict instead of failing CI: the PR stays mergeable (as
far as the repository's branch protection allows), and a maintainer who
accepts the increase dismisses the review, which leaves the decision and its
reason in the PR's timeline.

One MemBrowse review is kept per PR, found by a marker in its body:

- still over a limit and a review is active: its text is updated;
- over a limit and no review is active: a new one is submitted, unless a
  maintainer already dismissed a review that named the same regions (they
  accepted the increase, so later pushes do not ask again);
- back within the limits: the active review is dismissed by the action.

The review body also records which target/region pairs it named, so the
action can tell a maintainer's dismissal (keys kept) from its own (keys
cleared before dismissing).
"""

import json
import logging
import re
import subprocess
from typing import NamedTuple, Optional

from .github_common import GH_COMMENT_TIMEOUT, GH_LIST_COMMENTS_TIMEOUT, get_pr_number

logger = logging.getLogger(__name__)

REVIEW_MARKER = "<!-- membrowse-pr-review -->"
_KEYS_RE = re.compile(r'<!-- membrowse-review-keys: (.*?) -->')
_SHA_RE = re.compile(r'[0-9a-fA-F]{7,40}')

RESOLVED_MESSAGE = "Memory is back within the configured limits."

_PERMISSION_HINT = (
    "Requesting changes needs 'permissions: pull-requests: write' on the job. "
    "Pull requests from forks get a read-only token in 'pull_request' "
    "workflows; post the comment from a 'workflow_run' workflow instead."
)


class ReviewReason(NamedTuple):
    """One reason to request changes: ``key`` names the target and region
    (to recognise a dismissed review), ``text`` is the line shown to people."""
    key: str
    text: str


class _Review(NamedTuple):
    review_id: int
    state: str
    body: str


def _gh(args: list[str], timeout: int = GH_COMMENT_TIMEOUT) -> str:
    result = subprocess.run(
        ['gh', 'api', *args], check=True, capture_output=True, timeout=timeout,
    )
    return result.stdout.decode('utf-8')


def _review_keys(body: str) -> set[str]:
    match = _KEYS_RE.search(body or '')
    if not match:
        return set()
    try:
        return set(json.loads(match.group(1)))
    except (json.JSONDecodeError, TypeError):
        return set()


def _keys_marker(keys) -> str:
    # '>' is escaped so a target or region name cannot end the HTML comment.
    encoded = json.dumps(sorted(keys)).replace('>', '\\u003e')
    return f"<!-- membrowse-review-keys: {encoded} -->"


def _list_reviews(pr_number: str) -> list[_Review]:
    """The MemBrowse reviews on a PR (submitted by a bot, with the marker)."""
    output = _gh(
        ['--paginate', f'repos/{{owner}}/{{repo}}/pulls/{pr_number}/reviews?per_page=100',
         '--jq', '.[] | {id, state, body, type: .user.type}'],
        timeout=GH_LIST_COMMENTS_TIMEOUT,
    )
    reviews = []
    for line in output.splitlines():
        try:
            review = json.loads(line)
        except json.JSONDecodeError:
            continue
        if review.get('type') == 'Bot' and REVIEW_MARKER in (review.get('body') or ''):
            reviews.append(_Review(review['id'], review.get('state', ''), review['body']))
    return reviews


def _pr_head_sha(pr_number: str) -> str:
    return _gh([f'repos/{{owner}}/{{repo}}/pulls/{pr_number}', '--jq', '.head.sha']).strip()


def build_review_body(reasons: list[ReviewReason], dashboard_url: Optional[str] = None) -> str:
    """The text of a MemBrowse change request."""
    lines = [
        REVIEW_MARKER,
        _keys_marker({reason.key for reason in reasons}),
        "**MemBrowse:** this pull request takes memory past the limits set for this "
        "repository:",
        "",
        *(f"- {reason.text}" for reason in reasons),
        "",
    ]
    details = "See the MemBrowse memory report comment"
    if dashboard_url:
        details += f" or [explore what changed]({dashboard_url})"
    lines.append(
        f"{details}. If the increase is intended, a maintainer can dismiss this review; "
        "MemBrowse will not ask again for the same regions."
    )
    return '\n'.join(lines) + '\n'


def _resolved_body(body: str) -> str:
    """A review body with its keys cleared, so that the action's own dismissal
    is not mistaken for a maintainer accepting the increase."""
    return _KEYS_RE.sub(_keys_marker(()), body) + f"\n**Resolved:** {RESOLVED_MESSAGE}\n"


def sync_review(
    pr_number: str,
    reasons: list[ReviewReason],
    commit_sha: Optional[str] = None,
    dashboard_url: Optional[str] = None,
) -> None:
    """
    Request changes on a PR while ``reasons`` is non-empty, and dismiss the
    request once it is empty. See the module docstring for the rules.

    Args:
        pr_number: The PR number
        reasons: Why the PR crosses a limit; empty when it does not
        commit_sha: The commit the reasons were computed for. When given and
            the PR has moved on to a newer head, nothing is done, so that a
            late run cannot undo the verdict on a newer commit.
        dashboard_url: Link to the change on MemBrowse, for the review text

    Raises:
        subprocess.CalledProcessError: If a gh command fails
        ValueError: If the PR number is invalid
    """
    pr_num = get_pr_number(pr_number)

    if commit_sha and not _SHA_RE.fullmatch(commit_sha):
        commit_sha = None  # a branch name or similar: nothing to compare
    if commit_sha:
        head = _pr_head_sha(pr_num)
        if head and not head.lower().startswith(commit_sha.lower()):
            logger.info("PR #%s has moved on from %s to %s; leaving its review alone",
                        pr_num, commit_sha[:12], head[:12])
            return
        commit_sha = head or None  # the full SHA, for the review's commit_id

    reviews = _list_reviews(pr_num)
    active = [review for review in reviews if review.state == 'CHANGES_REQUESTED']
    base = f'repos/{{owner}}/{{repo}}/pulls/{pr_num}/reviews'

    if not reasons:
        for review in active:
            logger.info("Memory is within limits; dismissing MemBrowse review %d", review.review_id)
            _gh(['--method', 'PUT', f'{base}/{review.review_id}',
                 '-f', f'body={_resolved_body(review.body)}'])
            _gh(['--method', 'PUT', f'{base}/{review.review_id}/dismissals',
                 '-f', f'message={RESOLVED_MESSAGE}', '-f', 'event=DISMISS'])
        return

    body = build_review_body(reasons, dashboard_url)
    if active:
        logger.info("Updating MemBrowse change request %d", active[-1].review_id)
        _gh(['--method', 'PUT', f'{base}/{active[-1].review_id}', '-f', f'body={body}'])
        return

    dismissed = set().union(*(_review_keys(review.body) for review in reviews
                               if review.state == 'DISMISSED'))
    keys = {reason.key for reason in reasons}
    if keys <= dismissed:
        logger.info("A maintainer already dismissed the MemBrowse change request for %s; "
                    "not requesting changes again", ', '.join(sorted(keys)))
        return

    logger.info("Requesting changes on PR #%s: %s", pr_num, ', '.join(sorted(keys)))
    args = ['--method', 'POST', base, '-f', 'event=REQUEST_CHANGES', '-f', f'body={body}']
    if commit_sha:
        args += ['-f', f'commit_id={commit_sha}']
    _gh(args)


def handle_review_error(error: Exception) -> None:
    """Log a failed review call as a warning; the comment is unaffected."""
    message = f"Failed to update the MemBrowse PR review: {error}"
    stderr = getattr(error, 'stderr', None)
    if stderr:
        stderr = stderr.decode('utf-8') if isinstance(stderr, bytes) else stderr
        message += f"\ngh stderr: {stderr.strip()}"
        if 'not accessible' in stderr or '403' in stderr:
            message += f"\n{_PERMISSION_HINT}"
    logger.warning(message)
