"""Tests for GitHub fork PR detection utilities."""

import os
import tempfile
from unittest.mock import patch
import pytest

from membrowse.utils.github import is_fork_pr, get_fork_pr_context
from tests.conftest import github_event_context, make_pr_event_data


class TestIsForkPR:
    """Test fork PR detection."""

    def test_returns_false_for_non_pr_event(self):
        """Test that is_fork_pr returns False for push events."""
        with patch.dict('os.environ', {'GITHUB_EVENT_NAME': 'push'}):
            assert is_fork_pr() is False

    def test_returns_false_when_event_path_missing(self):
        """Test that is_fork_pr returns False when GITHUB_EVENT_PATH is not set."""
        with patch.dict('os.environ', {
            'GITHUB_EVENT_NAME': 'pull_request',
            'GITHUB_EVENT_PATH': ''
        }):
            assert is_fork_pr() is False

    def test_returns_true_for_fork_pr(self):
        """Test that is_fork_pr returns True when PR is from a fork."""
        event_data = make_pr_event_data(
            head_repo='contributor/repo',
            base_repo='owner/repo',
            head_ref='feature-branch'
        )

        with github_event_context(event_data):
            assert is_fork_pr() is True

    def test_returns_false_for_same_repo_pr(self):
        """Test that is_fork_pr returns False when PR is from same repo."""
        event_data = make_pr_event_data(
            head_repo='owner/repo',
            base_repo='owner/repo',
            head_ref='feature-branch'
        )

        with github_event_context(event_data):
            assert is_fork_pr() is False

    def test_returns_false_on_invalid_json(self):
        """Test that is_fork_pr returns False for invalid JSON."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('not valid json')
            event_path = f.name

        try:
            with patch.dict('os.environ', {
                'GITHUB_EVENT_NAME': 'pull_request',
                'GITHUB_EVENT_PATH': event_path
            }):
                assert is_fork_pr() is False
        finally:
            os.unlink(event_path)


class TestGetForkPRContext:
    """Test fork PR context extraction."""

    def test_extracts_all_fields(self):
        """Test that get_fork_pr_context extracts all required fields."""
        event_data = make_pr_event_data(
            head_repo='contributor/repo',
            base_repo='owner/repo',
            head_sha='abc123def456',
            base_sha='base789xyz',
            head_ref='feature-branch',
            pr_number=456,
            pr_author='contributor'
        )

        with github_event_context(event_data):
            context = get_fork_pr_context()

            assert context.pr_number == 456
            assert context.fork_repo_full_name == 'contributor/repo'
            assert context.base_repo_full_name == 'owner/repo'
            assert context.head_sha == 'abc123def456'
            assert context.pr_author_login == 'contributor'
            assert context.branch_name == 'feature-branch'

    def test_raises_on_missing_event_path(self):
        """Test that get_fork_pr_context raises ValueError when event path is missing."""
        with patch.dict('os.environ', {
            'GITHUB_EVENT_NAME': 'pull_request',
            'GITHUB_EVENT_PATH': ''
        }):
            with pytest.raises(ValueError) as exc_info:
                get_fork_pr_context()
            assert 'GITHUB_EVENT_PATH not found' in str(exc_info.value)

    def test_raises_on_missing_pr_data(self):
        """Test that get_fork_pr_context raises ValueError when PR data is missing."""
        event_data = {'action': 'opened'}  # No pull_request key

        with github_event_context(event_data):
            with pytest.raises(ValueError) as exc_info:
                get_fork_pr_context()
            assert 'No pull_request data' in str(exc_info.value)

    def test_raises_on_missing_required_fields(self):
        """Test that get_fork_pr_context raises ValueError for missing required fields."""
        event_data = {
            'pull_request': {
                'number': 123,
                # Missing user, head.sha, etc.
                'head': {'ref': 'branch'},
                'base': {'repo': {'full_name': 'owner/repo'}}
            }
        }

        with github_event_context(event_data):
            with pytest.raises(ValueError) as exc_info:
                get_fork_pr_context()
            assert 'Missing required fields' in str(exc_info.value)
