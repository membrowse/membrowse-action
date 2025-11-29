"""Tests for Git metadata detection utilities."""

import json
import os
import tempfile
from unittest.mock import patch
from membrowse.utils.git import detect_github_metadata, _parse_pull_request_event


class TestPullRequestMetadata:
    """Test pull request metadata extraction."""

    def test_parse_pull_request_event_extracts_head_sha(self):
        """Test that _parse_pull_request_event extracts the PR head SHA."""
        event_data = {
            'pull_request': {
                'number': 123,
                'head': {
                    'sha': 'abc123def456',
                    'ref': 'feature-branch'
                },
                'base': {
                    'sha': '789ghi012jkl',
                    'ref': 'main'
                }
            }
        }

        (base_sha, branch_name, pr_number, head_sha, pr_name,
         pr_author_name, pr_author_email) = _parse_pull_request_event(event_data)

        assert base_sha == '789ghi012jkl'
        assert branch_name == 'feature-branch'
        assert pr_number == '123'
        assert head_sha == 'abc123def456'
        assert pr_name == ''  # No title in this test data
        assert pr_author_name == ''  # No user in this test data
        assert pr_author_email == ''

    def test_parse_pull_request_event_extracts_pr_name(self):
        """Test that _parse_pull_request_event extracts the PR name/title."""
        event_data = {
            'pull_request': {
                'number': 456,
                'title': 'Add awesome feature',
                'head': {
                    'sha': 'feature123abc',
                    'ref': 'feature-branch'
                },
                'base': {
                    'sha': 'main456def',
                    'ref': 'main'
                }
            }
        }

        (base_sha, branch_name, pr_number, head_sha, pr_name,
         pr_author_name, pr_author_email) = _parse_pull_request_event(event_data)

        assert base_sha == 'main456def'
        assert branch_name == 'feature-branch'
        assert pr_number == '456'
        assert head_sha == 'feature123abc'
        assert pr_name == 'Add awesome feature'
        assert pr_author_name == ''  # No user in this test data
        assert pr_author_email == ''

    def test_detect_github_metadata_uses_pr_head_sha(self):
        """Test that detect_github_metadata uses PR head SHA instead of merge commit."""
        # Create a temporary event payload file
        pr_event = {
            'pull_request': {
                'number': 456,
                'title': 'Implement cool feature',
                'head': {
                    'sha': 'real-commit-sha-123',
                    'ref': 'feature-branch'
                },
                'base': {
                    'sha': 'base-commit-sha-456',
                    'ref': 'main'
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(pr_event, f)
            event_path = f.name

        try:
            # Mock environment variables
            with patch.dict(os.environ, {
                'GITHUB_EVENT_NAME': 'pull_request',
                'GITHUB_SHA': 'merge-commit-sha-789',  # This is the merge commit we want to ignore
                'GITHUB_EVENT_PATH': event_path
            }):
                # Mock git commands to return commit details
                with patch('membrowse.utils.git.run_git_command') as mock_git:
                    def git_side_effect(cmd):
                        responses = {
                            "['log', '-1', '--pretty=format:%B', 'real-commit-sha-123']":
                                'added very cool buffer',
                            "['log', '-1', '--pretty=format:%cI', 'real-commit-sha-123']":
                                '2025-01-10T12:00:00Z',
                            "['log', '-1', '--pretty=format:%an', 'real-commit-sha-123']":
                                'Test Author',
                            "['log', '-1', '--pretty=format:%ae', 'real-commit-sha-123']":
                                'author@example.com',
                            "['config', '--get', 'remote.origin.url']":
                                'https://github.com/user/repo.git',
                            "['rev-parse', 'HEAD~1']":
                                'parent-commit-sha-999'
                        }
                        cmd_str = str(cmd)
                        if cmd_str in responses:
                            return responses[cmd_str]
                        if 'symbolic-ref' in cmd or 'for-each-ref' in cmd:
                            return 'feature-branch'
                        return None

                    mock_git.side_effect = git_side_effect

                    metadata = detect_github_metadata()

                    # Verify the commit_hash is the PR head SHA, not the merge commit SHA
                    assert metadata['commit_hash'] == 'real-commit-sha-123'
                    assert metadata['commit_message'] == 'added very cool buffer'
                    # For PR events: parent is HEAD~1, base is target branch tip
                    assert metadata['parent_commit_hash'] == 'parent-commit-sha-999'
                    assert metadata['base_commit_hash'] == 'base-commit-sha-456'
                    assert metadata['branch_name'] == 'feature-branch'
                    assert metadata['pr_number'] == '456'
                    assert metadata['pr_name'] == 'Implement cool feature'
                    assert metadata['author_name'] == 'Test Author'
                    assert metadata['author_email'] == 'author@example.com'
        finally:
            # Clean up temp file
            os.unlink(event_path)

    def test_detect_github_metadata_push_event_uses_github_sha(self):
        """Test that push events still use GITHUB_SHA as before."""
        push_event = {
            'before': 'parent-commit-sha',
            'after': 'push-commit-sha'
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(push_event, f)
            event_path = f.name

        try:
            with patch.dict(os.environ, {
                'GITHUB_EVENT_NAME': 'push',
                'GITHUB_SHA': 'push-commit-sha',
                'GITHUB_EVENT_PATH': event_path
            }):
                with patch('membrowse.utils.git.run_git_command') as mock_git:
                    def git_side_effect(cmd):
                        responses = {
                            "['log', '-1', '--pretty=format:%B', 'push-commit-sha']":
                                'Push commit message',
                            "['log', '-1', '--pretty=format:%cI', 'push-commit-sha']":
                                '2025-01-10T12:00:00Z',
                            "['log', '-1', '--pretty=format:%an', 'push-commit-sha']":
                                'Push Author',
                            "['log', '-1', '--pretty=format:%ae', 'push-commit-sha']":
                                'push@example.com',
                            "['config', '--get', 'remote.origin.url']":
                                'https://github.com/user/repo.git',
                            "['rev-parse', 'HEAD~1']":
                                'actual-parent-sha-777'
                        }
                        cmd_str = str(cmd)
                        if cmd_str in responses:
                            return responses[cmd_str]
                        if 'symbolic-ref' in cmd or 'for-each-ref' in cmd:
                            return 'main'
                        return None

                    mock_git.side_effect = git_side_effect

                    metadata = detect_github_metadata()

                    # Verify push events use GITHUB_SHA
                    assert metadata['commit_hash'] == 'push-commit-sha'
                    assert metadata['commit_message'] == 'Push commit message'
                    # For push events: both parent and base should be HEAD~1
                    assert metadata['parent_commit_hash'] == 'actual-parent-sha-777'
                    assert metadata['base_commit_hash'] == 'actual-parent-sha-777'
        finally:
            # Clean up temp file
            os.unlink(event_path)
