"""Tests for binary search onboard mode."""

import argparse
from unittest.mock import patch

from membrowse.commands.onboard import (
    _extract_fingerprint,
    _binary_search_range,
    _run_binary_search_onboard,
    run_onboard,
)


# --- Helpers ---

def _make_report(layout=None):
    """Create a report dict with the given memory_layout."""
    return {
        'file_path': 'firmware.elf',
        'architecture': 'arm',
        'entry_point': 0x8000,
        'file_type': 'ET_EXEC',
        'machine': 'ARM',
        'symbols': [],
        'program_headers': [],
        'memory_layout': layout or {},
    }


def _make_layout(flash_used=1000, ram_used=500):
    """Create a simple memory_layout dict."""
    return {
        'FLASH': {
            'address': 0x08000000,
            'limit_size': 65536,
            'type': 'ROM',
            'used_size': flash_used,
            'free_size': 65536 - flash_used,
            'utilization_percent': flash_used / 65536 * 100,
            'sections': [],
        },
        'RAM': {
            'address': 0x20000000,
            'limit_size': 32768,
            'type': 'RAM',
            'used_size': ram_used,
            'free_size': 32768 - ram_used,
            'utilization_percent': ram_used / 32768 * 100,
            'sections': [],
        },
    }


def _make_args(**overrides):
    """Create a minimal args namespace for onboard."""
    defaults = {
        'num_commits': 5,
        'build_script': 'make',
        'elf_path': 'build/firmware.elf',
        'target_name': 'stm32f4',
        'api_key': 'test-key',
        'api_url': 'https://api.membrowse.com',
        'ld_scripts': None,
        'linker_defs': None,
        'build_dirs': None,
        'initial_commit': None,
        'binary_search': False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _make_commit_metadata(sha):
    """Create commit metadata for a given SHA."""
    return {
        'commit_sha': sha,
        'parent_sha': sha + '_parent',
        'commit_message': f'commit {sha[:8]}',
        'commit_timestamp': '2026-01-01T00:00:00Z',
        'author_name': 'Test',
        'author_email': 'test@test.com',
    }


def _get_upload_commit_hashes(mock_upload):
    """Extract commit hashes from upload_report call args in order."""
    return [
        call.kwargs['commit_info']['commit_hash']
        for call in mock_upload.call_args_list
    ]


# --- Fingerprint tests ---

class TestExtractFingerprint:
    """Tests for _extract_fingerprint helper."""

    def test_basic_fingerprint(self):
        """Extracts sorted region-name/used-size tuples."""
        report = _make_report(_make_layout(flash_used=1000, ram_used=500))
        fp = _extract_fingerprint(report)
        assert fp == (('FLASH', 1000), ('RAM', 500))

    def test_empty_layout(self):
        """Empty layout returns empty tuple."""
        report = _make_report({})
        fp = _extract_fingerprint(report)
        assert not fp

    def test_missing_layout_key(self):
        """Missing memory_layout key returns empty tuple."""
        report = {'file_path': 'test.elf'}
        fp = _extract_fingerprint(report)
        assert not fp

    def test_ignores_address_changes(self):
        """Two reports with same used_size but different addresses are identical."""
        layout1 = _make_layout(flash_used=2000, ram_used=800)
        layout2 = _make_layout(flash_used=2000, ram_used=800)
        # Change addresses
        layout2['FLASH']['address'] = 0x00000000
        layout2['RAM']['address'] = 0x10000000
        assert _extract_fingerprint(_make_report(layout1)) == \
               _extract_fingerprint(_make_report(layout2))

    def test_different_used_size_differs(self):
        """Different used_size produces different fingerprints."""
        fp1 = _extract_fingerprint(_make_report(_make_layout(flash_used=1000)))
        fp2 = _extract_fingerprint(_make_report(_make_layout(flash_used=1001)))
        assert fp1 != fp2

    def test_sorted_by_region_name(self):
        """Regions are sorted alphabetically by name."""
        layout = {
            'ZZZ': {'used_size': 100},
            'AAA': {'used_size': 200},
        }
        fp = _extract_fingerprint(_make_report(layout))
        assert fp == (('AAA', 200), ('ZZZ', 100))


# --- Binary search range tests ---

class TestBinarySearchRange:
    """Tests for _binary_search_range recursive function."""

    def test_adjacent_indices_noop(self):
        """right_idx - left_idx <= 1 does nothing."""
        commit_results = {}
        flush_called = []
        commits = ['aaa', 'bbb']
        result = _binary_search_range(
            commits, 0, 1,
            (('FLASH', 100),), (('FLASH', 100),),
            {0, 1}, set(), {}, commit_results,
            _make_args(), {}, lambda: flush_called.append(True))
        assert result is True
        assert not commit_results
        assert not flush_called

    def test_identical_range_marks_all_identical(self):
        """When fingerprints match, all intermediate commits are stored as identical."""
        commit_results = {}
        flush_called = []

        commits = ['c0', 'c1', 'c2', 'c3', 'c4']
        fp = (('FLASH', 1000), ('RAM', 500))

        result = _binary_search_range(
            commits, 0, 4,
            fp, fp,
            {0, 4}, set(), {}, commit_results,
            _make_args(), {}, lambda: flush_called.append(True))

        assert result is True
        # c1, c2, c3 should be in commit_results as identical
        for i in [1, 2, 3]:
            assert i in commit_results
            _report, build_failed, identical = commit_results[i]
            assert identical is True
            assert build_failed is False
        assert len(flush_called) == 1

    @patch('membrowse.commands.onboard._build_and_generate_report')
    def test_different_endpoints_builds_midpoint(self, mock_build):
        """When endpoints differ, the midpoint is built."""
        # All builds return same report (so recursion finds them identical)
        mid_report = _make_report(_make_layout(flash_used=1500))
        mock_build.return_value = (mid_report, False)

        commit_results = {}
        commits = ['c0', 'c1', 'c2', 'c3', 'c4']
        fp_left = (('FLASH', 1000), ('RAM', 500))
        fp_right = (('FLASH', 2000), ('RAM', 500))

        _binary_search_range(
            commits, 0, 4,
            fp_left, fp_right,
            {0, 4}, set(), {}, commit_results,
            _make_args(), {}, lambda: None)

        # Midpoint (index 2) should have been built
        mock_build.assert_called()
        build_commits = [call[0][0] for call in mock_build.call_args_list]
        assert 'c2' in build_commits

    @patch('membrowse.commands.onboard._build_and_generate_report')
    def test_build_failure_continues_binary_search(self, mock_build):
        """When midpoint build fails, continues binary search with None fingerprint."""
        failed_report = _make_report({})
        success_report = _make_report(_make_layout(flash_used=1000))

        def build_side_effect(commit, _args, _linker_vars):
            if commit == 'c2':
                return failed_report, True
            return success_report, False

        mock_build.side_effect = build_side_effect

        commit_results = {}
        failed_indices = set()
        commits = ['c0', 'c1', 'c2', 'c3', 'c4']

        result = _binary_search_range(
            commits, 0, 4,
            (('FLASH', 1000),), (('FLASH', 2000),),
            {0, 4}, failed_indices, {}, commit_results,
            _make_args(), {}, lambda: None)

        assert result is True
        # All intermediate commits should have results (c1, c2, c3)
        assert 1 in commit_results
        assert 2 in commit_results
        assert 3 in commit_results
        # c2 should be marked as build_failed
        assert commit_results[2][1] is True
        # c2 should be in failed_indices
        assert 2 in failed_indices


class TestRunBinarySearchOnboard:
    """Tests for _run_binary_search_onboard orchestrator."""

    @patch('membrowse.commands.onboard._build_and_generate_report')
    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    def test_single_commit(self, mock_metadata, mock_upload, mock_build):
        """N=1: builds and uploads the single commit."""
        mock_metadata.side_effect = _make_commit_metadata
        mock_upload.return_value = ({"status": "success"}, "")
        mock_build.return_value = (_make_report(_make_layout()), False)

        success, failed = _run_binary_search_onboard(
            _make_args(), ['abc123'], 'main', 'repo', {})

        assert success == 1
        assert failed == 0
        mock_build.assert_called_once_with('abc123', _make_args(), {})

    @patch('membrowse.commands.onboard._build_and_generate_report')
    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    def test_two_commits(self, mock_metadata, mock_upload, mock_build):
        """N=2: builds both endpoints, no recursion."""
        mock_metadata.side_effect = _make_commit_metadata
        mock_upload.return_value = ({"status": "success"}, "")
        mock_build.return_value = (_make_report(_make_layout()), False)

        success, failed = _run_binary_search_onboard(
            _make_args(), ['aaa', 'bbb'], 'main', 'repo', {})

        assert success == 2
        assert failed == 0
        assert mock_build.call_count == 2

    @patch('membrowse.commands.onboard._build_and_generate_report')
    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    def test_two_commits_identical_dedup(self, mock_metadata, mock_upload, mock_build):
        """N=2 with same fingerprint: second is uploaded as identical."""
        mock_metadata.side_effect = _make_commit_metadata
        mock_upload.return_value = ({"status": "success"}, "")
        mock_build.return_value = (_make_report(_make_layout()), False)

        success, failed = _run_binary_search_onboard(
            _make_args(), ['aaa', 'bbb'], 'main', 'repo', {})

        assert success == 2
        assert failed == 0
        # Second upload should be identical (same fingerprint as first)
        assert mock_upload.call_args_list[1].kwargs.get('identical') is True

    @patch('membrowse.commands.onboard._build_and_generate_report')
    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    def test_all_identical(self, mock_metadata, mock_upload, mock_build):
        """All commits have same fingerprint: only 2 builds, rest marked identical."""
        mock_metadata.side_effect = _make_commit_metadata
        mock_upload.return_value = ({"status": "success"}, "")
        report = _make_report(_make_layout(flash_used=1000, ram_used=500))
        mock_build.return_value = (report, False)

        commits = [f'c{i}' for i in range(10)]
        success, failed = _run_binary_search_onboard(
            _make_args(), commits, 'main', 'repo', {})

        assert failed == 0
        assert success == 10  # 2 built + 8 identical
        assert mock_build.call_count == 2  # Only endpoints built
        # All uploads should be in chronological order
        upload_hashes = _get_upload_commit_hashes(mock_upload)
        assert upload_hashes == [f'c{i}' for i in range(10)]
        # HEAD (c9) must be the last upload
        assert upload_hashes[-1] == 'c9'
        # All uploads except c0 should be identical (fingerprint dedup)
        for call in mock_upload.call_args_list[1:]:
            assert call.kwargs.get('identical') is True

    @patch('membrowse.commands.onboard._build_and_generate_report')
    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    def test_change_in_middle(self, mock_metadata, mock_upload, mock_build):
        """Change at midpoint: verifies correct recursion and chronological upload."""
        mock_metadata.side_effect = _make_commit_metadata
        mock_upload.return_value = ({"status": "success"}, "")

        # Commits: c0..c4. c0-c1 have layout A, c2-c4 have layout B.
        layout_a = _make_layout(flash_used=1000)
        layout_b = _make_layout(flash_used=2000)
        report_a = _make_report(layout_a)
        report_b = _make_report(layout_b)

        def build_side_effect(commit, _args, _linker_vars):
            if commit in ('c0', 'c1'):
                return report_a, False
            return report_b, False

        mock_build.side_effect = build_side_effect

        commits = ['c0', 'c1', 'c2', 'c3', 'c4']
        success, failed = _run_binary_search_onboard(
            _make_args(), commits, 'main', 'repo', {})

        assert failed == 0
        assert success == 5
        # Should build fewer than 5 commits (binary search saves some)
        assert mock_build.call_count < 5
        # Uploads must be in chronological order
        upload_hashes = _get_upload_commit_hashes(mock_upload)
        assert upload_hashes == ['c0', 'c1', 'c2', 'c3', 'c4']

    @patch('membrowse.commands.onboard._build_and_generate_report')
    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    def test_failed_endpoint_uses_binary_search(self, mock_metadata,
                                                mock_upload, mock_build):
        """When an endpoint build fails, binary search finds the boundary."""
        mock_metadata.side_effect = _make_commit_metadata
        mock_upload.return_value = ({"status": "success"}, "")

        success_report = _make_report(_make_layout(flash_used=1000))

        # c0 succeeds, c4 fails, intermediates succeed
        def build_side_effect(commit, _args, _linker_vars):
            if commit == 'c4':
                return _make_report({}), True
            return success_report, False

        mock_build.side_effect = build_side_effect

        commits = ['c0', 'c1', 'c2', 'c3', 'c4']
        success, failed = _run_binary_search_onboard(
            _make_args(), commits, 'main', 'repo', {})

        assert failed == 0
        assert success == 5
        # Binary search should build fewer than 5 (c1 identical to c0/c2)
        assert mock_build.call_count < 5
        # Uploads must be in chronological order
        upload_hashes = _get_upload_commit_hashes(mock_upload)
        assert upload_hashes == ['c0', 'c1', 'c2', 'c3', 'c4']

    @patch('membrowse.commands.onboard._build_and_generate_report')
    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    def test_three_groups_chronological(self, mock_metadata, mock_upload, mock_build):  # pylint: disable=too-many-locals
        """10 commits in 3 groups: only change-point commits get full uploads."""
        mock_metadata.side_effect = _make_commit_metadata
        mock_upload.return_value = ({"status": "success"}, "")

        # c0-c2: fingerprint A, c3-c6: fingerprint B, c7-c9: fingerprint C
        layout_a = _make_layout(flash_used=1000, ram_used=500)
        layout_b = _make_layout(flash_used=2000, ram_used=500)
        layout_c = _make_layout(flash_used=3000, ram_used=500)
        report_a = _make_report(layout_a)
        report_b = _make_report(layout_b)
        report_c = _make_report(layout_c)

        def build_side_effect(commit, _args, _linker_vars):
            idx = int(commit[1:])  # "c3" -> 3
            if idx <= 2:
                return report_a, False
            if idx <= 6:
                return report_b, False
            return report_c, False

        mock_build.side_effect = build_side_effect

        commits = [f'c{i}' for i in range(10)]
        success, failed = _run_binary_search_onboard(
            _make_args(), commits, 'main', 'repo', {})

        assert failed == 0
        assert success == 10

        # Uploads must be in chronological order
        upload_hashes = _get_upload_commit_hashes(mock_upload)
        assert upload_hashes == [f'c{i}' for i in range(10)]

        # Only change-point commits should be full (non-identical) uploads:
        # c0 (first), c3 (A->B change), c7 (B->C change)
        full_uploads = []
        identical_uploads = []
        for call in mock_upload.call_args_list:
            sha = call.kwargs['commit_info']['commit_hash']
            if call.kwargs.get('identical'):
                identical_uploads.append(sha)
            else:
                full_uploads.append(sha)

        assert 'c0' in full_uploads
        assert 'c3' in full_uploads
        assert 'c7' in full_uploads
        assert len(full_uploads) == 3
        assert len(identical_uploads) == 7


    @patch('membrowse.commands.onboard._build_and_generate_report')
    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    def test_both_endpoints_fail_marks_intermediates_failed(self, mock_metadata,
                                                            mock_upload, mock_build):
        """When both endpoints fail, intermediates are marked as build_failed."""
        mock_metadata.side_effect = _make_commit_metadata
        mock_upload.return_value = ({"status": "success"}, "")

        mock_build.return_value = (_make_report({}), True)  # All builds fail

        commits = ['c0', 'c1', 'c2', 'c3', 'c4']
        success, failed = _run_binary_search_onboard(
            _make_args(), commits, 'main', 'repo', {})

        assert failed == 0
        assert success == 5
        # Only endpoints built (both None fingerprint -> intermediates marked failed)
        assert mock_build.call_count == 2
        # All uploads should have build_failed=True
        for call in mock_upload.call_args_list:
            assert call.kwargs.get('build_failed') is True

    @patch('membrowse.commands.onboard._build_and_generate_report')
    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    def test_failure_boundary_detection(self, mock_metadata, mock_upload,
                                        mock_build):
        """Binary search finds where builds start and stop failing."""
        mock_metadata.side_effect = _make_commit_metadata
        mock_upload.return_value = ({"status": "success"}, "")

        # c0,c1 succeed (fp A), c2,c3 fail, c4 succeeds (fp B)
        # Different endpoints force recursion, which discovers the failures
        def build_side_effect(commit, _args, _linker_vars):
            idx = int(commit[1:])
            if idx in (2, 3):
                return _make_report({}), True
            if idx == 4:
                return _make_report(_make_layout(flash_used=2000)), False
            return _make_report(_make_layout(flash_used=1000)), False

        mock_build.side_effect = build_side_effect

        commits = ['c0', 'c1', 'c2', 'c3', 'c4']
        success, failed = _run_binary_search_onboard(
            _make_args(), commits, 'main', 'repo', {})

        assert failed == 0
        assert success == 5
        # Uploads must be in chronological order
        upload_hashes = _get_upload_commit_hashes(mock_upload)
        assert upload_hashes == ['c0', 'c1', 'c2', 'c3', 'c4']
        # c2 and c3 should be build_failed
        for call in mock_upload.call_args_list:
            sha = call.kwargs['commit_info']['commit_hash']
            if sha in ('c2', 'c3'):
                assert call.kwargs.get('build_failed') is True, \
                    f"{sha} should be build_failed"
            else:
                assert not call.kwargs.get('build_failed'), \
                    f"{sha} should not be build_failed"


    @patch('membrowse.commands.onboard._build_and_generate_report')
    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    def test_no_identical_after_build_failed(
            self, mock_metadata, mock_upload, mock_build):
        """After a build_failed upload, the next commit must not be
        deduped to identical even if its fingerprint matches a prior
        successful commit. This prevents the API from rejecting
        identical reports whose parent is build_failed."""
        mock_metadata.side_effect = _make_commit_metadata
        mock_upload.return_value = ({"status": "success"}, "")

        # c0: fp X (1000), c4: fp Y (2000) — different endpoints force
        # binary search. c2 fails. c1,c3 succeed with fp X (same as c0).
        # Without the fix, flush dedup would mark c3 identical because
        # prev_fingerprint=X persists across c2's build_failed.
        def build_side_effect(commit, _args, _linker_vars):
            idx = int(commit[1:])
            if idx == 2:
                return _make_report({}), True  # c2 fails
            if idx == 4:
                return _make_report(_make_layout(flash_used=2000)), False
            return _make_report(_make_layout(flash_used=1000)), False

        mock_build.side_effect = build_side_effect

        commits = ['c0', 'c1', 'c2', 'c3', 'c4']
        success, failed = _run_binary_search_onboard(
            _make_args(), commits, 'main', 'repo', {})

        assert failed == 0
        assert success == 5
        upload_hashes = _get_upload_commit_hashes(mock_upload)
        assert upload_hashes == ['c0', 'c1', 'c2', 'c3', 'c4']

        for call in mock_upload.call_args_list:
            sha = call.kwargs['commit_info']['commit_hash']
            if sha == 'c2':
                assert call.kwargs.get('build_failed') is True, \
                    "c2 should be build_failed"
            elif sha == 'c3':
                # Key assertion: c3 must NOT be identical (parent c2 is
                # build_failed). It should upload as a regular report.
                assert not call.kwargs.get('identical'), \
                    "c3 must not be identical after build_failed parent"
                assert not call.kwargs.get('build_failed'), \
                    "c3 built successfully and should not be build_failed"


class TestDryRun:
    """Test --dry-run mode."""

    @patch('membrowse.commands.onboard._build_and_generate_report')
    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    def test_dry_run_skips_upload(self, mock_metadata, mock_upload, mock_build):
        """Dry-run builds and analyzes but never calls upload_report."""
        mock_metadata.side_effect = _make_commit_metadata
        mock_build.return_value = (_make_report(_make_layout()), False)

        args = _make_args(dry_run=True)
        success, failed = _run_binary_search_onboard(
            args, ['c0', 'c1', 'c2'], 'main', 'repo', {})

        assert success == 3
        assert failed == 0
        # Endpoints were built
        assert mock_build.call_count == 2
        # upload_report was never called
        mock_upload.assert_not_called()

    @patch('membrowse.commands.onboard._build_and_generate_report')
    @patch('membrowse.commands.onboard.upload_report')
    @patch('membrowse.commands.onboard.get_commit_metadata')
    def test_dry_run_identical_skips_upload(self, mock_metadata, mock_upload,
                                            mock_build):
        """Dry-run marks identical commits without uploading."""
        mock_metadata.side_effect = _make_commit_metadata
        report = _make_report(_make_layout(flash_used=1000))
        mock_build.return_value = (report, False)

        args = _make_args(dry_run=True)
        commits = [f'c{i}' for i in range(5)]
        success, failed = _run_binary_search_onboard(
            args, commits, 'main', 'repo', {})

        assert success == 5
        assert failed == 0
        assert mock_build.call_count == 2  # Only endpoints
        mock_upload.assert_not_called()


class TestMutualExclusivity:  # pylint: disable=too-few-public-methods
    """Test --binary-search and --build-dirs mutual exclusivity."""

    @patch('membrowse.commands.onboard._get_repository_info')
    def test_binary_search_and_build_dirs_rejected(self, mock_repo):
        """Both flags set returns error."""
        args = _make_args(binary_search=True, build_dirs=['src/'])
        result = run_onboard(args)
        assert result == 1
        # _get_repository_info should not be called
        mock_repo.assert_not_called()
