"""Tests for the comment-action's --skip-unchanged option and comment lookup."""

import json
import subprocess
from unittest import mock

import pytest

from membrowse.utils import github_comment, github_common
from membrowse.utils.github_comment import COMMENT_MARKER, post_summary_comment


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
