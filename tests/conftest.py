"""Shared pytest fixtures for MemBrowse tests."""

import json
import os
import tempfile
from contextlib import contextmanager
from unittest.mock import patch

import pytest


@contextmanager
def github_event_context(event_data, event_name='pull_request'):
    """
    Context manager that sets up GitHub Actions environment with event data.

    Args:
        event_data: Dictionary containing the event payload
        event_name: The GitHub event name (default: 'pull_request')

    Yields:
        The path to the temporary event file
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(event_data, f)
        event_path = f.name

    try:
        with patch.dict(os.environ, {
            'GITHUB_EVENT_NAME': event_name,
            'GITHUB_EVENT_PATH': event_path
        }):
            yield event_path
    finally:
        os.unlink(event_path)


def make_pr_event_data(**kwargs):
    """
    Create a pull request event data dictionary.

    Keyword Args:
        head_repo: Full name of the head (source) repository (default: 'contributor/repo')
        base_repo: Full name of the base (target) repository (default: 'owner/repo')
        head_sha: SHA of the head commit (default: 'abc123')
        base_sha: SHA of the base commit (default: 'def456')
        head_ref: Name of the head branch (default: 'feature')
        base_ref: Name of the base branch (default: 'main')
        pr_number: Pull request number (default: 123)
        pr_author: Login of the PR author (default: 'contributor')

    Returns:
        Dictionary containing the pull request event data
    """
    defaults = {
        'head_repo': 'contributor/repo',
        'base_repo': 'owner/repo',
        'head_sha': 'abc123',
        'base_sha': 'def456',
        'head_ref': 'feature',
        'base_ref': 'main',
        'pr_number': 123,
        'pr_author': 'contributor'
    }
    config = {**defaults, **kwargs}

    return {
        'pull_request': {
            'number': config['pr_number'],
            'user': {'login': config['pr_author']},
            'head': {
                'repo': {'full_name': config['head_repo']},
                'sha': config['head_sha'],
                'ref': config['head_ref']
            },
            'base': {
                'repo': {'full_name': config['base_repo']},
                'sha': config['base_sha'],
                'ref': config['base_ref']
            }
        }
    }


@pytest.fixture
def fork_pr_event():
    """Create a fork PR event data (head and base repos differ)."""
    return make_pr_event_data(
        head_repo='contributor/repo',
        base_repo='owner/repo'
    )


@pytest.fixture
def same_repo_pr_event():
    """Create a same-repo PR event data (head and base repos are the same)."""
    return make_pr_event_data(
        head_repo='owner/repo',
        base_repo='owner/repo'
    )
