"""Tests for authentication strategy implementation."""

from unittest.mock import patch
import pytest

from membrowse.auth.strategy import (
    AuthType,
    AuthContext,
    determine_auth_strategy,
    _fork_context_to_dict
)
from membrowse.utils.github import ForkPRContext
from tests.conftest import github_event_context, make_pr_event_data


class TestAuthContext:
    """Test AuthContext dataclass."""

    def test_build_headers_api_key(self):
        """Test that API key auth produces correct headers."""
        context = AuthContext(
            auth_type=AuthType.API_KEY,
            api_key='test-api-key-123'
        )
        headers = context.build_headers()

        assert headers['Authorization'] == 'Bearer test-api-key-123'
        assert headers['Content-Type'] == 'application/json'
        assert 'X-Auth-Type' not in headers

    def test_build_headers_api_key_missing_raises(self):
        """Test that API key auth raises when api_key is None."""
        context = AuthContext(auth_type=AuthType.API_KEY, api_key=None)

        with pytest.raises(ValueError) as exc_info:
            context.build_headers()
        assert 'API key required' in str(exc_info.value)

    def test_build_headers_tokenless(self):
        """Test that tokenless auth produces correct headers."""
        context = AuthContext(
            auth_type=AuthType.GITHUB_TOKENLESS,
            github_context={'pr_number': 123}
        )
        headers = context.build_headers()

        assert headers['X-Auth-Type'] == 'github-tokenless'
        assert headers['Content-Type'] == 'application/json'
        assert 'Authorization' not in headers

    def test_get_metadata_additions_api_key(self):
        """Test that API key auth returns empty metadata additions."""
        context = AuthContext(
            auth_type=AuthType.API_KEY,
            api_key='test-key'
        )
        additions = context.get_metadata_additions()
        assert not additions

    def test_get_metadata_additions_tokenless(self):
        """Test that tokenless auth returns github_context in metadata."""
        github_context = {
            'pr_number': 456,
            'repository': 'owner/repo',
            'commit_sha': 'abc123'
        }
        context = AuthContext(
            auth_type=AuthType.GITHUB_TOKENLESS,
            github_context=github_context
        )
        additions = context.get_metadata_additions()

        assert 'github_context' in additions
        assert additions['github_context']['pr_number'] == 456
        assert additions['github_context']['repository'] == 'owner/repo'


class TestForkContextToDict:  # pylint: disable=too-few-public-methods
    """Test fork context conversion."""

    def test_converts_all_fields(self):
        """Test that ForkPRContext is correctly converted to dict."""
        fork_context = ForkPRContext(
            pr_number=789,
            fork_repo_full_name='contributor/repo',
            base_repo_full_name='owner/repo',
            head_sha='sha123abc',
            pr_author_login='contributor',
            branch_name='feature-xyz'
        )

        result = _fork_context_to_dict(fork_context)

        assert result['pr_number'] == 789
        assert result['fork_repository'] == 'contributor/repo'
        assert result['repository'] == 'owner/repo'
        assert result['commit_sha'] == 'sha123abc'
        assert result['pr_author'] == 'contributor'
        assert result['branch_name'] == 'feature-xyz'


class TestDetermineAuthStrategy:
    """Test authentication strategy determination."""

    def test_api_key_takes_precedence(self):
        """Test that API key is used when provided, even in fork PR context."""
        context = determine_auth_strategy(
            api_key='my-api-key',
            auto_detect_fork=True
        )

        assert context.auth_type == AuthType.API_KEY
        assert context.api_key == 'my-api-key'
        assert context.github_context is None

    def test_tokenless_for_fork_pr_without_api_key(self):
        """Test tokenless auth when in fork PR without API key."""
        event_data = make_pr_event_data(
            head_repo='contributor/repo',
            base_repo='owner/repo',
            pr_number=123
        )

        with github_event_context(event_data):
            context = determine_auth_strategy(
                api_key=None,
                auto_detect_fork=True
            )

            assert context.auth_type == AuthType.GITHUB_TOKENLESS
            assert context.api_key is None
            assert context.github_context is not None
            assert context.github_context['pr_number'] == 123
            assert context.github_context['repository'] == 'owner/repo'
            assert context.github_context['fork_repository'] == 'contributor/repo'

    def test_raises_when_no_api_key_and_not_fork_pr(self):
        """Test that ValueError is raised when no API key and not a fork PR."""
        event_data = make_pr_event_data(
            head_repo='owner/repo',
            base_repo='owner/repo'
        )

        with github_event_context(event_data):
            with pytest.raises(ValueError) as exc_info:
                determine_auth_strategy(
                    api_key=None,
                    auto_detect_fork=True
                )
            assert '--api-key is required' in str(exc_info.value)

    def test_raises_when_no_api_key_and_auto_detect_disabled(self):
        """Test that ValueError is raised when no API key and auto-detect disabled."""
        with pytest.raises(ValueError) as exc_info:
            determine_auth_strategy(
                api_key=None,
                auto_detect_fork=False  # Disabled
            )
        assert '--api-key is required' in str(exc_info.value)

    def test_error_message_mentions_fork_pr_when_github_mode(self):
        """Test that error message mentions fork PR support when in GitHub mode."""
        with patch.dict('os.environ', {
            'GITHUB_EVENT_NAME': 'push',  # Not a PR
        }):
            with pytest.raises(ValueError) as exc_info:
                determine_auth_strategy(
                    api_key=None,
                    auto_detect_fork=True
                )
            error_msg = str(exc_info.value)
            assert '--api-key is required' in error_msg
            assert 'fork prs' in error_msg.lower()
