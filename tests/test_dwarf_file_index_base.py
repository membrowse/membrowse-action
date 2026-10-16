#!/usr/bin/env python3
"""
Test cases for resolving DWARF file numbers against the line program file table.

File numbers in line program rows and in DW_AT_decl_file are 0-based when
the line program header is DWARF 5 and 1-based before. The CU version must
not decide this: GCC 11+ emits DWARF 5 .debug_info together with a version 3
.debug_line when the assembler generates the line table, while older GCC
emits DWARF 4 .debug_info with a version 3 line table.
"""
# pylint: disable=protected-access,too-few-public-methods

import unittest
from types import SimpleNamespace
from unittest import mock

from membrowse.analysis.dwarf import DWARFProcessor

# The file table as pyelftools lists it. In a DWARF 5 table GCC repeats the
# primary source as entry 0 and entry 1.
FILES = [b'heap_4.c', b'heap_4.c', b'stddef.h', b'_default_types.h']


class FakeLineProgram:
    """Minimal stand-in for an elftools LineProgram."""

    def __init__(self, version, rows=()):
        self.header = SimpleNamespace(
            version=version,
            file_entry=[SimpleNamespace(name=n) for n in FILES])
        self._rows = rows

    def get_entries(self):
        """Rows as (address, file, line) states."""
        return [SimpleNamespace(state=SimpleNamespace(
            address=address, file=file_index, line=line))
            for address, file_index, line in self._rows]


class FakeCU(dict):
    """Minimal stand-in for an elftools CompileUnit."""

    def __init__(self, version):
        super().__init__(version=version)
        self.cu_offset = 0

    def get_top_DIE(self):  # pylint: disable=invalid-name
        """No DIEs: the tests only inspect the file table."""
        return None


def die_file_entries(cu_version, line_version):
    """File-number map the DIE pass builds for one CU."""
    processor = DWARFProcessor(None, set(), skip_line_program=True)
    dwarfinfo = mock.Mock()
    dwarfinfo.line_program_for_CU.return_value = FakeLineProgram(line_version)
    with mock.patch.object(processor, '_process_die_tree') as process:
        processor._extract_die_symbol_data_optimized(
            FakeCU(cu_version), dwarfinfo, 'heap_4.c', None, None)
    return process.call_args[0][1]


def line_program_files(line_version, rows):
    """address -> file map the line program pass builds for one CU."""
    processor = DWARFProcessor(None, set(), skip_line_program=False)
    dwarfinfo = mock.Mock()
    dwarfinfo.line_program_for_CU.return_value = FakeLineProgram(
        line_version, rows)
    processor._extract_line_program_data(FakeCU(5), dwarfinfo)
    return processor.dwarf_data['address_to_file']


class TestDeclFileIndexBase(unittest.TestCase):
    """DW_AT_decl_file is resolved with the line program's numbering."""

    def test_dwarf5_cu_with_version3_line_table_is_one_based(self):
        """GCC 13 Arm: CU v5, .debug_line v3. decl_file 2 is heap_4.c,
        not the stddef.h a 0-based reading would give."""
        entries = die_file_entries(cu_version=5, line_version=3)
        self.assertEqual(entries[1], 'heap_4.c')
        self.assertEqual(entries[2], 'heap_4.c')
        self.assertEqual(entries[3], 'stddef.h')
        self.assertNotIn(0, entries)

    def test_dwarf5_line_table_is_zero_based(self):
        """CU v5, .debug_line v5: file 0 is valid and file 2 is stddef.h."""
        entries = die_file_entries(cu_version=5, line_version=5)
        self.assertEqual(entries[0], 'heap_4.c')
        self.assertEqual(entries[2], 'stddef.h')

    def test_dwarf4_cu_with_version3_line_table_is_one_based(self):
        """GCC 10: CU v4, .debug_line v3."""
        entries = die_file_entries(cu_version=4, line_version=3)
        self.assertEqual(entries[3], 'stddef.h')
        self.assertNotIn(0, entries)


class TestLineProgramIndexBase(unittest.TestCase):
    """Line program rows are resolved with the line program's numbering."""

    def test_version3_line_table_is_one_based(self):
        """File 1 is the primary source and file 3 is stddef.h."""
        files = line_program_files(3, [(0x100, 1, 10), (0x200, 3, 20)])
        self.assertEqual(files[0x100], 'heap_4.c')
        self.assertEqual(files[0x200], 'stddef.h')

    def test_version3_file_zero_is_skipped(self):
        """File 0 does not exist before DWARF 5."""
        files = line_program_files(3, [(0x100, 0, 10)])
        self.assertNotIn(0x100, files)

    def test_version5_line_table_is_zero_based(self):
        """In a v5 table file 2 is stddef.h; 1-based reading gave heap_4.c."""
        files = line_program_files(
            5, [(0x100, 0, 10), (0x200, 2, 20), (0x300, 3, 30)])
        self.assertEqual(files[0x100], 'heap_4.c')
        self.assertEqual(files[0x200], 'stddef.h')
        self.assertEqual(files[0x300], '_default_types.h')

    def test_out_of_range_file_number_is_ignored(self):
        """A file number past the end of the table maps to nothing."""
        files = line_program_files(5, [(0x100, len(FILES), 10)])
        self.assertNotIn(0x100, files)


if __name__ == '__main__':
    unittest.main()
