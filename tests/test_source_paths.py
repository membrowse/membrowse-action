"""Source files reported as paths relative to a source root.

Symbols used to carry the basename of their source file. With a source
root (the repository checkout) the file is reported relative to it, e.g.
src/portable/synopsys/dwc2/dcd_dwc2.c, which tells same-named files apart
and matches the paths a repository uses for its own per-file size tables.
Files outside the root, and every file when there is no root, keep the
basename.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from membrowse.analysis.dwarf import DWARFProcessor
from membrowse.analysis.sources import SourceFileResolver, relative_source_path
from membrowse.commands.report import generate_report, resolve_source_root
from membrowse.core.analyzer import ELFAnalyzer
from tests.test_helpers import can_compile_embedded


class TestRelativeSourcePath(unittest.TestCase):
    """relative_source_path and the resolver's reported names."""

    def test_inside_root_is_relative(self):
        """Inside root is relative."""
        self.assertEqual(
            relative_source_path('/work/repo/src/class/cdc/cdc_device.c', ('/work/repo/',)),
            'src/class/cdc/cdc_device.c')

    def test_outside_root_is_basename(self):
        """Outside root is basename."""
        self.assertEqual(
            relative_source_path('/opt/toolchain/include/stdint.h', ('/work/repo/',)),
            'stdint.h')

    def test_no_root_is_basename(self):
        """No root is basename."""
        self.assertEqual(relative_source_path('/work/repo/src/main.c', ()), 'main.c')

    def test_dot_segments_are_collapsed_before_matching(self):
        """Dot segments are collapsed before matching."""
        self.assertEqual(
            relative_source_path('/work/repo/build/../src/main.c', ('/work/repo/',)),
            'src/main.c')

    def test_windows_separators_are_normalized(self):
        """Windows separators are normalized."""
        self.assertEqual(
            relative_source_path('C:\\work\\repo\\src\\main.c', ('C:/work/repo/',)),
            'src/main.c')

    def test_windows_root_is_kept_as_a_drive_path(self):
        """A drive-letter root is matched as given, on any host."""
        resolver = SourceFileResolver(
            {'symbol_to_file': {('foo', 1): 'C:\\work\\repo\\src\\foo.c'},
             'address_to_file': {}, 'address_to_cu_file': {}},
            system_header_cache={}, source_root='C:\\work\\repo')
        self.assertEqual(resolver.extract_source_file('foo', 'FUNC', 1), 'src/foo.c')

    def test_sibling_directory_with_root_as_prefix_is_outside(self):
        """/work/repo-old is not inside /work/repo."""
        self.assertEqual(
            relative_source_path('/work/repo-old/src/main.c', ('/work/repo/',)),
            'main.c')

    def test_resolver_without_root_keeps_basenames(self):
        """Resolver without root keeps basenames."""
        resolver = SourceFileResolver(
            {'symbol_to_file': {('foo', 0x1000): '/work/repo/src/foo.c'},
             'address_to_file': {}, 'address_to_cu_file': {}},
            system_header_cache={})
        self.assertEqual(resolver.extract_source_file('foo', 'FUNC', 0x1000), 'foo.c')

    def test_resolver_with_root_reports_relative_paths(self):
        """Resolver with root reports relative paths."""
        resolver = SourceFileResolver(
            {'symbol_to_file': {('foo', 0x1000): '/work/repo/src/foo.c',
                                ('bar', 0x2000): '/usr/lib/gcc/include/bar.h'},
             'address_to_file': {0x3000: '/work/repo/src/inline.h'},
             'address_to_cu_file': {0x3000: '/work/repo/src/host/baz.c'}},
            system_header_cache={}, source_root='/work/repo')
        self.assertEqual(resolver.extract_source_file('foo', 'FUNC', 0x1000), 'src/foo.c')
        self.assertEqual(resolver.extract_source_file('bar', 'OBJECT', 0x2000), 'bar.h')
        # inlined code in a header is still attributed to the CU's .c file
        self.assertEqual(resolver.extract_source_file('baz', 'FUNC', 0x3000),
                         'src/host/baz.c')

    def test_root_through_symlink_matches_both_spellings(self):
        """The compiler records the path it was invoked with; a root given
        through a symlink must match paths recorded either way."""
        with tempfile.TemporaryDirectory() as tmp:
            # the resolved temp dir: Windows hands out 8.3 short names
            real_root = os.path.join(os.path.realpath(tmp), 'real')
            os.makedirs(os.path.join(real_root, 'src'))
            link_root = os.path.join(tmp, 'link')
            try:
                os.symlink(real_root, link_root)
            except (OSError, NotImplementedError):
                self.skipTest('symlinks unavailable')
            resolver = SourceFileResolver(
                {'symbol_to_file': {('a', 1): os.path.join(real_root, 'src', 'a.c'),
                                    ('b', 2): os.path.join(link_root, 'src', 'b.c')},
                 'address_to_file': {}, 'address_to_cu_file': {}},
                system_header_cache={}, source_root=link_root)
            self.assertEqual(resolver.extract_source_file('a', 'FUNC', 1), 'src/a.c')
            self.assertEqual(resolver.extract_source_file('b', 'FUNC', 2), 'src/b.c')


class TestLineProgramFilePaths(unittest.TestCase):
    """File table entries joined with their directories, per DWARF version."""

    def _processor(self):
        return DWARFProcessor(elffile=None, symbol_addresses=set())

    def test_dwarf4_dir_index_zero_is_comp_dir_and_list_is_one_based(self):
        """Dwarf4 dir index zero is comp dir and list is one based."""
        join = self._processor()._join_file_entry  # pylint: disable=protected-access
        dirs = ['/work/repo/src/../include', 'sub']
        self.assertEqual(join('main.c', 0, dirs, False, '/work/repo/src'),
                         '/work/repo/src/main.c')
        self.assertEqual(join('tusb.h', 1, dirs, False, '/work/repo/src'),
                         '/work/repo/include/tusb.h')
        # a relative directory is relative to the compilation directory
        self.assertEqual(join('x.c', 2, dirs, False, '/work/repo/src'),
                         '/work/repo/src/sub/x.c')

    def test_dwarf5_list_is_zero_based_with_comp_dir_first(self):
        """Dwarf5 list is zero based with comp dir first."""
        join = self._processor()._join_file_entry  # pylint: disable=protected-access
        dirs = ['/work/repo/src', '/work/repo/include']
        self.assertEqual(join('main.c', 0, dirs, True, '/work/repo/src'),
                         '/work/repo/src/main.c')
        self.assertEqual(join('tusb.h', 1, dirs, True, '/work/repo/src'),
                         '/work/repo/include/tusb.h')

    def test_absolute_and_unknown_directory(self):
        """Absolute and unknown directory."""
        join = self._processor()._join_file_entry  # pylint: disable=protected-access
        self.assertEqual(join('/abs/x.c', 1, ['/d'], False, '/c'), '/abs/x.c')
        self.assertEqual(join('C:/abs/x.c', 1, ['/d'], False, '/c'), 'C:/abs/x.c')
        # out-of-range directory, no compilation directory: the bare name
        self.assertEqual(join('x.c', 7, ['/d'], False, None), 'x.c')
        self.assertEqual(join('x.c', 0, [], False, None), 'x.c')

    def test_file_table_from_header(self):
        """File table from header."""
        processor = self._processor()
        header = SimpleNamespace(
            version=4,
            include_directory=[b'/work/repo/include'],
            file_entry=[SimpleNamespace(name=b'main.c', dir_index=0),
                        SimpleNamespace(name=b'tusb.h', dir_index=1),
                        None])
        dwarfinfo = SimpleNamespace(
            line_program_for_CU=lambda cu: SimpleNamespace(header=header))
        paths = processor._line_program_file_paths(  # pylint: disable=protected-access
            dwarfinfo, SimpleNamespace(cu_offset=0), '/work/repo/src')
        self.assertEqual(paths, {1: '/work/repo/src/main.c', 2: '/work/repo/include/tusb.h'})


class TestResolveSourceRoot(unittest.TestCase):
    """Default source root of the report and onboard commands."""

    def test_explicit_wins(self):
        """Explicit wins."""
        with patch.dict(os.environ, {'GITHUB_WORKSPACE': '/ws'}):
            self.assertEqual(resolve_source_root('/explicit'), '/explicit')

    def test_github_workspace(self):
        """Github workspace."""
        with patch.dict(os.environ, {'GITHUB_WORKSPACE': '/ws'}):
            self.assertEqual(resolve_source_root(None), '/ws')

    def test_git_top_level_then_none(self):
        """Git top level then none."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('GITHUB_WORKSPACE', None)
            with patch('membrowse.commands.report.run_git_command', return_value='/top'):
                self.assertEqual(resolve_source_root(None), '/top')
            with patch('membrowse.commands.report.run_git_command', return_value=None):
                self.assertIsNone(resolve_source_root(None))


@unittest.skipUnless(shutil.which('gcc') and can_compile_embedded('gcc'),
                     'no gcc that produces ELF files')
class TestCompiledSourcePaths(unittest.TestCase):
    """A real ELF: sources under the root are reported by path, the rest by basename."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        root = os.path.join(cls.tmp, 'repo')
        os.makedirs(os.path.join(root, 'src', 'drivers'))
        os.makedirs(os.path.join(root, 'include'))
        os.makedirs(os.path.join(cls.tmp, 'vendor'))
        with open(os.path.join(root, 'include', 'inl.h'), 'w', encoding='utf-8') as f:
            f.write('static inline int inl(int x) { return x * 3; }\n')
        with open(os.path.join(root, 'src', 'drivers', 'drv.c'), 'w', encoding='utf-8') as f:
            f.write('#include "inl.h"\nint drv_state = 7;\n'
                    'int drv_run(int x) { return inl(x) + drv_state; }\n')
        with open(os.path.join(root, 'src', 'main.c'), 'w', encoding='utf-8') as f:
            f.write('int drv_run(int);\nint vendor_fn(int);\nint main_counter;\n'
                    'int main(void) { return drv_run(vendor_fn(main_counter)); }\n')
        with open(os.path.join(cls.tmp, 'vendor', 'vendor.c'), 'w', encoding='utf-8') as f:
            f.write('int vendor_fn(int x) { return x + 1; }\n')
        cls.root = root
        cls.elf = os.path.join(cls.tmp, 'prog.elf')
        subprocess.run(
            ['gcc', '-g', '-O0', '-I', os.path.join(root, 'include'),
             os.path.join(root, 'src', 'main.c'),
             os.path.join(root, 'src', 'drivers', 'drv.c'),
             os.path.join(cls.tmp, 'vendor', 'vendor.c'),
             '-o', cls.elf],
            check=True, capture_output=True, text=True, cwd=root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _sources(self, source_root):
        analyzer = ELFAnalyzer(self.elf, source_root=source_root)
        return {s.name: s.source_file for s in analyzer.get_symbols()}

    def test_paths_relative_to_root(self):
        """Paths relative to root."""
        sources = self._sources(self.root)
        self.assertEqual(sources['main'], 'src/main.c')
        self.assertEqual(sources['main_counter'], 'src/main.c')
        self.assertEqual(sources['drv_run'], 'src/drivers/drv.c')
        self.assertEqual(sources['drv_state'], 'src/drivers/drv.c')
        self.assertEqual(sources['vendor_fn'], 'vendor.c', 'outside the root: basename')

    def test_without_root_basenames(self):
        """Without root basenames."""
        sources = self._sources(None)
        self.assertEqual(sources['main'], 'main.c')
        self.assertEqual(sources['drv_run'], 'drv.c')

    def test_generate_report_passes_the_root(self):
        """Generate report passes the root."""
        report = generate_report(self.elf, source_root=self.root)
        by_name = {s['name']: s['source_file'] for s in report['symbols']}
        self.assertEqual(by_name['drv_run'], 'src/drivers/drv.c')


if __name__ == '__main__':
    unittest.main()
