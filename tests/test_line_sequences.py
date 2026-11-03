#!/usr/bin/env python3
"""
Test cases for taking DWARF line program rows one sequence at a time.

A sequence covers [first row, end_sequence row). The end_sequence row is the
first address after the sequence and often the start of another CU's
function, so it must not map that address. Sequences of code the linker
discarded (ld.bfd: relocated to 0, LLD: tombstone -1) are dropped whole, and
the address lookup only uses a row from a sequence that contains the address.
"""
# pylint: disable=protected-access

import unittest
from unittest import mock

from membrowse.analysis.dwarf import DWARFProcessor
from membrowse.analysis.sources import SourceFileResolver
from tests.test_dwarf_file_index_base import FakeCU, FakeLineProgram

# Version 5 file table: 0 heap_4.c, 2 stddef.h, 3 _default_types.h
HEAP, STDDEF, TYPES = 0, 2, 3
END = True


def run_cus(*cus, elffile=None):
    """dwarf_data after the line program pass over the given CUs' rows."""
    processor = DWARFProcessor(elffile, set(), skip_line_program=False)
    for offset, rows in enumerate(cus):
        dwarfinfo = mock.Mock()
        dwarfinfo.line_program_for_CU.return_value = FakeLineProgram(5, rows)
        cu = FakeCU(5)
        cu.cu_offset = offset
        file_paths = processor._line_program_file_paths(dwarfinfo, cu, None)
        processor._extract_line_program_data(cu, dwarfinfo, file_paths)
    return processor.dwarf_data


def elf_with_function_at(address):
    """A minimal ELF with one STT_FUNC symbol."""
    symbol = {'st_info': {'type': 'STT_FUNC'}, 'st_value': address,
              'st_shndx': 1}
    symtab = mock.Mock()
    symtab.iter_symbols.return_value = [symbol]
    elffile = mock.Mock()
    elffile.get_section_by_name.return_value = symtab
    return elffile


def resolver(dwarf_data):
    """A source resolver over dwarf_data."""
    dwarf_data.setdefault('symbol_to_file', {})
    dwarf_data.setdefault('address_to_cu_file', {})
    return SourceFileResolver(dwarf_data, {})


class TestEndSequence(unittest.TestCase):
    """The end_sequence row closes a sequence and maps nothing."""

    def test_end_sequence_row_is_not_stored(self):
        """Rows map their addresses; the end address is only the range end."""
        data = run_cus([(0x100, HEAP, 10), (0x108, HEAP, 11), (0x110, HEAP, 12, END)])
        self.assertEqual(data['address_to_file'], {0x100: 'heap_4.c', 0x108: 'heap_4.c'})
        self.assertNotIn(0x110, data['address_to_line'])
        self.assertEqual(data['line_sequences'], [(0x100, 0x110, 0)])

    def test_next_cu_keeps_its_start_address(self):
        """The CU before keeps no claim on the address where it ends,
        whichever CU is processed first."""
        owner = [(0x110, STDDEF, 5), (0x120, STDDEF, 6, END)]
        before = [(0x100, HEAP, 10), (0x110, HEAP, 12, END)]
        for order in ((owner, before), (before, owner)):
            data = run_cus(*order)
            self.assertEqual(data['address_to_file'][0x110], 'stddef.h')
            self.assertEqual(data['address_to_line'][0x110], 5)

    def test_row_at_the_end_address_is_not_stored(self):
        """A row just before end_sequence at the same address covers zero
        bytes; the next CU's code (here libgcc assembly) starts there."""
        before = [(0x100, HEAP, 10), (0x10c, HEAP, 12), (0x10c, HEAP, 12, END)]
        owner = [(0x10c, STDDEF, 77), (0x120, STDDEF, 78, END)]
        data = run_cus(before, owner)
        self.assertEqual(data['address_to_file'][0x10c], 'stddef.h')
        self.assertEqual(data['address_to_line'][0x10c], 77)

    def test_unterminated_sequence_keeps_its_rows(self):
        """A line program cut short still maps the rows it has."""
        data = run_cus([(0x100, HEAP, 10), (0x104, HEAP, 11)])
        self.assertEqual(data['address_to_file'][0x104], 'heap_4.c')
        self.assertEqual(data['line_sequences'], [(0x100, 0x105, 0)])


class TestRowCollisions(unittest.TestCase):
    """Which row keeps an address that several rows name."""

    def test_last_row_wins_within_a_sequence(self):
        """Earlier rows at the same address cover zero bytes."""
        data = run_cus([(0x100, STDDEF, 3), (0x100, HEAP, 10), (0x108, HEAP, 11, END)])
        self.assertEqual(data['address_to_file'][0x100], 'heap_4.c')
        self.assertEqual(data['address_to_line'][0x100], 10)

    def test_first_sequence_wins_across_sequences(self):
        """A later CU does not overwrite an address already mapped."""
        data = run_cus([(0x100, HEAP, 10), (0x108, HEAP, 11, END)],
                       [(0x100, STDDEF, 3), (0x104, STDDEF, 4, END)])
        self.assertEqual(data['address_to_file'][0x100], 'heap_4.c')
        self.assertEqual(data['address_to_line'][0x100], 10)


class TestDeadSequences(unittest.TestCase):
    """Sequences of discarded code are dropped as a whole."""

    LIVE = [(0x4, HEAP, 10), (0x10, HEAP, 11, END)]
    BFD_DEAD = [(0x0, STDDEF, 1), (0x4, STDDEF, 2), (0x8, STDDEF, 3), (0xc, STDDEF, 4, END)]

    def test_bfd_sequence_at_zero_is_dropped(self):
        """ld.bfd puts a discarded function at 0: none of its rows count,
        whichever CU is processed first."""
        for order in ((self.LIVE, self.BFD_DEAD), (self.BFD_DEAD, self.LIVE)):
            data = run_cus(*order)
            self.assertEqual(data['address_to_file'], {0x4: 'heap_4.c'})
            self.assertEqual([seq[:2] for seq in data['line_sequences']], [(0x4, 0x10)])

    def test_sequence_at_zero_is_kept_with_a_function_at_zero(self):
        """Real code linked at 0 (e.g. _start) keeps its rows."""
        data = run_cus([(0x0, HEAP, 1), (0x4, HEAP, 2, END)],
                       elffile=elf_with_function_at(0))
        self.assertEqual(data['address_to_file'][0x0], 'heap_4.c')

    def test_thumb_function_at_zero_counts(self):
        """A Thumb function at 0 has symbol value 1."""
        data = run_cus([(0x0, HEAP, 1), (0x4, HEAP, 2, END)],
                       elffile=elf_with_function_at(1))
        self.assertIn(0x0, data['address_to_file'])

    def test_function_elsewhere_does_not_keep_zero(self):
        """Only a function at 0 keeps sequences that start there."""
        data = run_cus(self.BFD_DEAD, elffile=elf_with_function_at(0x100))
        self.assertEqual(data['address_to_file'], {})

    def test_lld_tombstone_sequence_is_dropped(self):
        """LLD sets a discarded function to -1; its rows run past 32 bits."""
        data = run_cus([(0xffffffff, HEAP, 1), (0x100000003, HEAP, 2),
                        (0x100000007, HEAP, 3, END)])
        self.assertEqual(data['address_to_file'], {})
        self.assertEqual(data['line_sequences'], [])


class TestSameCUGap(unittest.TestCase):
    """Functions without line rows between two sequences of one CU."""

    def setUp(self):
        # CU 0 has two sequences with a gap at 0x110..0x118 (e.g. empty weak
        # callbacks whose DIEs are declarations only); CU 1 follows.
        self.data = run_cus(
            [(0x100, HEAP, 10), (0x10c, HEAP, 11), (0x110, HEAP, 12, END),
             (0x118, HEAP, 20), (0x120, HEAP, 21, END)],
            [(0x130, STDDEF, 5), (0x140, STDDEF, 6, END)])
        self.resolver = resolver(self.data)

    def test_gap_inside_one_cu_takes_its_file(self):
        """0x112 lies between two heap_4.c sequences."""
        self.assertEqual(self.resolver._resolve_by_address(0x113), 'heap_4.c')

    def test_gap_inside_one_cu_has_no_line(self):
        """No row covers the gap, so no line is reported."""
        self.assertEqual(self.resolver.extract_source_line(0x112), 0)

    def test_gap_between_cus_maps_nothing(self):
        """0x124 lies between heap_4.c and stddef.h: neither file is used."""
        self.assertEqual(self.resolver._resolve_by_address(0x124), '')

    def test_far_gap_inside_one_cu_maps_nothing(self):
        """The gap row is only used within 100 bytes."""
        data = run_cus([(0x100, HEAP, 10), (0x104, HEAP, 10, END),
                        (0x400, HEAP, 20), (0x404, HEAP, 21, END)])
        self.assertEqual(resolver(data)._resolve_by_address(0x200), '')


class TestAddressLookup(unittest.TestCase):
    """The nearby lookup only uses rows of a sequence containing the address."""

    def setUp(self):
        self.data = run_cus(
            [(0x100, HEAP, 10), (0x108, HEAP, 11), (0x110, HEAP, 12, END)],
            [(0x120, STDDEF, 5), (0x130, STDDEF, 6, END)])
        self.resolver = resolver(self.data)

    def test_address_inside_a_sequence_takes_the_row_before(self):
        """0x10c is covered by the row at 0x108."""
        self.assertEqual(self.resolver._find_nearby_address(0x10c), 0x108)
        self.assertEqual(self.resolver._resolve_by_address(0x10c), 'heap_4.c')
        self.assertEqual(self.resolver.extract_source_line(0x10c), 11)

    def test_thumb_address_takes_its_row(self):
        """A Thumb symbol at 0x121 maps to the row at 0x120."""
        self.assertEqual(self.resolver._resolve_by_address(0x121), 'stddef.h')

    def test_gap_after_a_sequence_maps_nothing(self):
        """0x114 lies past heap_4.c's sequence: not its file, not its line."""
        self.assertIsNone(self.resolver._find_nearby_address(0x114))
        self.assertEqual(self.resolver._resolve_by_address(0x114), '')
        self.assertEqual(self.resolver.extract_source_line(0x114), 0)

    def test_address_before_every_sequence_maps_nothing(self):
        """The row just after the address is not used either."""
        self.assertIsNone(self.resolver._find_nearby_address(0xfc))

    def test_end_address_maps_nothing(self):
        """The end of the last sequence is outside it."""
        self.assertIsNone(self.resolver._find_nearby_address(0x130))


if __name__ == '__main__':
    unittest.main()
