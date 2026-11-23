"""Tests for the comment-action's --request-changes option (PR reviews)."""

import json
import subprocess
import sys
from unittest import mock

import pytest

from membrowse.utils import github_comment, github_common, github_review
from membrowse.utils.github_comment import ChangeThreshold, post_summary_comment, review_reasons
from membrowse.utils.github_review import REVIEW_MARKER, ReviewReason, build_review_body

HEAD = 'a' * 40


def _summary(modified_regions=None, alerts=None) -> dict:
    """A /summary API response with one target."""
    return {
        'data': {
            'pr_number': 42,
            'dashboard_url': 'https://membrowse.com/p/x',
            'targets': [{
                'target_name': 'stm32',
                'changes_summary': {
                    'changes': {'regions': {'modified': modified_regions or []}},
                },
                'alerts': alerts or {},
            }],
        }
    }


def _region(name, old, new):
    return {'name': name, 'used_size': new, 'limit_size': 1 << 20, 'old': {'used_size': old}}


GREW = _summary([_region('FLASH', 10_000, 12_048)])      # +2,048
SHRANK = _summary([_region('FLASH', 12_048, 10_000)])    # -2,048
SMALL = _summary([_region('FLASH', 10_000, 10_100)])     # +100
WITHIN = _summary()
OVER_BUDGET = _summary(alerts={'budgets': [{
    'budget_name': 'ram', 'exceeded_regions': ['RAM'],
    'current_usage': {'RAM': 5_000}, 'limits': {'RAM': 4_096},
    'exceeded_by': {'RAM': 904},
}]})


class FakeGh:
    """Stands in for the gh CLI: PR comments, the PR head and its reviews."""

    def __init__(self, reviews=None, head=HEAD, fail_reviews=False):
        self.reviews = reviews or []
        self.head = head
        self.fail_reviews = fail_reviews
        self.calls = []

    def __call__(self, cmd, **_kwargs):
        self.calls.append(cmd)
        path = next((arg for arg in cmd if arg.startswith('repos/')), '')
        stdout = ''
        if '/reviews' in path and self.fail_reviews and 'POST' in cmd:
            raise subprocess.CalledProcessError(
                1, cmd, stderr=b'HTTP 403: Resource not accessible by integration')
        if path.endswith('/reviews?per_page=100'):
            stdout = ''.join(json.dumps(review) + '\n' for review in self.reviews)
        elif path.endswith('/pulls/42'):
            stdout = self.head + '\n'
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout.encode(), stderr=b'')

    def _review_calls(self, method, suffix=''):
        return [cmd for cmd in self.calls if method in cmd
                and any(arg.startswith('repos/') and arg.endswith(suffix) for arg in cmd)
                and any('/reviews' in arg for arg in cmd)]

    @property
    def requested(self):
        """Bodies of new change requests."""
        return [_field(cmd, 'body') for cmd in self._review_calls('POST')]

    @property
    def edited(self):
        """(review id, body) of edited reviews."""
        return [(int(_path(cmd).rsplit('/', 1)[1]), _field(cmd, 'body'))
                for cmd in self._review_calls('PUT')
                if not _path(cmd).endswith('/dismissals')]

    @property
    def dismissed(self):
        """Ids of dismissed reviews."""
        return [int(_path(cmd).split('/')[-2]) for cmd in self._review_calls('PUT', '/dismissals')]


def _path(cmd):
    return next(arg for arg in cmd if arg.startswith('repos/'))


def _field(cmd, name):
    return next(cmd[i + 1].split('=', 1)[1] for i, arg in enumerate(cmd)
                if arg == '-f' and cmd[i + 1].startswith(f'{name}='))


def _review(review_id, state, keys, review_type='Bot'):
    body = build_review_body([ReviewReason(key, key) for key in keys])
    return {'id': review_id, 'state': state, 'body': body, 'type': review_type}


def _post(tmp_path, response, gh, **kwargs):
    path = tmp_path / 'summary.json'
    path.write_text(json.dumps(response), encoding='utf-8')
    kwargs.setdefault('request_changes', True)
    with mock.patch.object(github_comment, 'is_gh_cli_available', return_value=True), \
            mock.patch.object(github_common.subprocess, 'run', gh), \
            mock.patch.object(github_review.subprocess, 'run', gh):
        post_summary_comment(str(path), **kwargs)


def _context(response):
    return github_comment.build_summary_template_context(response)


def test_reasons_alerts_without_threshold():
    """Without min_change only budget alerts count."""
    assert not review_reasons(_context(GREW))
    reasons = review_reasons(_context(OVER_BUDGET))
    assert [reason.key for reason in reasons] == ['stm32/RAM']
    assert '904 bytes' in reasons[0].text and '*ram*' in reasons[0].text


@pytest.mark.parametrize('response, threshold, keys', [
    (GREW, ChangeThreshold(2048), ['stm32/FLASH']),
    (GREW, ChangeThreshold(2049), []),
    (GREW, ChangeThreshold(20, percent=True), ['stm32/FLASH']),
    (SHRANK, ChangeThreshold(1), []),  # shrinking never asks for changes
    (SMALL, ChangeThreshold(512), []),
])
def test_reasons_growth(response, threshold, keys):
    """With a threshold, regions that grew by at least it count."""
    assert [reason.key for reason in review_reasons(_context(response), threshold)] == keys


def test_requests_changes(tmp_path):
    """Over the threshold: the comment is posted and a change request submitted."""
    gh = FakeGh()
    _post(tmp_path, GREW, gh, min_change='1KB', commit_sha=HEAD[:7])
    assert any(cmd[:3] == ['gh', 'pr', 'comment'] for cmd in gh.calls)
    [body] = gh.requested
    assert REVIEW_MARKER in body and 'stm32** FLASH grew by +2,048 bytes' in body
    assert 'https://membrowse.com/p/x' in body
    post = gh._review_calls('POST')[0]  # pylint: disable=protected-access
    assert _field(post, 'event') == 'REQUEST_CHANGES'
    assert _field(post, 'commit_id') == HEAD  # the full SHA, not the prefix


def test_off_by_default(tmp_path):
    """Without request_changes no review is touched."""
    gh = FakeGh()
    _post(tmp_path, OVER_BUDGET, gh, request_changes=False)
    assert not any('/reviews' in arg for cmd in gh.calls for arg in cmd)


def test_nothing_to_do(tmp_path):
    """Within limits and no earlier request: no review calls beyond the lookup."""
    gh = FakeGh()
    _post(tmp_path, SMALL, gh, min_change='1KB')
    assert not gh.requested and not gh.edited and not gh.dismissed


def test_updates_active_request(tmp_path):
    """Still over a limit on a later push: the same review is edited."""
    gh = FakeGh([_review(5, 'CHANGES_REQUESTED', ['stm32/FLASH'])])
    _post(tmp_path, OVER_BUDGET, gh)
    assert not gh.requested
    assert [review_id for review_id, _ in gh.edited] == [5]
    assert 'stm32/RAM' in gh.edited[0][1]


def test_dismisses_when_fixed(tmp_path):
    """Back within limits: the action clears the keys and dismisses its review."""
    gh = FakeGh([_review(5, 'CHANGES_REQUESTED', ['stm32/FLASH'])])
    _post(tmp_path, SHRANK, gh, min_change='1KB')
    assert gh.dismissed == [5]
    [(review_id, body)] = gh.edited
    assert review_id == 5 and '**Resolved:**' in body
    assert github_review._review_keys(body) == set()  # pylint: disable=protected-access


def test_maintainer_dismissal_is_respected(tmp_path):
    """A maintainer dismissed the request for these regions: do not ask again."""
    gh = FakeGh([_review(5, 'DISMISSED', ['stm32/FLASH'])])
    _post(tmp_path, GREW, gh, min_change='1KB')
    assert not gh.requested


def test_new_region_asks_again(tmp_path):
    """A region the dismissed review did not name gets a new request."""
    gh = FakeGh([_review(5, 'DISMISSED', ['stm32/FLASH'])])
    _post(tmp_path, OVER_BUDGET, gh)
    assert len(gh.requested) == 1


def test_new_request_leaves_out_accepted_regions(tmp_path):
    """A new request names only the regions nobody accepted yet."""
    both = _summary([_region('FLASH', 10_000, 12_048)],
                    alerts=OVER_BUDGET['data']['targets'][0]['alerts'])
    gh = FakeGh([_review(5, 'DISMISSED', ['stm32/FLASH'])])
    _post(tmp_path, both, gh, min_change='1KB')
    [body] = gh.requested
    # pylint: disable=protected-access
    assert github_review._review_keys(body) == {'stm32/RAM'}
    assert 'FLASH' not in body.split('-->', 2)[2]


def test_accepted_region_does_not_keep_review_open(tmp_path):
    """FLASH accepted, RAM flagged then fixed while FLASH is still over: the
    active review is dismissed rather than kept open for FLASH alone."""
    gh = FakeGh([_review(5, 'DISMISSED', ['stm32/FLASH']),
                 _review(6, 'CHANGES_REQUESTED', ['stm32/RAM'])])
    _post(tmp_path, GREW, gh, min_change='1KB')
    assert gh.dismissed == [6] and not gh.requested
    [(review_id, body)] = gh.edited
    assert review_id == 6 and 'already accepted' in body


def test_resolved_then_regressed_asks_again(tmp_path):
    """The action's own dismissal (keys cleared) does not count as accepted."""
    resolved = _review(5, 'DISMISSED', ['stm32/FLASH'])
    resolved['body'] = github_review._resolved_body(resolved['body'])  # pylint: disable=protected-access
    gh = FakeGh([resolved])
    _post(tmp_path, GREW, gh, min_change='1KB')
    assert len(gh.requested) == 1


def test_ignores_other_reviews(tmp_path):
    """Reviews by people, even quoting the marker, are not the action's."""
    gh = FakeGh([_review(5, 'CHANGES_REQUESTED', ['stm32/FLASH'], review_type='User')])
    _post(tmp_path, SHRANK, gh, min_change='1KB')
    assert not gh.dismissed and not gh.edited


def test_stale_commit_is_skipped(tmp_path):
    """A run for an older commit leaves the newer head's review alone."""
    gh = FakeGh([_review(5, 'CHANGES_REQUESTED', ['stm32/FLASH'])], head='b' * 40)
    _post(tmp_path, SHRANK, gh, min_change='1KB', commit_sha=HEAD)
    assert not gh.dismissed and not gh.requested
    assert not any(arg.endswith('/reviews?per_page=100') for cmd in gh.calls for arg in cmd)


def test_permission_error_is_a_warning(tmp_path, caplog):
    """A read-only token logs a hint instead of failing the step."""
    gh = FakeGh(fail_reviews=True)
    _post(tmp_path, OVER_BUDGET, gh)
    assert 'pull-requests: write' in caplog.text
    assert any(cmd[:3] == ['gh', 'pr', 'comment'] for cmd in gh.calls)


def test_keys_cannot_end_the_html_comment():
    """A '-->' in a target name stays inside the keys marker."""
    body = build_review_body([ReviewReason('evil-->/FLASH', 'x')])
    # pylint: disable=protected-access
    assert github_review._review_keys(body) == {'evil-->/FLASH'}


def test_cli_flags(tmp_path):
    """--request-changes and --commit-sha reach post_summary_comment."""
    path = tmp_path / 'summary.json'
    path.write_text(json.dumps(GREW), encoding='utf-8')
    argv = ['github_comment', '--summary-json', str(path),
            '--request-changes', '--commit-sha', HEAD]
    with mock.patch.object(sys, 'argv', argv), \
            mock.patch.object(github_comment, 'post_summary_comment') as post:
        github_comment.main()
    assert post.call_args.kwargs['request_changes'] is True
    assert post.call_args.kwargs['commit_sha'] == HEAD
