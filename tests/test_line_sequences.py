#!/usr/bin/env python3
"""
Test cases for taking DWARF line program rows one sequence at a time.

A sequence covers [first row, end_sequence row). The end_sequence row is the
first address after the sequence and often the start of another CU's
function, so it must not map that address. Sequences of code the linker
discarded (ld.bfd: relocated to 0 plus an offset, LLD: tombstone -1) are
dropped whole, and the address lookup only uses a row from a sequence that
contains the address.
"""
# pylint: disable=protected-access

import unittest
from types import SimpleNamespace
from unittest import mock

from membrowse.analysis.dwarf import DWARFProcessor
from membrowse.analysis.line_sequences import CodeLayout, line_sequences
from membrowse.analysis.sources import SourceFileResolver
from tests.test_dwarf_file_index_base import FakeCU, FakeLineProgram

# Version 5 file table: 0 heap_4.c, 2 stddef.h, 3 _default_types.h
HEAP, STDDEF, TYPES = 0, 2, 3
MISSING = 9  # not in the file table
END = True

# Code at 0 (flash at 0, as on nRF), with code symbols at 0x0 and 0x100
CODE_AT_ZERO = CodeLayout([(0x0, 0x1000)], {0x0, 0x100})


def run_cus(*cus, layout=None):
    """dwarf_data after the line program pass over the given CUs' rows."""
    processor = DWARFProcessor(None, set(), skip_line_program=False)
    if layout is not None:
        processor._code_layout = layout
    for offset, rows in enumerate(cus):
        dwarfinfo = mock.Mock()
        dwarfinfo.line_program_for_CU.return_value = FakeLineProgram(5, rows)
        cu = FakeCU(5)
        cu.cu_offset = offset
        file_paths = processor._line_program_file_paths(dwarfinfo, cu, None)
        processor._extract_line_program_data(cu, dwarfinfo, file_paths)
    processor._store_line_sequences()
    return processor.dwarf_data


class FakeSection(dict):
    """A pyelftools section header with a name."""

    def __init__(self, name, **header):
        super().__init__(sh_type='SHT_PROGBITS', **header)
        self.name = name


class FakeSymbol(dict):
    """A pyelftools symbol with a name."""

    def __init__(self, name, sym_type, value, shndx=1):
        super().__init__(st_info={'type': sym_type}, st_value=value, st_shndx=shndx)
        self.name = name


def fake_elf(symbols, text=(0x0, 0x1000)):
    """An ELF with one executable section and a symbol table."""
    symtab = FakeSection('.symtab', sh_flags=0, sh_addr=0, sh_size=16)
    symtab.iter_symbols = lambda: symbols  # pylint: disable=attribute-defined-outside-init
    sections = [
        FakeSection('.text', sh_flags=0x6, sh_addr=text[0], sh_size=text[1] - text[0]),
        FakeSection('.data', sh_flags=0x3, sh_addr=0x20000000, sh_size=0x100),
        symtab]
    return SimpleNamespace(iter_sections=lambda: iter(sections))


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

    def test_overlap_keeps_the_sequence_at_a_code_symbol(self):
        """A bfd-discarded sequence at 0x4 (0 plus its offset) lies on live
        code at 0x0; the live one starts at a symbol and keeps its rows,
        whichever CU is read first."""
        live = [(0x0, HEAP, 1), (0x4, HEAP, 2), (0x8, HEAP, 3), (0x10, HEAP, 4, END)]
        dead = [(0x4, STDDEF, 7), (0x8, STDDEF, 8), (0xc, STDDEF, 9, END)]
        for order in ((live, dead), (dead, live)):
            data = run_cus(*order, layout=CODE_AT_ZERO)
            self.assertEqual(set(data['address_to_file'].values()), {'heap_4.c'})
            self.assertEqual([seq[:2] for seq in data['line_sequences']], [(0x0, 0x10)])

    def test_comdat_copies_keep_the_first_cu(self):
        """Two CUs describe one inline function with the same range (ld.bfd
        points the discarded COMDAT copy at the kept one): the first CU's
        rows are used, whichever CU is read first."""
        first = [(0x100, STDDEF, 3), (0x104, STDDEF, 4), (0x108, STDDEF, 5, END)]
        second = [(0x100, TYPES, 3), (0x104, TYPES, 4), (0x108, TYPES, 5, END)]
        data = run_cus(first, second, layout=CODE_AT_ZERO)
        self.assertEqual(data['address_to_file'], {0x100: 'stddef.h', 0x104: 'stddef.h'})
        self.assertEqual(data['line_sequences'], [(0x100, 0x108, 0)])

    def test_overlap_that_cannot_be_told_apart_keeps_neither(self):
        """Two sequences starting at one code symbol with different ends:
        neither file is used."""
        data = run_cus([(0x100, HEAP, 10), (0x108, HEAP, 11, END)],
                       [(0x100, STDDEF, 3), (0x104, STDDEF, 4, END)],
                       layout=CODE_AT_ZERO)
        self.assertEqual(data['address_to_file'], {})
        self.assertEqual(data['line_sequences'], [])

    def test_overlap_without_a_symbol_table_keeps_neither(self):
        """Without symbols the live sequence cannot be told."""
        data = run_cus([(0x100, HEAP, 10), (0x108, HEAP, 11, END)],
                       [(0x100, STDDEF, 3), (0x104, STDDEF, 4, END)])
        self.assertEqual(data['address_to_file'], {})


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

    def test_sequence_at_zero_is_kept_with_code_symbol_at_zero(self):
        """Real code linked at 0 (e.g. _start) keeps its rows."""
        data = run_cus([(0x0, HEAP, 1), (0x4, HEAP, 2, END)], layout=CODE_AT_ZERO)
        self.assertEqual(data['address_to_file'][0x0], 'heap_4.c')

    def test_sequence_at_zero_without_code_symbol_is_dropped(self):
        """With code at 0 but no symbol there (a vector table), a sequence
        at 0 is ld.bfd's discarded code."""
        layout = CodeLayout([(0x0, 0x1000)], {0x100})
        data = run_cus(self.BFD_DEAD, layout=layout)
        self.assertEqual(data['address_to_file'], {})

    def test_dead_start_is_the_first_row_whatever_its_file(self):
        """A discarded sequence at 0 whose first row names no known file
        still starts at 0, not at its first resolved row."""
        dead = [(0x0, MISSING, 1), (0x4, STDDEF, 2), (0x8, STDDEF, 3), (0xc, STDDEF, 4, END)]
        data = run_cus(dead, layout=CodeLayout([(0x0, 0x1000)], {0x4}))
        self.assertEqual(data['address_to_file'], {})

    def test_many_sequences_at_zero_keep_none(self):
        """--gc-sections with a function at 0: several sequences start at 0,
        and which one is live cannot be told."""
        live = [(0x0, HEAP, 1), (0x8, HEAP, 2, END)]
        data = run_cus(live, self.BFD_DEAD,
                       [(0x0, TYPES, 1), (0x20, TYPES, 2, END)], layout=CODE_AT_ZERO)
        self.assertEqual(data['address_to_file'], {})
        self.assertEqual(data['line_sequences'], [])

    def test_sequence_outside_code_is_dropped(self):
        """With flash at 0x08000000, a discarded function at 0x40 (0 plus
        its offset in the section) lies outside every code section."""
        layout = CodeLayout([(0x08000000, 0x08001000)], {0x08000000})
        data = run_cus([(0x40, STDDEF, 1), (0x48, STDDEF, 2, END)],
                       [(0x08000000, HEAP, 1), (0x08000010, HEAP, 2, END)],
                       layout=layout)
        self.assertEqual(data['address_to_file'], {0x08000000: 'heap_4.c'})

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
        """0x112 lies between two heap_4.c sequences (0x113: Thumb)."""
        self.assertEqual(self.resolver._resolve_by_address(0x112), 'heap_4.c')
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

    def test_gap_distance_counts_from_the_sequence_end(self):
        """A long sequence whose last row is far back: 0x188 is 8 bytes past
        its end and 120 bytes past its last row."""
        data = run_cus([(0x100, HEAP, 10), (0x110, HEAP, 11), (0x180, HEAP, 12, END),
                        (0x190, HEAP, 20), (0x198, HEAP, 21, END)])
        self.assertEqual(resolver(data)._resolve_by_address(0x188), 'heap_4.c')

    def test_neighbours_ignore_a_nested_sequence(self):
        """A shorter sequence of another CU inside the earlier one does not
        hide the same-CU gap after it."""
        data = {'address_to_file': {0x100: 'heap_4.c', 0x104: 'stddef.h',
                                    0x10c: 'heap_4.c', 0x118: 'heap_4.c'},
                'line_sequences': [(0x100, 0x110, 0), (0x104, 0x108, 1),
                                   (0x118, 0x120, 0)]}
        self.assertEqual(resolver(data)._resolve_by_address(0x112), 'heap_4.c')

    def test_gap_prefers_the_cu_file_of_the_symbol_address(self):
        """The gap row is in a header; the symbol's own DIE names its .c."""
        data = run_cus([(0x100, STDDEF, 10), (0x110, STDDEF, 12, END),
                        (0x118, HEAP, 20), (0x120, HEAP, 21, END)])
        data['address_to_cu_file'] = {0x112: 'callbacks.c'}
        self.assertEqual(resolver(data)._resolve_by_address(0x112), 'callbacks.c')


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



class TestLayout(unittest.TestCase):
    """CodeLayout read from the ELF sections and symbol table."""

    def test_notype_label_at_zero_is_code(self):
        """Startup assembly without .type @function (STT_NOTYPE) at 0."""
        layout = CodeLayout.from_elf(fake_elf([FakeSymbol('_start', 'STT_NOTYPE', 0)]))
        self.assertTrue(layout.starts_code(0))
        data = run_cus([(0x0, HEAP, 1), (0x4, HEAP, 2), (0x10, HEAP, 3, END)], layout=layout)
        self.assertEqual(data['address_to_file'], {0x0: 'heap_4.c', 0x4: 'heap_4.c'})

    def test_thumb_function_at_zero_is_code(self):
        """A Thumb function at 0 has symbol value 1."""
        layout = CodeLayout.from_elf(fake_elf([FakeSymbol('Reset', 'STT_FUNC', 1)]))
        self.assertTrue(layout.starts_code(0))

    def test_mapping_and_undefined_symbols_are_not_code(self):
        """$t/$d mark instruction sets, not code starts."""
        layout = CodeLayout.from_elf(fake_elf([
            FakeSymbol('$t', 'STT_NOTYPE', 0), FakeSymbol('$d', 'STT_NOTYPE', 0),
            FakeSymbol('ext', 'STT_FUNC', 0, shndx='SHN_UNDEF'),
            FakeSymbol('data', 'STT_NOTYPE', 0x20000000)]))
        self.assertFalse(layout.starts_code(0))
        self.assertFalse(layout.starts_code(0x20000000))

    def test_only_executable_sections_are_code(self):
        """.data is allocated but not executable."""
        layout = CodeLayout.from_elf(fake_elf([], text=(0x08000000, 0x08001000)))
        self.assertTrue(layout.is_code(0x08000000))
        self.assertFalse(layout.is_code(0x08001000))
        self.assertFalse(layout.is_code(0x20000000))
        self.assertFalse(layout.is_code(0x0))


class TestLineStates(unittest.TestCase):
    """line_sequences reads states that leave out optional attributes."""

    def test_state_without_end_sequence_or_line(self):
        """A missing end_sequence means none; a missing line means 0."""
        entries = [SimpleNamespace(state=SimpleNamespace(address=0x100, file=0)),
                   SimpleNamespace(state=SimpleNamespace(address=0x104, file=0, line=5)),
                   SimpleNamespace(state=None)]
        self.assertEqual(list(line_sequences(entries, {0: 'a.c'})),
                         [(0x100, [(0x100, 'a.c', 0), (0x104, 'a.c', 5)], 0x105)])


if __name__ == '__main__':
    unittest.main()
