"""Tests for the per-file changes in the PR comment template context."""
from membrowse.utils.github_comment import _build_template_context
from membrowse.utils.summary_formatter import (
    build_summary_template_context,
    enrich_files,
    region_kind,
    summarize_file_changes,
)


class TestRegionKind:
    """Flash or RAM from the linker attributes, else from the region's name."""

    def test_writable_attributes_are_ram_and_others_flash(self):
        """Writable attributes are ram and others flash."""
        assert region_kind('X', 'rw') == 'ram'
        assert region_kind('X', 'xrw') == 'ram'
        assert region_kind('X', 'rx') == 'flash'
        assert region_kind('X', 'r') == 'flash'

    def test_attributes_win_over_the_name(self):
        """Attributes win over the name."""
        assert region_kind('FLASH_LIKE', 'rw') == 'ram'
        assert region_kind('RAM_LIKE', 'rx') == 'flash'

    def test_unknown_type_falls_back_to_the_name(self):
        """Unknown type falls back to the name."""
        for region_type in (None, '', 'UNKNOWN', 'unknown'):
            assert region_kind('FLASH', region_type) == 'flash'
            assert region_kind('ROM', region_type) == 'flash'
            assert region_kind('m_text', region_type) == 'flash'
            assert region_kind('Code', region_type) == 'flash'
            assert region_kind('RAM', region_type) == 'ram'
            assert region_kind('DTCM', region_type) == 'ram'
            assert region_kind('m_data', region_type) == 'ram'
            assert region_kind('SDRAM', region_type) == 'ram'

    def test_data_flash_is_flash(self):
        """Data flash is flash."""
        assert region_kind('DATA_FLASH', 'UNKNOWN') == 'flash'

    def test_a_name_with_no_hint_is_other(self):
        """A name with no hint is other."""
        assert region_kind('SPIX', 'UNKNOWN') == 'other'
        assert region_kind('VECT1', None) == 'other'


LAYOUT = {
    'FLASH': {'type': 'rx', 'used_size': 1000, 'limit_size': 4000},
    'RAM': {'type': 'UNKNOWN', 'used_size': 100, 'limit_size': 400},
}


class TestEnrichFiles:
    """Each added, removed and modified entry becomes a delta with its kind."""

    def test_added_removed_modified_deltas(self):
        """Added removed modified deltas."""
        files = {
            'added': [{'name': 'src/new.c', 'region': 'FLASH', 'size': 40}],
            'removed': [{'name': 'src/gone.c', 'region': 'RAM', 'size': 16}],
            'modified': [{'name': 'src/main.c', 'region': 'RAM', 'size': 300,
                          'old': {'size': 44}}],
        }
        entries = enrich_files(files, LAYOUT)
        assert [(e['name'], e['kind'], e['old_size'], e['size'], e['delta'], e['delta_str'])
                for e in entries] == [
            ('src/new.c', 'flash', 0, 40, 40, '+40'),
            ('src/gone.c', 'ram', 16, 0, -16, '-16'),
            ('src/main.c', 'ram', 44, 300, 256, '+256'),
        ]
        assert entries[0]['region'] == 'FLASH'

    def test_absent_or_empty_files_give_no_entries(self):
        """Absent or empty files give no entries."""
        assert not enrich_files(None, LAYOUT)
        assert not enrich_files({'added': [], 'removed': [], 'modified': []}, LAYOUT)

    def test_a_region_missing_from_the_layout_is_classified_by_name(self):
        """A region missing from the layout is classified by name."""
        entries = enrich_files({'added': [{'name': 'a.c', 'region': 'SRAM', 'size': 1}]}, {})
        assert entries[0]['kind'] == 'ram'


def _target(name, files):
    return {'name': name, 'files': enrich_files(files, LAYOUT)}


class TestSummarizeFileChanges:
    """Rows across targets: min and max per kind, with the build of each end."""

    def test_min_and_max_over_the_targets_the_file_changed_in(self):
        """Min and max over the targets the file changed in."""
        rows = summarize_file_changes([
            _target('a/cdc', {'modified': [
                {'name': 'main.c', 'region': 'FLASH', 'size': 110, 'old': {'size': 100}},
                {'name': 'main.c', 'region': 'RAM', 'size': 356, 'old': {'size': 100}}]}),
            _target('b/cdc', {'modified': [
                {'name': 'main.c', 'region': 'FLASH', 'size': 140, 'old': {'size': 100}},
                {'name': 'main.c', 'region': 'RAM', 'size': 356, 'old': {'size': 100}}]}),
            _target('c/hid', {'modified': [
                {'name': 'main.c', 'region': 'FLASH', 'size': 120, 'old': {'size': 100}}]}),
        ])
        assert len(rows) == 1
        row = rows[0]
        assert row['name'] == 'main.c'
        assert row['builds'] == 3
        assert row['flash'] == {'min': 10, 'max': 40, 'min_str': '+10', 'max_str': '+40',
                                'min_build': 'a/cdc', 'max_build': 'b/cdc', 'builds': 3}
        assert row['ram']['min'] == row['ram']['max'] == 256
        assert row['ram']['builds'] == 2
        assert (row['ram']['min_build'], row['ram']['max_build']) == ('a/cdc', 'b/cdc')
        assert row['other'] == {'min': 0, 'max': 0, 'min_str': '0', 'max_str': '0',
                                'min_build': None, 'max_build': None, 'builds': 0}

    def test_regions_of_one_kind_are_summed_per_target(self):
        """Regions of one kind are summed per target."""
        rows = summarize_file_changes([_target('a/cdc', {
            'added': [{'name': 'x.c', 'region': 'RAM', 'size': 30}],
            'removed': [{'name': 'x.c', 'region': 'DTCM', 'size': 30}],
            'modified': [{'name': 'y.c', 'region': 'RAM', 'size': 8, 'old': {'size': 4}},
                         {'name': 'y.c', 'region': 'CCMRAM', 'size': 1, 'old': {'size': 9}}],
        })])
        # x.c merely moved between two RAM regions: no change in RAM, no row
        assert [row['name'] for row in rows] == ['y.c']
        assert rows[0]['ram']['min'] == rows[0]['ram']['max'] == -4
        assert rows[0]['builds'] == 1

    def test_rows_sort_by_largest_absolute_delta_then_name(self):
        """Rows sort by largest absolute delta then name."""
        rows = summarize_file_changes([_target('a/cdc', {'added': [
            {'name': 'small.c', 'region': 'FLASH', 'size': 2},
            {'name': 'b.c', 'region': 'RAM', 'size': 9},
            {'name': 'a.c', 'region': 'FLASH', 'size': 9},
        ], 'removed': [{'name': 'big.c', 'region': 'FLASH', 'size': 500}]})])
        assert [row['name'] for row in rows] == ['big.c', 'a.c', 'b.c', 'small.c']

    def test_other_regions_count_as_a_change_of_their_own_kind(self):
        """Other regions count as a change of their own kind."""
        rows = summarize_file_changes([_target('a/cdc', {'added': [
            {'name': 'v.c', 'region': 'SPIX', 'size': 7}]})])
        assert rows[0]['flash']['builds'] == 0
        assert rows[0]['ram']['builds'] == 0
        assert rows[0]['other'] == {'min': 7, 'max': 7, 'min_str': '+7', 'max_str': '+7',
                                    'min_build': 'a/cdc', 'max_build': 'a/cdc', 'builds': 1}

    def test_no_targets_no_rows(self):
        """No targets no rows."""
        assert not summarize_file_changes([])


SUMMARY = {
    'success': True,
    'data': {
        'commit_sha': 'abc',
        'pr_number': 16,
        'dashboard_url': 'https://membrowse.com/project/p?commit_sha=abc',
        'targets': [
            {
                'target_name': 'board/cdc',
                'dashboard_url': 'https://membrowse.com/compare',
                'changes_summary': {
                    'memory_layout': LAYOUT,
                    'changes': {
                        'regions': {'modified': [{'name': 'RAM', 'used_size': 356,
                                                  'limit_size': 400, 'old': {'used_size': 100}}]},
                        'sections': {'modified': []},
                        'files': {'added': [], 'removed': [], 'modified': [
                            {'name': 'src/main.c', 'region': 'RAM', 'size': 356,
                             'old': {'size': 100}}]},
                    },
                },
                'alerts': None,
            },
            {
                'target_name': 'board/hid',
                'dashboard_url': None,
                'changes_summary': {
                    'memory_layout': LAYOUT,
                    'changes': {'regions': {'modified': []}, 'sections': {'modified': []},
                                'files': {'added': [], 'removed': [], 'modified': []}},
                },
                'alerts': None,
            },
            {
                # a root, or a base without file sizes: no files key at all
                'target_name': 'board/msc',
                'dashboard_url': None,
                'changes_summary': {'memory_layout': LAYOUT,
                                    'changes': {'regions': {'modified': []},
                                                'sections': {'modified': []}}},
                'alerts': None,
            },
        ],
    },
}


class TestTemplateContext:
    """Both context builders carry the per-target files and the cross-target rows."""

    def test_summary_mode_context(self):
        """Summary mode context."""
        context = build_summary_template_context(SUMMARY)
        assert [t['has_file_changes'] for t in context['targets']] == [True, False, False]
        assert context['targets'][0]['files'][0]['delta'] == 256
        assert context['targets_with_file_changes'] == 1
        assert [row['name'] for row in context['file_changes']] == ['src/main.c']
        assert context['file_changes'][0]['ram']['max_build'] == 'board/cdc'

    def test_file_mode_context(self):
        """File mode context."""
        results = [{
            'target_name': 'board/cdc',
            'comparison_url': None,
            'api_response': {'data': {
                'memory_layout': LAYOUT,
                'changes': {'regions': {'modified': []}, 'sections': {'modified': []},
                            'files': {'added': [{'name': 'src/new.c', 'region': 'FLASH',
                                                 'size': 12}],
                                      'removed': [], 'modified': []}},
            }},
        }]
        context = _build_template_context(results)
        assert context['targets'][0]['has_file_changes'] is True
        assert context['targets_with_file_changes'] == 1
        assert context['file_changes'][0]['flash']['max_str'] == '+12'
