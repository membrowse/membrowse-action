"""Source files reported as paths relative to a source root.

Symbols used to carry the basename of their source file. With a source
root (the repository checkout) the file is reported relative to it, e.g.
src/portable/synopsys/dwc2/dcd_dwc2.c, which tells same-named files apart
and matches the paths a repository uses for its own per-file size tables.
Files outside the root, and every file when there is no root (the
default), keep the basename.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from membrowse.analysis.dwarf import DWARFProcessor
from membrowse.analysis.sources import SourceFileResolver, relative_source_path
from membrowse.commands.report import generate_report
from membrowse.core.analyzer import ELFAnalyzer
from tests.test_helpers import can_compile_embedded


class TestRelativeSourcePath(unittest.TestCase):
    """relative_source_path and the resolver's reported names."""

    def test_inside_root_is_relative(self):
        """Inside root is relative."""
        self.assertEqual(
            relative_source_path('/work/repo/src/class/cdc/cdc_device.c', ('/work/repo/',)),
            'src/class/cdc/cdc_device.c')

    def test_outside_root_is_none(self):
        """Outside root no root applies: the resolver falls back to the basename."""
        self.assertIsNone(
            relative_source_path('/opt/toolchain/include/stdint.h', ('/work/repo/',)))

    def test_no_root_is_none(self):
        """No root: nothing applies, the resolver falls back to the basename."""
        self.assertIsNone(relative_source_path('/work/repo/src/main.c', ()))
        self.assertIsNone(relative_source_path('src/main.c', ()))

    def test_already_relative_path_is_kept_under_a_root(self):
        """A build with -ffile-prefix-map=/path/repo=. records paths relative
        to the repository already; with a root set they are reported as
        recorded, while a path leaving the build directory is not."""
        self.assertEqual(relative_source_path('./src/main.c', ('/work/repo/',)), 'src/main.c')
        self.assertEqual(relative_source_path('src/main.c', ('/work/repo/',)), 'src/main.c')
        self.assertIsNone(relative_source_path('../lib/x.c', ('/work/repo/',)))

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

    def test_windows_paths_ignore_case_on_any_host(self):
        """A Windows toolchain may record a lowercase drive letter; the
        file system ignores case, so the root matches on a Linux runner too."""
        self.assertEqual(
            relative_source_path('c:/Work/repo/src/main.c', ('C:/work/repo/',)),
            'src/main.c')
        self.assertEqual(
            relative_source_path('//server/share/repo/SRC/main.c', ('//server/share/repo/',)),
            'SRC/main.c')

    def test_posix_paths_are_case_sensitive(self):
        """Posix paths are case sensitive."""
        self.assertIsNone(relative_source_path('/Work/repo/src/main.c', ('/work/repo/',)))

    def test_sibling_directory_with_root_as_prefix_is_outside(self):
        """/work/repo-old is not inside /work/repo."""
        self.assertIsNone(
            relative_source_path('/work/repo-old/src/main.c', ('/work/repo/',)))

    def test_resolver_without_root_keeps_basenames(self):
        """Resolver without root keeps basenames."""
        resolver = SourceFileResolver(
            {'symbol_to_file': {('foo', 0x1000): '/work/repo/src/foo.c'},
             'address_to_file': {}, 'address_to_cu_file': {}},
            system_header_cache={})
        self.assertEqual(resolver.extract_source_file('foo', 'FUNC', 0x1000), 'foo.c')

    def test_resolver_warns_when_no_path_lies_under_the_root(self):
        """Firmware built from another checkout (a container mount) matches
        nothing; say so instead of silently reporting basenames."""
        resolver = SourceFileResolver(
            {'symbol_to_file': {('foo', 1): '/app/src/foo.c', ('bar', 2): '/app/src/bar.c'},
             'address_to_file': {}, 'address_to_cu_file': {}},
            system_header_cache={}, source_root='/__w/repo/repo')
        self.assertEqual(resolver.extract_source_file('foo', 'FUNC', 1), 'foo.c')
        self.assertEqual(resolver.extract_source_file('bar', 'FUNC', 2), 'bar.c')
        with self.assertLogs('membrowse.analysis.sources', level='WARNING') as logs:
            resolver.log_source_root_coverage()
        self.assertIn('/__w/repo/repo', logs.output[0])
        self.assertIn('2 distinct', logs.output[0])

    def test_resolver_is_quiet_when_a_path_matches_or_no_root_is_set(self):
        """Resolver is quiet when a path matches or no root is set."""
        with mock.patch('membrowse.analysis.sources.logger') as logger:
            resolver = SourceFileResolver(
                {'symbol_to_file': {('foo', 1): '/work/repo/src/foo.c',
                                    ('bar', 2): '/opt/libc/bar.c'},
                 'address_to_file': {}, 'address_to_cu_file': {}},
                system_header_cache={}, source_root='/work/repo')
            resolver.extract_source_file('foo', 'FUNC', 1)
            resolver.extract_source_file('bar', 'FUNC', 2)
            resolver.log_source_root_coverage()
            resolver = SourceFileResolver(
                {'symbol_to_file': {('bar', 2): '/opt/libc/bar.c'},
                 'address_to_file': {}, 'address_to_cu_file': {}},
                system_header_cache={})
            resolver.extract_source_file('bar', 'FUNC', 2)
            resolver.log_source_root_coverage()
            logger.warning.assert_not_called()

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

    def test_dwarf5_entry_without_directory_index_is_in_directory_zero(self):
        """pyelftools stores dir_index=None when the entry format has no
        DW_LNCT_directory_index; that must not fail the whole CU."""
        processor = self._processor()
        header = SimpleNamespace(
            version=5,
            include_directory=[b'/work/repo/src'],
            file_entry=[SimpleNamespace(name=b'main.c', dir_index=None)])
        dwarfinfo = SimpleNamespace(
            line_program_for_CU=lambda cu: SimpleNamespace(header=header))
        paths = processor._line_program_file_paths(  # pylint: disable=protected-access
            dwarfinfo, SimpleNamespace(cu_offset=0), '/work/repo/src')
        self.assertEqual(paths, {0: '/work/repo/src/main.c'})

    def test_windows_absolute_cu_name_is_not_joined_onto_comp_dir(self):
        """CMake on a Windows runner hands the compiler absolute sources."""
        self.assertEqual(
            self._cu_source_file('C:/proj/src/main.c', 'C:/proj/build'),
            'C:/proj/src/main.c')
        self.assertEqual(
            self._cu_source_file('C:\\proj\\src\\main.c', 'C:\\proj\\build'),
            'C:/proj/src/main.c')
        self.assertEqual(
            self._cu_source_file('../src/main.c', 'C:/proj/build'),
            'C:/proj/src/main.c')
        self.assertEqual(
            self._cu_source_file('/proj/src/main.c', '/proj/build'),
            '/proj/src/main.c')

    def _cu_source_file(self, name, comp_dir):
        """The CU source file _process_cu hands the DIE pass."""
        processor = DWARFProcessor(elffile=None, symbol_addresses=set(),
                                   skip_line_program=True)
        attributes = {'DW_AT_name': SimpleNamespace(value=name.encode()),
                      'DW_AT_comp_dir': SimpleNamespace(value=comp_dir.encode())}
        cu = SimpleNamespace(
            cu_offset=0, get_top_DIE=lambda: SimpleNamespace(attributes=attributes))
        with mock.patch.object(processor, '_extract_cu_address_range',
                               return_value=(None, None)), \
             mock.patch.object(processor, '_line_program_file_paths', return_value={}), \
             mock.patch.object(processor, '_extract_die_symbol_data_optimized') as die_pass:
            processor._process_cu(cu, dwarfinfo=None)  # pylint: disable=protected-access
        return die_pass.call_args[0][1]

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
