"""Tests for the comment-action's --skip-unchanged option and comment lookup."""

import json
import subprocess
import sys
from unittest import mock

import pytest

from membrowse.utils import github_comment, github_common
from membrowse.utils.github_comment import (
    COMMENT_MARKER, ChangeThreshold, parse_min_change, post_summary_comment,
)


def _summary(modified_regions=None, alerts=None) -> dict:
    """A /summary API response with one target."""
    return {
        'data': {
            'pr_number': 42,
            'targets': [{
                'target_name': 'stm32',
                'changes_summary': {
                    'changes': {'regions': {'modified': modified_regions or []}},
                },
                'alerts': alerts or {},
            }],
        }
    }


UNCHANGED = _summary()
CHANGED = _summary([{
    'name': 'FLASH', 'used_size': 1100, 'limit_size': 4096,
    'old': {'used_size': 1000},
}])


class FakeGh:
    """Stands in for subprocess.run calls to the gh CLI."""

    def __init__(self, existing_comment_id=None):
        self.existing_comment_id = existing_comment_id
        self.calls = []

    def __call__(self, cmd, **_kwargs):
        self.calls.append(cmd)
        stdout = b''
        if cmd[:2] == ['gh', 'api'] and '--jq' in cmd and self.existing_comment_id:
            stdout = (
                json.dumps({'id': 1, 'body': 'unrelated'}) + '\n'
                + json.dumps({'id': self.existing_comment_id,
                              'body': f'{COMMENT_MARKER}\nold'}) + '\n'
            ).encode()
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr=b'')

    @property
    def created(self) -> bool:
        """True if a new PR comment was created."""
        return any(cmd[:3] == ['gh', 'pr', 'comment'] for cmd in self.calls)

    @property
    def updated(self) -> bool:
        """True if an existing comment was edited."""
        return any('PATCH' in cmd for cmd in self.calls)


def _post(tmp_path, response, gh, **kwargs):
    path = tmp_path / 'summary.json'
    path.write_text(json.dumps(response), encoding='utf-8')
    with mock.patch.object(github_comment, 'is_gh_cli_available', return_value=True), \
            mock.patch.object(github_common.subprocess, 'run', gh):
        post_summary_comment(str(path), **kwargs)


@pytest.mark.parametrize('response, existing, skip, created, updated', [
    # Without the option a comment is always posted.
    (UNCHANGED, None, False, True, False),
    # Nothing changed and no comment yet: stay quiet.
    (UNCHANGED, None, True, False, False),
    # Nothing changed but a comment exists: update it so it does not go stale.
    (UNCHANGED, 99, True, False, True),
    # Memory changed: comment as usual.
    (CHANGED, None, True, True, False),
    (CHANGED, 99, True, False, True),
])
def test_skip_unchanged(tmp_path, response, existing, skip, created, updated):
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    """A comment is created only when needed; an existing one is always updated."""
    gh = FakeGh(existing)
    _post(tmp_path, response, gh, skip_unchanged=skip)
    assert gh.created is created
    assert gh.updated is updated


def test_alerts_count_as_changes():
    """A budget alert alone is reason enough to comment."""
    context = {'targets': [{'has_changes': False, 'has_alerts': True}]}
    # pylint: disable=protected-access
    assert github_comment._has_memory_changes(context)
    assert not github_comment._has_memory_changes(
        {'targets': [{'has_changes': False, 'has_alerts': False}]})
    assert not github_comment._has_memory_changes({'targets': []})


def test_find_existing_comment_paginates():
    """The comment lookup lists every page, not just gh's first 30 comments."""
    gh = FakeGh(existing_comment_id=7)
    with mock.patch.object(github_common.subprocess, 'run', gh):
        assert github_common.find_existing_comment('42', COMMENT_MARKER) == 7
    cmd = gh.calls[0]
    assert '--paginate' in cmd
    assert any('per_page=100' in arg for arg in cmd)


def test_combined_comment_skip_unchanged():
    """File mode honours skip_unchanged too."""
    results = [{'pr_number': 42, 'target_name': 'stm32', 'api_response': {'data': {}}}]
    gh = FakeGh()
    with mock.patch.object(github_comment, 'is_gh_cli_available', return_value=True), \
            mock.patch.object(github_common.subprocess, 'run', gh):
        github_comment.post_combined_pr_comment(results, skip_unchanged=True)
    assert not gh.created


SMALL = _summary([{
    'name': 'FLASH', 'used_size': 10_100, 'limit_size': 65_536,
    'old': {'used_size': 10_000},
}])  # +100 bytes, +1%
SHRANK = _summary([{
    'name': 'RAM', 'used_size': 7_000, 'limit_size': 65_536,
    'old': {'used_size': 10_000},
}])  # -3,000 bytes, -30%
SMALL_WITH_ALERT = _summary(
    SMALL['data']['targets'][0]['changes_summary']['changes']['regions']['modified'],
    alerts={'budgets': [{
        'budget_name': 'flash', 'exceeded_regions': ['FLASH'],
        'current_usage': {'FLASH': 10_100}, 'limits': {'FLASH': 10_050},
        'exceeded_by': {'FLASH': 50},
    }]},
)


@pytest.mark.parametrize('text, expected', [
    ('512', ChangeThreshold(512)),
    ('512B', ChangeThreshold(512)),
    (' 2KB ', ChangeThreshold(2048)),
    ('2kib', ChangeThreshold(2048)),
    ('1.5K', ChangeThreshold(1536)),
    ('1MB', ChangeThreshold(1024 ** 2)),
    ('0.5%', ChangeThreshold(0.5, percent=True)),
    ('10 %', ChangeThreshold(10, percent=True)),
])
def test_parse_min_change(text, expected):
    """Bytes with an optional 1024-based unit, or a percentage."""
    assert parse_min_change(text) == expected


@pytest.mark.parametrize('text', ['', 'abc', '-5', '5GB', '1.2.3', '%', '5 % %'])
def test_parse_min_change_rejects(text):
    """Anything else is an error rather than silently no threshold."""
    with pytest.raises(ValueError):
        parse_min_change(text)


@pytest.mark.parametrize('response, min_change, created', [
    (SMALL, '100', True),        # exactly at the threshold
    (SMALL, '101', False),
    (SMALL, '1%', True),
    (SMALL, '1.5%', False),
    (SHRANK, '2KB', True),       # shrinking counts too
    (SHRANK, '25%', True),
    (SHRANK, '4KB', False),
    (UNCHANGED, '0', False),     # nothing changed at all
    (SMALL_WITH_ALERT, '1MB', True),  # alerts always comment
    (SMALL, '', True),           # empty: no threshold, always comment
])
def test_min_change(tmp_path, response, min_change, created):
    """A new comment needs a region change of at least min_change."""
    gh = FakeGh()
    _post(tmp_path, response, gh, min_change=min_change)
    assert gh.created is created


def test_min_change_still_updates_existing(tmp_path):
    """Below the threshold an existing comment is still updated."""
    gh = FakeGh(existing_comment_id=99)
    _post(tmp_path, SMALL, gh, min_change='1KB')
    assert gh.updated and not gh.created


def test_min_change_wins_over_skip_unchanged(tmp_path):
    """With both set, the threshold decides."""
    gh = FakeGh()
    _post(tmp_path, SMALL, gh, skip_unchanged=True, min_change='1KB')
    assert not gh.created


@pytest.mark.parametrize('delta', [55, -55])
def test_min_change_percent_boundary(delta):
    """A change of exactly the percentage reaches it despite float rounding."""
    region = {'delta': delta, 'old': {'used_size': 10_000}}
    # pylint: disable=protected-access
    assert github_comment._region_reaches(region, ChangeThreshold(0.55, percent=True))
    assert not github_comment._region_reaches(region, ChangeThreshold(0.56, percent=True))


def test_min_change_from_nothing():
    """A region growing from zero bytes passes any percentage."""
    region = {'delta': 4, 'old': {'used_size': 0}}
    # pylint: disable=protected-access
    assert github_comment._region_reaches(region, ChangeThreshold(1000, percent=True))


def test_min_change_cli(tmp_path):
    """--min-change reaches post_summary_comment parsed; bad values exit."""
    path = tmp_path / 'summary.json'
    path.write_text(json.dumps(SMALL), encoding='utf-8')
    argv = ['github_comment', '--summary-json', str(path), '--min-change', '2KB']
    with mock.patch.object(sys, 'argv', argv), \
            mock.patch.object(github_comment, 'post_summary_comment') as post:
        github_comment.main()
    assert post.call_args.kwargs['min_change'] == ChangeThreshold(2048)

    argv[-1] = 'lots'
    with mock.patch.object(sys, 'argv', argv), pytest.raises(SystemExit):
        github_comment.main()
