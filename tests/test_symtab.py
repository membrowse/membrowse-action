#!/usr/bin/env python3
"""
The symbol table parsed once per ELF file (analysis/symtab.py).
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection

from membrowse.analysis.symtab import symtab_symbols

ELF = Path(__file__).parent / "fixtures" / "tinyusb" / "stm32f407disco" / "cdc_msc.elf"


class TestSymtabSymbols(unittest.TestCase):
    """symtab_symbols"""

    def test_parsed_once_per_elf(self):
        """Later calls for the same ELFFile reuse the first list"""
        with open(ELF, 'rb') as f, mock.patch.object(
                SymbolTableSection, 'iter_symbols', autospec=True,
                side_effect=SymbolTableSection.iter_symbols) as iter_symbols:
            elffile = ELFFile(f)
            first = symtab_symbols(elffile)
            second = symtab_symbols(elffile, elffile.get_section_by_name('.symtab'))
            self.assertIs(first, second)
            self.assertEqual(iter_symbols.call_count, 1)
            self.assertIn('main', {s.name for s in first})

            symtab_symbols(ELFFile(f))  # another ELFFile parses again
            self.assertEqual(iter_symbols.call_count, 2)

    def test_no_symtab(self):
        """None when the ELF has no .symtab"""
        elffile = mock.Mock()
        elffile.get_section_by_name.return_value = None
        self.assertIsNone(symtab_symbols(elffile))

    def test_uncacheable_elf(self):
        """Objects without weak references are read every time"""
        section = SimpleNamespace(iter_symbols=lambda: iter(['a', 'b']))
        elffile = 0  # ints are not weak-referenceable
        self.assertEqual(symtab_symbols(elffile, section), ['a', 'b'])
        self.assertEqual(symtab_symbols(elffile, section), ['a', 'b'])


if __name__ == '__main__':
    unittest.main()
