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
                    'sha': 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0',
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
                    # For PR events: base is target branch tip
                    assert metadata['base_commit_hash'] == \
                        'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0'
                    assert metadata['branch_name'] == 'feature-branch'
                    assert metadata['pr_number'] == '456'
                    assert metadata['pr_name'] == 'Implement cool feature'
                    assert metadata['author_name'] == 'Test Author'
                    assert metadata['author_email'] == 'author@example.com'
        finally:
            # Clean up temp file
            os.unlink(event_path)

    def test_detect_github_metadata_push_event_uses_event_before(self):
        """Push events base on the event's 'before' (previous branch tip),
        not the git parent (HEAD~1). This bridges over unbuilt intermediate
        commits of a multi-commit push so the report chain stays intact."""
        push_event = {
            'before': 'c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0',
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
                    # For push events: base is the event 'before', not HEAD~1
                    assert metadata['base_commit_hash'] == \
                        'c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0'
        finally:
            # Clean up temp file
            os.unlink(event_path)

    def test_detect_github_metadata_push_event_falls_back_to_git_parent(self):
        """When a push event has no usable 'before' (e.g. branch creation),
        fall back to the git parent (HEAD~1)."""
        push_event = {
            'before': '',
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

                    # No 'before' -> fall back to HEAD~1
                    assert metadata['base_commit_hash'] == 'actual-parent-sha-777'
        finally:
            os.unlink(event_path)

    def test_detect_github_metadata_push_event_ignores_zero_before(self):
        """Branch creation / first push sends an all-zero 'before'; it is not a
        real commit, so fall back to the git parent (HEAD~1)."""
        push_event = {
            'before': '0' * 40,
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

                    # All-zero 'before' -> fall back to HEAD~1
                    assert metadata['base_commit_hash'] == 'actual-parent-sha-777'
        finally:
            os.unlink(event_path)

    def test_detect_github_metadata_push_event_ignores_malformed_before(self):
        """A malformed/non-SHA 'before' from a custom event payload must not be
        trusted; fall back to the git parent (HEAD~1)."""
        push_event = {
            'before': 'not-a-real-sha',
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

                    # Malformed 'before' -> fall back to HEAD~1
                    assert metadata['base_commit_hash'] == 'actual-parent-sha-777'
        finally:
            os.unlink(event_path)


class TestAncestry:
    """First-parent ancestry collection (metadata.git.ancestry)."""

    @staticmethod
    def _sha(n):
        return f'{n:040x}'

    def test_local_rev_list_is_first_parent_and_capped(self):
        from membrowse.utils.git import get_ancestry, ANCESTRY_DEPTH
        seen = []

        def git_side_effect(cmd):
            seen.append(cmd)
            if cmd[0] == 'rev-list':
                return '\n'.join(self._sha(i) for i in range(1, 4))
            return None

        with patch('membrowse.utils.git.run_git_command', side_effect=git_side_effect):
            line = get_ancestry(self._sha(1))

        assert line == [self._sha(1), self._sha(2), self._sha(3)]
        assert seen[0] == ['rev-list', '--first-parent',
                           f'--max-count={ANCESTRY_DEPTH}', self._sha(1)]
        # Not shallow (rev-parse yields nothing): the short line is final.
        assert 'fetch' not in [cmd[0] for cmd in seen]
        assert ANCESTRY_DEPTH == 200

    def test_shallow_clone_deepens_then_rev_lists_again(self):
        """actions/checkout at fetch-depth 2 yields exactly two entries; that
        is a truncated line, not a short repository, and must deepen."""
        from membrowse.utils.git import get_ancestry
        calls = []

        def git_side_effect(cmd):
            calls.append(cmd[0])
            if cmd[0] == 'rev-list':
                # Two commits before the fetch, the full line after it.
                if 'fetch' in calls:
                    return '\n'.join(self._sha(i) for i in range(1, 6))
                return '\n'.join([self._sha(1), self._sha(2)])
            if cmd[0] == 'rev-parse' and '--is-shallow-repository' in cmd:
                # Shallow until the fetch; the deepened history is complete.
                return 'false' if 'fetch' in calls else 'true'
            if cmd[0] == 'fetch':
                assert '--filter=tree:0' in cmd and '--depth=200' in cmd
                assert cmd[-2:] == ['origin', self._sha(1)]
                return ''
            return None

        with patch('membrowse.utils.git.run_git_command', side_effect=git_side_effect):
            line = get_ancestry(self._sha(1))

        assert calls == ['rev-list', 'rev-parse', 'fetch', 'rev-list', 'rev-parse']
        assert len(line) == 5

    def test_full_clone_with_short_history_never_fetches(self):
        """A repository with fewer than ANCESTRY_DEPTH commits is complete as
        it is; a non-shallow checkout is final however short the line."""
        from membrowse.utils.git import get_ancestry
        calls = []

        def git_side_effect(cmd):
            calls.append(cmd[0])
            if cmd[0] == 'rev-list':
                return '\n'.join([self._sha(1), self._sha(2), self._sha(3)])
            if cmd[0] == 'rev-parse':
                return 'false'
            return None

        with patch('membrowse.utils.git.run_git_command', side_effect=git_side_effect):
            line = get_ancestry(self._sha(1))

        assert line == [self._sha(1), self._sha(2), self._sha(3)]
        assert calls == ['rev-list', 'rev-parse']

    def test_full_depth_line_is_final_without_a_shallow_check(self):
        from membrowse.utils.git import get_ancestry, ANCESTRY_DEPTH
        calls = []

        def git_side_effect(cmd):
            calls.append(cmd[0])
            if cmd[0] == 'rev-list':
                return '\n'.join(self._sha(i) for i in range(1, ANCESTRY_DEPTH + 1))
            return None

        with patch('membrowse.utils.git.run_git_command', side_effect=git_side_effect):
            assert len(get_ancestry(self._sha(1))) == ANCESTRY_DEPTH
        assert calls == ['rev-list']

    def test_fetch_failure_falls_back_to_github_api(self):
        from membrowse.utils.git import get_ancestry
        # Commits listing is NOT first-parent only: 3 is a second parent of 2
        # and must be skipped by following parents[0].
        commits = [
            {'sha': self._sha(1), 'parents': [{'sha': self._sha(2)}]},
            {'sha': self._sha(2), 'parents': [{'sha': self._sha(4)}, {'sha': self._sha(3)}]},
            {'sha': self._sha(3), 'parents': [{'sha': self._sha(4)}]},
            {'sha': self._sha(4), 'parents': []},
        ]

        class Resp:
            status_code = 200

            def json(self):
                return commits

        def git_side_effect(cmd):
            if cmd[0] == 'rev-list':
                return self._sha(1)
            if cmd[0] == 'rev-parse':
                return 'true'
            return None  # fetch fails

        with patch.dict(os.environ, {'GITHUB_REPOSITORY': 'o/r', 'GITHUB_TOKEN': 't'}), \
                patch('membrowse.utils.git.run_git_command', side_effect=git_side_effect), \
                patch('membrowse.utils.git.requests.get', return_value=Resp()) as get:
            line = get_ancestry(self._sha(1))

        assert line == [self._sha(1), self._sha(2), self._sha(4)]
        assert get.call_args[0][0] == 'https://api.github.com/repos/o/r/commits'
        assert get.call_args[1]['params']['sha'] == self._sha(1)

    def test_every_fallback_failing_still_returns_what_is_local(self):
        from membrowse.utils.git import get_ancestry

        def git_side_effect(cmd):
            if cmd[0] == 'rev-list':
                return self._sha(1)
            if cmd[0] == 'rev-parse':
                return 'true'
            return None

        with patch.dict(os.environ, {'GITHUB_REPOSITORY': '', 'GITHUB_TOKEN': ''}), \
                patch('membrowse.utils.git.run_git_command', side_effect=git_side_effect):
            assert get_ancestry(self._sha(1)) == [self._sha(1)]

        with patch('membrowse.utils.git.run_git_command', return_value=None):
            assert get_ancestry(self._sha(1)) == []
            assert get_ancestry('') == []

    def test_non_sha_start_never_fetches(self):
        """Tests and odd checkouts pass logical names; no network for those."""
        from membrowse.utils.git import get_ancestry
        calls = []
        with patch('membrowse.utils.git.run_git_command',
                   side_effect=lambda cmd: calls.append(cmd[0])):
            assert get_ancestry('not-a-sha') == []
        assert 'fetch' not in calls

    def test_fetch_can_be_disabled(self):
        from membrowse.utils.git import get_ancestry
        calls = []
        with patch('membrowse.utils.git.run_git_command',
                   side_effect=lambda cmd: calls.append(cmd[0]) or self._sha(1)):
            assert get_ancestry(self._sha(1), fetch=False) == [self._sha(1)]
        assert calls == ['rev-list']

    def test_malformed_rev_list_output_is_dropped(self):
        from membrowse.utils.git import get_ancestry
        with patch('membrowse.utils.git.run_git_command',
                   return_value=f'{self._sha(1)}\nfatal: bad object'):
            assert get_ancestry(self._sha(1), fetch=False) == []

    def test_exceptions_never_escape(self):
        from membrowse.utils.git import get_ancestry
        with patch('membrowse.utils.git.run_git_command', side_effect=RuntimeError('boom')):
            assert get_ancestry(self._sha(1)) == []


class TestAncestryInMetadata:
    """Where the line starts, per event."""

    @staticmethod
    def _sha(n):
        return f'{n:040x}'

    def _run(self, event_name, event, env, git_side_effect):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(event, f)
            event_path = f.name
        try:
            with patch.dict(os.environ, {
                    'GITHUB_EVENT_NAME': event_name,
                    'GITHUB_EVENT_PATH': event_path,
                    'GITHUB_REPOSITORY': '', 'GITHUB_TOKEN': '',
                    **env}):
                with patch('membrowse.utils.git.run_git_command',
                           side_effect=git_side_effect):
                    return detect_github_metadata()
        finally:
            os.unlink(event_path)

    def _git(self, lines_by_start):
        def side_effect(cmd):
            if cmd[0] == 'rev-list':
                return lines_by_start.get(cmd[-1])
            if 'symbolic-ref' in cmd or 'for-each-ref' in cmd:
                return 'main'
            return None
        return side_effect

    def test_push_event_starts_at_the_reported_commit(self):
        head, before, older = self._sha(10), self._sha(9), self._sha(8)
        metadata = self._run(
            'push', {'before': before, 'after': head}, {'GITHUB_SHA': head},
            self._git({head: '\n'.join([head, before, older])}))

        assert metadata['commit_hash'] == head
        assert metadata['base_commit_hash'] == before
        assert metadata['ancestry'] == [head, before, older]
        assert 'backfill' not in metadata

    def test_pull_request_event_starts_at_the_base(self):
        head, base, older = self._sha(20), self._sha(19), self._sha(18)
        event = {'pull_request': {
            'number': 5, 'title': 'x',
            'head': {'sha': head, 'ref': 'feature'},
            'base': {'sha': base, 'ref': 'main'}}}
        metadata = self._run(
            'pull_request', event, {'GITHUB_SHA': self._sha(99)},
            self._git({base: '\n'.join([base, older]),
                       head: '\n'.join([head, base, older])}))

        assert metadata['commit_hash'] == head
        assert metadata['base_commit_hash'] == base
        assert metadata['ancestry'] == [base, older], \
            "A PR line walks the target branch, not the PR branch"

    def test_no_ancestry_key_when_nothing_was_learned(self):
        head = self._sha(30)
        metadata = self._run(
            'push', {'before': '', 'after': head}, {'GITHUB_SHA': head},
            self._git({}))
        assert 'ancestry' not in metadata

    def test_workflow_run_reports_the_triggering_head_not_github_sha(self):
        """On workflow_run GITHUB_SHA is the default branch tip. The job built
        workflow_run.head_sha, and that is what must be reported."""
        head, base, older = self._sha(40), self._sha(39), self._sha(38)
        event = {'workflow_run': {
            'head_sha': head, 'head_branch': 'feature',
            'pull_requests': [{'number': 77, 'base': {'sha': base}}]}}
        metadata = self._run(
            'workflow_run', event, {'GITHUB_SHA': self._sha(99)},
            self._git({base: '\n'.join([base, older])}))

        assert metadata['commit_hash'] == head
        assert metadata['branch_name'] == 'feature'
        assert metadata['pr_number'] == '77'
        assert metadata['base_commit_hash'] == base
        assert metadata['ancestry'] == [base, older]

    def test_workflow_run_without_pr_keeps_git_parent(self):
        head, parent = self._sha(50), self._sha(49)
        event = {'workflow_run': {'head_sha': head, 'head_branch': 'master',
                                  'pull_requests': []}}

        def side_effect(cmd):
            if cmd == ['rev-parse', 'HEAD~1']:
                return parent
            if cmd[0] == 'rev-list' and cmd[-1] == head:
                return '\n'.join([head, parent])
            if 'symbolic-ref' in cmd or 'for-each-ref' in cmd:
                return 'master'
            return None

        metadata = self._run('workflow_run', event, {'GITHUB_SHA': self._sha(99)}, side_effect)
        assert metadata['commit_hash'] == head
        assert metadata['pr_number'] is None
        assert metadata['base_commit_hash'] == parent
        assert metadata['ancestry'] == [head, parent]


class TestOnboardBackfill:
    """onboard replays history and says so."""

    @staticmethod
    def _sha(n):
        return f'{n:040x}'

    def test_onboard_commit_info_carries_backfill_and_local_ancestry(self):
        from membrowse.commands.onboard import _build_commit_info
        head, parent = self._sha(60), self._sha(59)
        meta = {'commit_sha': head, 'parent_sha': parent, 'commit_message': 'm',
                'commit_timestamp': '2025-01-01T00:00:00Z', 'author_name': 'a',
                'author_email': 'a@x', 'tags': []}
        calls = []

        def side_effect(cmd):
            calls.append(cmd[0])
            if cmd[0] == 'rev-list':
                return '\n'.join([head, parent])
            return None

        with patch('membrowse.commands.onboard.get_commit_metadata', return_value=meta), \
                patch('membrowse.utils.git.run_git_command', side_effect=side_effect):
            info = _build_commit_info(head, 'main', 'repo')

        assert info['backfill'] is True
        assert info['base_commit_hash'] == parent
        assert info['ancestry'] == [head, parent]
        assert calls == ['rev-list'], "a full clone never deepens or calls the API"

    def test_report_detection_never_sets_backfill(self):
        from membrowse.utils.git import detect_git_metadata
        with patch('membrowse.utils.git.run_git_command', return_value=None):
            assert 'backfill' not in detect_git_metadata()
