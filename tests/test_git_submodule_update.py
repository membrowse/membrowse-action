"""Tests for submodule handling between onboard commits.

Builds a real superproject with one submodule whose gitlink changes between
two commits, then simulates a build that patched the submodule's working tree.
"""

import os
import subprocess

import pytest

from membrowse.utils.git import git_checkout, git_clean, git_submodule_update


def _git(cwd, *args):
    result = subprocess.run(
        ['git', *args],
        cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture()
def super_repo(tmp_path, monkeypatch):
    """Superproject with commits A and B; B bumps the submodule to a commit
    that changes lib.c."""
    monkeypatch.setenv('GIT_CONFIG_COUNT', '1')
    monkeypatch.setenv('GIT_CONFIG_KEY_0', 'protocol.file.allow')
    monkeypatch.setenv('GIT_CONFIG_VALUE_0', 'always')

    lib = tmp_path / 'lib'
    lib.mkdir()
    _git(lib, 'init', '-q')
    _git(lib, 'config', 'user.email', 'test@test.com')
    _git(lib, 'config', 'user.name', 'Test')
    (lib / 'lib.c').write_text('int v = 1;\n')
    _git(lib, 'add', '-A')
    _git(lib, 'commit', '-q', '-m', 'lib v1')
    lib_v1 = _git(lib, 'rev-parse', 'HEAD')
    (lib / 'lib.c').write_text('int v = 2;\n')
    _git(lib, 'commit', '-q', '-am', 'lib v2')
    lib_v2 = _git(lib, 'rev-parse', 'HEAD')

    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init', '-q')
    _git(repo, 'config', 'user.email', 'test@test.com')
    _git(repo, 'config', 'user.name', 'Test')
    _git(repo, 'submodule', 'add', '-q', str(lib), 'lib')
    _git(repo / 'lib', 'checkout', '-q', lib_v1)
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-q', '-m', 'A')
    commit_a = _git(repo, 'rev-parse', 'HEAD')
    _git(repo / 'lib', 'checkout', '-q', lib_v2)
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-q', '-m', 'B: bump lib')
    commit_b = _git(repo, 'rev-parse', 'HEAD')

    _git(repo, 'checkout', '-q', commit_a)
    _git(repo, 'submodule', 'update', '-q', '--init', '--recursive')

    monkeypatch.chdir(repo)
    return repo, commit_b, lib_v2


class TestSubmoduleUpdate:
    """Moving between commits must leave submodules at the recorded revision."""

    def test_patched_submodule_is_moved_to_new_revision(self, super_repo):  # pylint: disable=redefined-outer-name
        """A build-time patch to a file the next gitlink changes must not
        block the submodule checkout."""
        repo, commit_b, lib_v2 = super_repo
        (repo / 'lib' / 'lib.c').write_text('int v = 1; /* patched */\n')

        git_checkout(commit_b)
        git_submodule_update()

        assert _git(repo / 'lib', 'rev-parse', 'HEAD') == lib_v2
        assert (repo / 'lib' / 'lib.c').read_text() == 'int v = 2;\n'

    def test_clean_removes_untracked_files_in_submodules(self, super_repo):  # pylint: disable=redefined-outer-name
        """Files a patch added inside a submodule must not survive the clean."""
        repo, _, _ = super_repo
        added = repo / 'lib' / 'added_by_patch.c'
        added.write_text('int extra;\n')

        git_clean()

        assert not added.exists()
        assert os.path.exists(repo / 'lib' / 'lib.c')
