"""Tests for onboard's forced checkout and its working-tree guard.

A build can rewrite a tracked file, e.g. cargo bringing a stale Cargo.lock up
to date. A plain checkout then refuses to move to a commit that also changes
that file, and every later commit is lost. Checkouts are forced, so onboard
refuses to start when the user has uncommitted edits it would discard.
"""

import logging
import os
import subprocess
from unittest.mock import patch

import pytest

from membrowse.commands.onboard import _CI_ENV_MARKERS, _check_working_tree
from membrowse.utils.git import git_checkout, git_modified_tracked_files

pytestmark = pytest.mark.real_working_tree_check


def _git(cwd, *args):
    result = subprocess.run(
        ['git', *args],
        cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture(autouse=True)
def _isolated_git(monkeypatch):
    """Keep the user's git config (signing, hooks) out of the test repos."""
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')


@pytest.fixture()
def not_ci(monkeypatch):
    """Clear every variable that makes onboard think it runs in CI."""
    for name in ('CI', *_CI_ENV_MARKERS):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """Repo with commits A and B; B changes Cargo.lock. Checked out at A."""
    _git(tmp_path, 'init', '-q')
    _git(tmp_path, 'config', 'user.email', 'test@test.com')
    _git(tmp_path, 'config', 'user.name', 'Test')
    (tmp_path / 'Cargo.lock').write_text('version = "7.1.0"\n')
    (tmp_path / 'main.c').write_text('int main(void) { return 0; }\n')
    _git(tmp_path, 'add', '-A')
    _git(tmp_path, 'commit', '-q', '-m', 'A')
    commit_a = _git(tmp_path, 'rev-parse', 'HEAD')
    (tmp_path / 'Cargo.lock').write_text('version = "7.2.0"\n')
    _git(tmp_path, 'commit', '-q', '-am', 'B')
    commit_b = _git(tmp_path, 'rev-parse', 'HEAD')
    _git(tmp_path, 'checkout', '-q', commit_a)
    monkeypatch.chdir(tmp_path)
    return tmp_path, commit_a, commit_b


class TestForcedCheckout:
    """git_checkout must not be blocked by files a build rewrote."""

    def test_checkout_overwrites_file_the_build_rewrote(self, repo):  # pylint: disable=redefined-outer-name
        """The cargo lockfile case: build edits a file the next commit changes."""
        path, _, commit_b = repo
        (path / 'Cargo.lock').write_text('version = "7.2.0-rewritten"\n')

        git_checkout(commit_b)

        assert _git(path, 'rev-parse', 'HEAD') == commit_b
        assert (path / 'Cargo.lock').read_text() == 'version = "7.2.0"\n'
        assert git_modified_tracked_files() == []

    def test_checkout_of_unknown_ref_still_fails(self, repo):  # pylint: disable=redefined-outer-name,unused-argument
        """Forcing must not hide a bad ref."""
        with pytest.raises(RuntimeError):
            git_checkout('does-not-exist')


class TestModifiedTrackedFiles:
    """git_modified_tracked_files lists only tracked changes."""

    def test_clean_tree(self, repo):  # pylint: disable=redefined-outer-name,unused-argument
        """A fresh checkout has nothing to report."""
        assert git_modified_tracked_files() == []

    def test_lists_unstaged_and_staged_changes(self, repo):  # pylint: disable=redefined-outer-name
        """Both an unstaged and a staged edit are listed, with full paths."""
        path, _, _ = repo
        (path / 'Cargo.lock').write_text('edited\n')
        (path / 'main.c').write_text('edited\n')
        _git(path, 'add', 'main.c')

        assert sorted(git_modified_tracked_files()) == ['Cargo.lock', 'main.c']

    def test_lists_both_sides_of_a_rename(self, repo):  # pylint: disable=redefined-outer-name
        """A staged rename lists plain paths, not 'old -> new'."""
        path, _, _ = repo
        _git(path, 'mv', 'main.c', 'app.c')

        assert sorted(git_modified_tracked_files()) == ['app.c', 'main.c']

    def test_non_ascii_path_is_not_quoted(self, repo):  # pylint: disable=redefined-outer-name
        """Paths come back as written, not C-quoted with octal escapes."""
        path, _, _ = repo
        (path / 'café.c').write_text('int x;\n')
        _git(path, 'add', 'café.c')
        _git(path, 'commit', '-q', '-m', 'add')
        (path / 'café.c').write_text('int y;\n')

        assert git_modified_tracked_files() == ['café.c']

    def test_lists_moved_submodule(self, repo, tmp_path):  # pylint: disable=redefined-outer-name
        """A submodule moved off its recorded commit would be reset, so list it."""
        path, _, _ = repo
        sub_src = tmp_path.parent / f'{tmp_path.name}-sub'
        sub_src.mkdir()
        _git(sub_src, 'init', '-q')
        _git(sub_src, 'config', 'user.email', 'test@test.com')
        _git(sub_src, 'config', 'user.name', 'Test')
        (sub_src / 'lib.c').write_text('v1\n')
        _git(sub_src, 'add', '-A')
        _git(sub_src, 'commit', '-q', '-m', 'v1')
        _git(path, '-c', 'protocol.file.allow=always', 'submodule', 'add', '-q',
             str(sub_src), 'lib')
        _git(path, 'commit', '-q', '-m', 'add submodule')
        assert git_modified_tracked_files() == []

        (path / 'lib' / 'lib.c').write_text('v2\n')
        _git(path / 'lib', '-c', 'user.email=test@test.com', '-c', 'user.name=Test',
             'commit', '-q', '-am', 'v2')

        assert git_modified_tracked_files() == ['lib']

    def test_ignores_untracked_files(self, repo):  # pylint: disable=redefined-outer-name
        """Untracked files are git_clean's business, not a blocker."""
        path, _, _ = repo
        (path / 'build.log').write_text('output\n')

        assert git_modified_tracked_files() == []

    def test_none_outside_a_repository(self, tmp_path, monkeypatch):
        """git status failing is reported as None, not as a clean tree."""
        outside = tmp_path / 'not-a-repo'
        outside.mkdir()
        monkeypatch.chdir(outside)
        monkeypatch.setenv('GIT_CEILING_DIRECTORIES', str(tmp_path))

        assert git_modified_tracked_files() is None


class TestCheckWorkingTree:
    """_check_working_tree protects local work but doesn't block CI."""

    def test_clean_tree_proceeds(self, repo, not_ci):  # pylint: disable=redefined-outer-name,unused-argument
        """Nothing to lose, so onboard may start."""
        assert _check_working_tree() is True

    def test_local_changes_block_outside_ci(self, repo, not_ci, caplog):  # pylint: disable=redefined-outer-name,unused-argument
        """Uncommitted edits on a developer machine stop onboard."""
        path, _, _ = repo
        (path / 'main.c').write_text('work in progress\n')

        with caplog.at_level(logging.ERROR):
            assert _check_working_tree() is False
        assert 'main.c' in caplog.text
        assert (path / 'main.c').read_text() == 'work in progress\n'

    @pytest.mark.parametrize('ci_value', ['true', '1', 'True'])
    def test_local_changes_warn_in_ci(self, repo, not_ci, monkeypatch, caplog, ci_value):  # pylint: disable=redefined-outer-name,unused-argument,too-many-arguments,too-many-positional-arguments
        """In CI the checkout is disposable: warn and carry on."""
        path, _, _ = repo
        monkeypatch.setenv('CI', ci_value)
        (path / 'main.c').write_text('patched by setup step\n')

        with caplog.at_level(logging.WARNING):
            assert _check_working_tree() is True
        assert 'main.c' in caplog.text

    @pytest.mark.parametrize('marker', _CI_ENV_MARKERS)
    def test_ci_without_ci_variable_warns(self, repo, not_ci, monkeypatch, marker):  # pylint: disable=redefined-outer-name,unused-argument
        """Jenkins, Azure Pipelines and TeamCity don't set CI by default."""
        path, _, _ = repo
        monkeypatch.setenv(marker, 'True')
        (path / 'main.c').write_text('patched by setup step\n')

        assert _check_working_tree() is True

    @pytest.mark.parametrize('ci_value', ['', '0', 'false'])
    def test_ci_disabled_values_still_block(self, repo, not_ci, monkeypatch, ci_value):  # pylint: disable=redefined-outer-name,unused-argument
        """CI set to an off value counts as a local run."""
        path, _, _ = repo
        monkeypatch.setenv('CI', ci_value)
        (path / 'main.c').write_text('work in progress\n')

        assert _check_working_tree() is False

    def test_long_listing_is_truncated(self, not_ci, caplog):  # pylint: disable=redefined-outer-name,unused-argument
        """Many changed files are summarised, not dumped."""
        files = [f'src/file{i}.c' for i in range(25)]
        with patch('membrowse.commands.onboard.git_modified_tracked_files',
                   return_value=files), caplog.at_level(logging.ERROR):
            assert _check_working_tree() is False
        assert 'src/file9.c' in caplog.text
        assert 'src/file10.c' not in caplog.text
        assert 'and 15 more' in caplog.text

    def test_git_status_failure_blocks(self, monkeypatch):
        """If the tree can't be checked, don't risk discarding work."""
        monkeypatch.setenv('CI', 'true')
        with patch('membrowse.commands.onboard.git_modified_tracked_files',
                   return_value=None):
            assert _check_working_tree() is False
