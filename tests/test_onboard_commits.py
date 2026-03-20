"""Tests for the --commits feature of the onboard subcommand."""

import argparse
from unittest.mock import patch, MagicMock, call

import pytest

from membrowse.commands.onboard import (
    add_onboard_parser,
    run_onboard,
    _resolve_and_validate_commits,
)


# ---------------------------------------------------------------------------
# Helper: build an argparse parser that mirrors the real CLI
# ---------------------------------------------------------------------------

def _make_parser():
    parser = argparse.ArgumentParser()
    add_onboard_parser(parser.add_subparsers())
    return parser


def _parse(argv):
    return _make_parser().parse_args(['onboard'] + argv)


# Shared positional args used across tests
_POSITIONALS = ['make build', 'fw.elf', 'stm32', 'KEY123']


# ---------------------------------------------------------------------------
# CLI Argument Parsing
# ---------------------------------------------------------------------------

class TestCommitsArgParsing:
    """Test --commits CLI argument parsing."""

    def test_commits_without_num_commits(self):
        """--commits with no num_commits parses correctly."""
        args = _parse(['--commits', 'v1.0 v1.1 v2.0'] + _POSITIONALS)
        assert args.commits == 'v1.0 v1.1 v2.0'
        assert args.num_commits is None

    def test_num_commits_without_commits(self):
        """Existing usage: num_commits without --commits still works."""
        args = _parse(['50'] + _POSITIONALS)
        assert args.num_commits == 50
        assert args.commits is None

    def test_num_commits_with_api_url_positional(self):
        """Existing usage: num_commits with positional api_url still works."""
        args = _parse(['50'] + _POSITIONALS + ['https://custom.com'])
        assert args.num_commits == 50
        assert args.api_url == 'https://custom.com'

    def test_commits_with_api_url_flag(self):
        """--commits with --api-url flag parses correctly."""
        args = _parse([
            '--commits', 'a1 b2',
            '--api-url', 'https://custom.com',
        ] + _POSITIONALS)
        assert args.commits == 'a1 b2'
        assert args.api_url_flag == 'https://custom.com'
        assert args.num_commits is None

    def test_commits_without_api_url_uses_default(self):
        """--commits without --api-url uses the default API URL."""
        args = _parse(['--commits', 'a1 b2'] + _POSITIONALS)
        assert args.api_url_flag is None
        assert args.api_url == 'https://api.membrowse.com'

    def test_api_url_flag_overrides_positional(self):
        """--api-url flag is available alongside positional api_url."""
        args = _parse(['50'] + _POSITIONALS + ['--api-url', 'https://flag.com'])
        assert args.api_url_flag == 'https://flag.com'


# ---------------------------------------------------------------------------
# Mutual Exclusion Validation (in run_onboard)
# ---------------------------------------------------------------------------

class TestCommitsMutualExclusion:
    """Test mutual exclusion between --commits, num_commits, and --initial-commit."""

    @patch('membrowse.commands.onboard._get_repository_info')
    def test_both_num_commits_and_commits_errors(self, mock_repo_info):
        """Providing both num_commits and --commits returns error."""
        # This case requires manually constructing args since argparse
        # can parse both when num_commits is an int and --commits is given
        args = argparse.Namespace(
            num_commits=10,
            commits='v1.0 v1.1',
            initial_commit=None,
            build_script='make',
            elf_path='fw.elf',
            target_name='stm32',
            api_key='KEY',
            api_url='https://api.membrowse.com',
            api_url_flag=None,
            ld_scripts=None,
            linker_defs=None,
            build_dirs=None,
        )
        result = run_onboard(args)
        assert result == 1
        mock_repo_info.assert_not_called()

    @patch('membrowse.commands.onboard._get_repository_info')
    def test_commits_and_initial_commit_errors(self, mock_repo_info):
        """Providing both --commits and --initial-commit returns error."""
        args = argparse.Namespace(
            num_commits=None,
            commits='v1.0 v1.1',
            initial_commit='abc123',
            build_script='make',
            elf_path='fw.elf',
            target_name='stm32',
            api_key='KEY',
            api_url='https://api.membrowse.com',
            api_url_flag=None,
            ld_scripts=None,
            linker_defs=None,
            build_dirs=None,
        )
        result = run_onboard(args)
        assert result == 1
        mock_repo_info.assert_not_called()

    @patch('membrowse.commands.onboard._get_repository_info')
    def test_neither_num_commits_nor_commits_errors(self, mock_repo_info):
        """Providing neither num_commits nor --commits returns error."""
        args = argparse.Namespace(
            num_commits=None,
            commits=None,
            initial_commit=None,
            build_script='make',
            elf_path='fw.elf',
            target_name='stm32',
            api_key='KEY',
            api_url='https://api.membrowse.com',
            api_url_flag=None,
            ld_scripts=None,
            linker_defs=None,
            build_dirs=None,
        )
        result = run_onboard(args)
        assert result == 1
        mock_repo_info.assert_not_called()


# ---------------------------------------------------------------------------
# Commit Resolution (_resolve_and_validate_commits)
# ---------------------------------------------------------------------------

class TestResolveAndValidateCommits:
    """Test _resolve_and_validate_commits function."""

    @patch('membrowse.commands.onboard.run_git_command')
    def test_valid_hashes_resolve(self, mock_git):
        """Valid commit hashes resolve to full SHAs."""
        mock_git.side_effect = ['aaa111', 'bbb222', 'ccc333']
        result = _resolve_and_validate_commits('aaa bbb ccc')
        assert result == ['aaa111', 'bbb222', 'ccc333']
        assert mock_git.call_count == 3

    @patch('membrowse.commands.onboard.run_git_command')
    def test_tags_resolve(self, mock_git):
        """Tags resolve to commit SHAs."""
        mock_git.side_effect = ['sha_for_v1', 'sha_for_v2']
        result = _resolve_and_validate_commits('v1.0 v2.0')
        assert result == ['sha_for_v1', 'sha_for_v2']
        # Verify ^{commit} syntax is used to dereference tags
        mock_git.assert_any_call(['rev-parse', '--verify', 'v1.0^{commit}'])
        mock_git.assert_any_call(['rev-parse', '--verify', 'v2.0^{commit}'])

    @patch('membrowse.commands.onboard.run_git_command')
    def test_mixed_hashes_and_tags(self, mock_git):
        """Mixed hashes and tags all resolve."""
        mock_git.side_effect = ['sha1', 'sha2', 'sha3']
        result = _resolve_and_validate_commits('abc123 v1.0 def456')
        assert result == ['sha1', 'sha2', 'sha3']

    @patch('membrowse.commands.onboard.run_git_command')
    def test_one_invalid_ref_raises(self, mock_git):
        """One invalid ref among valid ones raises ValueError."""
        mock_git.side_effect = ['sha1', None, 'sha3']
        with pytest.raises(ValueError, match='bad_ref'):
            _resolve_and_validate_commits('good1 bad_ref good2')

    @patch('membrowse.commands.onboard.run_git_command')
    def test_all_invalid_refs_raises(self, mock_git):
        """All invalid refs raises ValueError listing all."""
        mock_git.side_effect = [None, None]
        with pytest.raises(ValueError, match='bad1.*bad2'):
            _resolve_and_validate_commits('bad1 bad2')

    def test_empty_string_raises(self):
        """Empty string raises ValueError."""
        with pytest.raises(ValueError, match='at least one'):
            _resolve_and_validate_commits('')

    @patch('membrowse.commands.onboard.run_git_command')
    def test_abbreviated_hashes_resolve(self, mock_git):
        """Abbreviated commit hashes resolve to full SHAs."""
        mock_git.return_value = 'aabbccdd11223344'
        result = _resolve_and_validate_commits('aabbcc')
        assert result == ['aabbccdd11223344']


# ---------------------------------------------------------------------------
# Faked Parent Chain
# ---------------------------------------------------------------------------

class TestFakedParentChain:
    """Test that --commits produces a faked parent chain in uploads."""

    def _make_args(self, commits_str):
        """Create a Namespace with --commits set."""
        return argparse.Namespace(
            num_commits=None,
            commits=commits_str,
            initial_commit=None,
            build_script='true',  # no-op build
            elf_path='fw.elf',
            target_name='stm32',
            api_key='KEY',
            api_url='https://api.membrowse.com',
            api_url_flag=None,
            ld_scripts=None,
            linker_defs=None,
            build_dirs=None,
        )

    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.generate_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    @patch('membrowse.commands.onboard.subprocess')
    @patch('membrowse.commands.onboard._get_repository_info')
    @patch('membrowse.commands.onboard._resolve_and_validate_commits')
    @patch('membrowse.commands.onboard.os.path.exists', return_value=True)
    def test_single_commit_parent_is_none(
        self, mock_exists, mock_resolve, mock_repo, mock_subprocess,
        mock_metadata, mock_generate, mock_upload,
    ):
        """Single commit gets base_commit_hash=None."""
        mock_resolve.return_value = ['aaa111']
        mock_repo.return_value = ('main', 'original_head', 'my-repo')
        mock_subprocess.run.return_value = MagicMock(returncode=0)
        mock_metadata.return_value = {
            'commit_sha': 'aaa111',
            'base_sha': 'real_parent',
            'commit_message': 'msg',
            'commit_timestamp': '2024-01-01T00:00:00Z',
            'author_name': 'Test',
            'author_email': 'test@test.com',
        }
        mock_generate.return_value = {'memory_layout': {}}

        run_onboard(self._make_args('aaa111'))

        commit_info = mock_upload.call_args[1]['commit_info']
        assert commit_info['base_commit_hash'] is None
        assert commit_info['commit_hash'] == 'aaa111'

    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.generate_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    @patch('membrowse.commands.onboard.subprocess')
    @patch('membrowse.commands.onboard._get_repository_info')
    @patch('membrowse.commands.onboard._resolve_and_validate_commits')
    @patch('membrowse.commands.onboard.os.path.exists', return_value=True)
    def test_two_commits_parent_chain(
        self, mock_exists, mock_resolve, mock_repo, mock_subprocess,
        mock_metadata, mock_generate, mock_upload,
    ):
        """Two commits: first gets None, second gets first's SHA."""
        mock_resolve.return_value = ['aaa111', 'bbb222']
        mock_repo.return_value = ('main', 'original_head', 'my-repo')
        mock_subprocess.run.return_value = MagicMock(returncode=0)
        mock_metadata.side_effect = [
            {
                'commit_sha': 'aaa111', 'base_sha': 'real_parent_a',
                'commit_message': 'msg1', 'commit_timestamp': 'ts1',
                'author_name': 'A', 'author_email': 'a@test.com',
            },
            {
                'commit_sha': 'bbb222', 'base_sha': 'real_parent_b',
                'commit_message': 'msg2', 'commit_timestamp': 'ts2',
                'author_name': 'B', 'author_email': 'b@test.com',
            },
        ]
        mock_generate.return_value = {'memory_layout': {}}

        run_onboard(self._make_args('aaa bbb'))

        assert mock_upload.call_count == 2
        first_info = mock_upload.call_args_list[0][1]['commit_info']
        second_info = mock_upload.call_args_list[1][1]['commit_info']
        assert first_info['base_commit_hash'] is None
        assert second_info['base_commit_hash'] == 'aaa111'

    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.generate_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    @patch('membrowse.commands.onboard.subprocess')
    @patch('membrowse.commands.onboard._get_repository_info')
    @patch('membrowse.commands.onboard._resolve_and_validate_commits')
    @patch('membrowse.commands.onboard.os.path.exists', return_value=True)
    def test_three_commits_full_chain(
        self, mock_exists, mock_resolve, mock_repo, mock_subprocess,
        mock_metadata, mock_generate, mock_upload,
    ):
        """Three commits: A->None, B->A, C->B."""
        shas = ['aaa111', 'bbb222', 'ccc333']
        mock_resolve.return_value = shas
        mock_repo.return_value = ('main', 'original_head', 'my-repo')
        mock_subprocess.run.return_value = MagicMock(returncode=0)
        mock_metadata.side_effect = [
            {
                'commit_sha': sha, 'base_sha': f'real_parent_{sha}',
                'commit_message': f'msg{i}', 'commit_timestamp': f'ts{i}',
                'author_name': 'X', 'author_email': 'x@test.com',
            }
            for i, sha in enumerate(shas)
        ]
        mock_generate.return_value = {'memory_layout': {}}

        run_onboard(self._make_args('a b c'))

        assert mock_upload.call_count == 3
        infos = [c[1]['commit_info'] for c in mock_upload.call_args_list]
        assert infos[0]['base_commit_hash'] is None
        assert infos[1]['base_commit_hash'] == 'aaa111'
        assert infos[2]['base_commit_hash'] == 'bbb222'

    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.generate_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    @patch('membrowse.commands.onboard.subprocess')
    @patch('membrowse.commands.onboard._get_repository_info')
    @patch('membrowse.commands.onboard._resolve_and_validate_commits')
    @patch('membrowse.commands.onboard.os.path.exists', return_value=True)
    def test_faked_parent_ignores_real_git_parent(
        self, mock_exists, mock_resolve, mock_repo, mock_subprocess,
        mock_metadata, mock_generate, mock_upload,
    ):
        """Faked parent chain ignores actual git ancestry."""
        mock_resolve.return_value = ['aaa111', 'bbb222']
        mock_repo.return_value = ('main', 'original_head', 'my-repo')
        mock_subprocess.run.return_value = MagicMock(returncode=0)
        # Real git parent of bbb222 is 'zzz999', not aaa111
        mock_metadata.side_effect = [
            {
                'commit_sha': 'aaa111', 'base_sha': 'xxx888',
                'commit_message': 'm1', 'commit_timestamp': 'ts1',
                'author_name': 'A', 'author_email': 'a@t.com',
            },
            {
                'commit_sha': 'bbb222', 'base_sha': 'zzz999',
                'commit_message': 'm2', 'commit_timestamp': 'ts2',
                'author_name': 'B', 'author_email': 'b@t.com',
            },
        ]
        mock_generate.return_value = {'memory_layout': {}}

        run_onboard(self._make_args('a b'))

        second_info = mock_upload.call_args_list[1][1]['commit_info']
        # Should use faked parent (aaa111), not real parent (zzz999)
        assert second_info['base_commit_hash'] == 'aaa111'


# ---------------------------------------------------------------------------
# Build Loop Behavior with --commits
# ---------------------------------------------------------------------------

class TestCommitsBuildLoop:
    """Test build loop behavior when --commits is used."""

    def _make_args(self, commits_str, build_dirs=None):
        return argparse.Namespace(
            num_commits=None,
            commits=commits_str,
            initial_commit=None,
            build_script='make',
            elf_path='fw.elf',
            target_name='stm32',
            api_key='KEY',
            api_url='https://api.membrowse.com',
            api_url_flag=None,
            ld_scripts=None,
            linker_defs=None,
            build_dirs=build_dirs,
        )

    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.generate_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    @patch('membrowse.commands.onboard._commit_has_changes_in_dirs')
    @patch('membrowse.commands.onboard.subprocess')
    @patch('membrowse.commands.onboard._get_repository_info')
    @patch('membrowse.commands.onboard._resolve_and_validate_commits')
    @patch('membrowse.commands.onboard.os.path.exists', return_value=True)
    def test_build_dirs_skipped_with_commits(
        self, mock_exists, mock_resolve, mock_repo, mock_subprocess,
        mock_changes, mock_metadata, mock_generate, mock_upload,
    ):
        """--build-dirs optimization is skipped when --commits is used."""
        mock_resolve.return_value = ['aaa111', 'bbb222']
        mock_repo.return_value = ('main', 'original_head', 'my-repo')
        mock_subprocess.run.return_value = MagicMock(returncode=0)
        mock_metadata.side_effect = [
            {
                'commit_sha': 'aaa111', 'base_sha': None,
                'commit_message': 'm1', 'commit_timestamp': 'ts1',
                'author_name': 'A', 'author_email': 'a@t.com',
            },
            {
                'commit_sha': 'bbb222', 'base_sha': 'aaa111',
                'commit_message': 'm2', 'commit_timestamp': 'ts2',
                'author_name': 'B', 'author_email': 'b@t.com',
            },
        ]
        mock_generate.return_value = {'memory_layout': {}}

        run_onboard(self._make_args('a b', build_dirs=['src/']))

        # _commit_has_changes_in_dirs should never be called
        mock_changes.assert_not_called()
        # Both commits should be fully built and uploaded
        assert mock_upload.call_count == 2

    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.generate_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    @patch('membrowse.commands.onboard.subprocess')
    @patch('membrowse.commands.onboard._get_repository_info')
    @patch('membrowse.commands.onboard._resolve_and_validate_commits')
    @patch('membrowse.commands.onboard.os.path.exists', return_value=True)
    def test_build_failure_uploads_empty_report(
        self, mock_exists, mock_resolve, mock_repo, mock_subprocess,
        mock_metadata, mock_generate, mock_upload,
    ):
        """Build failure with --commits uploads empty report and stops."""
        mock_resolve.return_value = ['aaa111']
        mock_repo.return_value = ('main', 'original_head', 'my-repo')
        # First subprocess call (checkout) succeeds, second (build) fails
        mock_subprocess.run.side_effect = [
            MagicMock(returncode=0),  # checkout
            MagicMock(returncode=0),  # submodule update
            MagicMock(returncode=0),  # git clean
            MagicMock(returncode=1, stdout='error', stderr=''),  # build fails
            MagicMock(returncode=0),  # restore HEAD
        ]
        mock_metadata.return_value = {
            'commit_sha': 'aaa111', 'base_sha': None,
            'commit_message': 'msg', 'commit_timestamp': 'ts',
            'author_name': 'A', 'author_email': 'a@t.com',
        }

        run_onboard(self._make_args('aaa'))

        # Should upload with build_failed=True
        mock_upload.assert_called_once()
        assert mock_upload.call_args[1]['build_failed'] is True
        # generate_report should NOT be called on build failure
        mock_generate.assert_not_called()

    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.generate_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    @patch('membrowse.commands.onboard.subprocess')
    @patch('membrowse.commands.onboard._get_repository_info')
    @patch('membrowse.commands.onboard._resolve_and_validate_commits')
    @patch('membrowse.commands.onboard.os.path.exists', return_value=True)
    def test_checkout_failure_stops_onboard(
        self, mock_exists, mock_resolve, mock_repo, mock_subprocess,
        mock_metadata, mock_generate, mock_upload,
    ):
        """Checkout failure stops the entire onboard."""
        mock_resolve.return_value = ['aaa111', 'bbb222']
        mock_repo.return_value = ('main', 'original_head', 'my-repo')
        # First checkout fails — should stop immediately
        mock_subprocess.run.side_effect = [
            MagicMock(returncode=1),  # checkout aaa111 fails
            MagicMock(returncode=0),  # restore HEAD (finalize)
        ]

        result = run_onboard(self._make_args('aaa bbb'))

        assert result == 1
        # No commits should be uploaded
        mock_upload.assert_not_called()
        mock_generate.assert_not_called()


# ---------------------------------------------------------------------------
# Upload Payload with --commits
# ---------------------------------------------------------------------------

class TestCommitsUploadPayload:
    """Test that upload payload has correct metadata when using --commits."""

    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.generate_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    @patch('membrowse.commands.onboard.subprocess')
    @patch('membrowse.commands.onboard._get_repository_info')
    @patch('membrowse.commands.onboard._resolve_and_validate_commits')
    @patch('membrowse.commands.onboard.os.path.exists', return_value=True)
    def test_real_metadata_with_faked_parent(
        self, mock_exists, mock_resolve, mock_repo, mock_subprocess,
        mock_metadata, mock_generate, mock_upload,
    ):
        """Upload uses real commit metadata but faked parent."""
        mock_resolve.return_value = ['aaa111', 'bbb222']
        mock_repo.return_value = ('main', 'original_head', 'my-repo')
        mock_subprocess.run.return_value = MagicMock(returncode=0)
        mock_metadata.side_effect = [
            {
                'commit_sha': 'aaa111', 'base_sha': 'real_parent_a',
                'commit_message': 'First commit message',
                'commit_timestamp': '2024-01-01T00:00:00Z',
                'author_name': 'Alice', 'author_email': 'alice@test.com',
            },
            {
                'commit_sha': 'bbb222', 'base_sha': 'real_parent_b',
                'commit_message': 'Second commit message',
                'commit_timestamp': '2024-06-15T12:00:00Z',
                'author_name': 'Bob', 'author_email': 'bob@test.com',
            },
        ]
        mock_generate.return_value = {'memory_layout': {}}

        args = argparse.Namespace(
            num_commits=None, commits='a b', initial_commit=None,
            build_script='make', elf_path='fw.elf', target_name='stm32',
            api_key='KEY', api_url='https://api.membrowse.com',
            api_url_flag=None, ld_scripts=None, linker_defs=None,
            build_dirs=None,
        )
        run_onboard(args)

        second_info = mock_upload.call_args_list[1][1]['commit_info']
        # Real metadata preserved
        assert second_info['commit_hash'] == 'bbb222'
        assert second_info['commit_message'] == 'Second commit message'
        assert second_info['commit_timestamp'] == '2024-06-15T12:00:00Z'
        assert second_info['author_name'] == 'Bob'
        assert second_info['author_email'] == 'bob@test.com'
        # Faked parent
        assert second_info['base_commit_hash'] == 'aaa111'
        # Branch and repo come from repo info
        assert second_info['branch_name'] == 'main'
        assert second_info['repository'] == 'my-repo'
        assert second_info['pr_number'] is None

    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.generate_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    @patch('membrowse.commands.onboard.subprocess')
    @patch('membrowse.commands.onboard._get_repository_info')
    @patch('membrowse.commands.onboard._resolve_and_validate_commits')
    @patch('membrowse.commands.onboard.os.path.exists', return_value=True)
    def test_api_url_flag_used_in_upload(
        self, mock_exists, mock_resolve, mock_repo, mock_subprocess,
        mock_metadata, mock_generate, mock_upload,
    ):
        """--api-url flag value is used in the upload call."""
        mock_resolve.return_value = ['aaa111']
        mock_repo.return_value = ('main', 'original_head', 'my-repo')
        mock_subprocess.run.return_value = MagicMock(returncode=0)
        mock_metadata.return_value = {
            'commit_sha': 'aaa111', 'base_sha': None,
            'commit_message': 'msg', 'commit_timestamp': 'ts',
            'author_name': 'A', 'author_email': 'a@t.com',
        }
        mock_generate.return_value = {'memory_layout': {}}

        args = argparse.Namespace(
            num_commits=None, commits='aaa', initial_commit=None,
            build_script='make', elf_path='fw.elf', target_name='stm32',
            api_key='KEY', api_url='https://api.membrowse.com',
            api_url_flag='https://custom.example.com',
            ld_scripts=None, linker_defs=None, build_dirs=None,
        )
        run_onboard(args)

        assert mock_upload.call_args[1]['api_url'] == 'https://custom.example.com'

    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.generate_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    @patch('membrowse.commands.onboard.subprocess')
    @patch('membrowse.commands.onboard._get_repository_info')
    @patch('membrowse.commands.onboard._get_commit_list')
    @patch('membrowse.commands.onboard.os.path.exists', return_value=True)
    def test_api_url_flag_overrides_positional_in_num_commits_mode(
        self, mock_exists, mock_commit_list, mock_repo, mock_subprocess,
        mock_metadata, mock_generate, mock_upload,
    ):
        """--api-url flag takes precedence over positional api_url in num_commits mode."""
        mock_commit_list.return_value = ['aaa111']
        mock_repo.return_value = ('main', 'original_head', 'my-repo')
        mock_subprocess.run.return_value = MagicMock(returncode=0)
        mock_metadata.return_value = {
            'commit_sha': 'aaa111', 'base_sha': None,
            'commit_message': 'msg', 'commit_timestamp': 'ts',
            'author_name': 'A', 'author_email': 'a@t.com',
        }
        mock_generate.return_value = {'memory_layout': {}}

        args = argparse.Namespace(
            num_commits=1, commits=None, initial_commit=None,
            build_script='make', elf_path='fw.elf', target_name='stm32',
            api_key='KEY', api_url='https://positional.example.com',
            api_url_flag='https://flag.example.com',
            ld_scripts=None, linker_defs=None, build_dirs=None,
        )
        run_onboard(args)

        assert mock_upload.call_args[1]['api_url'] == 'https://flag.example.com'


# ---------------------------------------------------------------------------
# Validation Before Loop
# ---------------------------------------------------------------------------

class TestCommitsUpfrontValidation:
    """Test that commit refs are validated before starting the build loop."""

    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.subprocess')
    @patch('membrowse.commands.onboard._get_repository_info')
    @patch('membrowse.commands.onboard._resolve_and_validate_commits')
    def test_invalid_refs_fail_before_any_build(
        self, mock_resolve, mock_repo, mock_subprocess, mock_upload,
    ):
        """Invalid refs cause early exit before any checkout or build."""
        mock_repo.return_value = ('main', 'original_head', 'my-repo')
        mock_resolve.side_effect = ValueError("Cannot resolve: bad_tag")

        args = argparse.Namespace(
            num_commits=None, commits='bad_tag', initial_commit=None,
            build_script='make', elf_path='fw.elf', target_name='stm32',
            api_key='KEY', api_url='https://api.membrowse.com',
            api_url_flag=None, ld_scripts=None, linker_defs=None,
            build_dirs=None,
        )
        result = run_onboard(args)

        assert result == 1
        # No checkout or build should have happened
        mock_subprocess.run.assert_not_called()
        mock_upload.assert_not_called()


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------

class TestCommitsEdgeCases:
    """Test edge cases for --commits."""

    @patch('membrowse.commands.onboard.run_git_command')
    def test_duplicate_commits_resolved(self, mock_git):
        """Duplicate commits in list are resolved individually."""
        mock_git.return_value = 'aaa111'
        result = _resolve_and_validate_commits('aaa aaa')
        assert result == ['aaa111', 'aaa111']
        assert mock_git.call_count == 2

    @patch('membrowse.commands.onboard.run_git_command')
    def test_annotated_tag_dereferenced(self, mock_git):
        """Annotated tag is dereferenced via ^{commit} syntax."""
        mock_git.return_value = 'abc123'
        _resolve_and_validate_commits('v1.0')
        mock_git.assert_called_once_with(
            ['rev-parse', '--verify', 'v1.0^{commit}'])

    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.generate_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    @patch('membrowse.commands.onboard.subprocess')
    @patch('membrowse.commands.onboard._get_repository_info')
    @patch('membrowse.commands.onboard._resolve_and_validate_commits')
    @patch('membrowse.commands.onboard.os.path.exists', return_value=True)
    def test_submodule_update_called_after_checkout(
        self, mock_exists, mock_resolve, mock_repo, mock_subprocess,
        mock_metadata, mock_generate, mock_upload,
    ):
        """git submodule update --init --recursive is called after checkout."""
        mock_resolve.return_value = ['aaa111']
        mock_repo.return_value = ('main', 'original_head', 'my-repo')
        mock_subprocess.run.return_value = MagicMock(returncode=0)
        mock_metadata.return_value = {
            'commit_sha': 'aaa111', 'base_sha': None,
            'commit_message': 'msg', 'commit_timestamp': 'ts',
            'author_name': 'A', 'author_email': 'a@t.com',
        }
        mock_generate.return_value = {'memory_layout': {}}

        args = argparse.Namespace(
            num_commits=None, commits='aaa', initial_commit=None,
            build_script='make', elf_path='fw.elf', target_name='stm32',
            api_key='KEY', api_url='https://api.membrowse.com',
            api_url_flag=None, ld_scripts=None, linker_defs=None,
            build_dirs=None,
        )
        run_onboard(args)

        # Find the submodule update call among subprocess.run calls
        calls = mock_subprocess.run.call_args_list
        submodule_calls = [
            c for c in calls
            if 'submodule' in str(c)
        ]
        assert len(submodule_calls) == 1
        sub_args = submodule_calls[0][0][0]
        assert sub_args == [
            'git', 'submodule', 'update', '--init', '--recursive', '--quiet'
        ]

        # Verify ordering: checkout before submodule update
        checkout_idx = next(
            i for i, c in enumerate(calls) if 'checkout' in str(c) and 'aaa111' in str(c)
        )
        submodule_idx = next(
            i for i, c in enumerate(calls) if 'submodule' in str(c)
        )
        assert checkout_idx < submodule_idx
