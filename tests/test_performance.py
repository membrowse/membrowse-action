#!/usr/bin/env python3
"""
Report generation time on the Meshtastic picow fixture (30013 symbols).

pyelftools parses every symbol again on each pass over the symbol table, at
about 1 s a pass for this firmware. v1.2.17 read it twice and #198 added a
third pass (CodeLayout.from_elf): `membrowse report` went from 6.5 s to
7.7 s. The symbols are now parsed once and shared (analysis/symtab.py).

The pass count is checked everywhere. Wall-clock time depends on the
machine and is checked only with MEMBROWSE_PERF=1, against
MEMBROWSE_PERF_BUDGET seconds. The default, 6.5, lies between the fastest
of 3 in-process runs of v1.2.17 (5.7 s) and of #198 (7.3 s) on the machine
the fixture was added on.
"""

import os
import time
import unittest
from pathlib import Path
from unittest import mock

from elftools.elf.sections import SymbolTableSection

from membrowse.core import ReportGenerator
from membrowse.linker.parser import LinkerScriptParser

FIXTURE = Path(__file__).parent / "fixtures" / "meshtastic" / "picow"
ELF = str(FIXTURE / "firmware.elf")
MAX_SYMBOL_TABLE_PASSES = 1


def _generate():
    regions = LinkerScriptParser(
        [str(FIXTURE / "memmap_default.ld")], elf_file=ELF).parse_memory_regions()
    return ReportGenerator(
        ELF, regions, map_file_path=str(FIXTURE / "firmware.map")).generate_report()


class TestReportPerformance(unittest.TestCase):
    """Report generation cost on a large firmware"""

    def test_symbol_table_passes(self):
        """The symbol table is parsed once"""
        passes = []
        iter_symbols = SymbolTableSection.iter_symbols

        def counting(section):
            if section.name == '.symtab':
                passes.append(section.name)
            return iter_symbols(section)

        with mock.patch.object(SymbolTableSection, 'iter_symbols', counting):
            _generate()
        self.assertLessEqual(len(passes), MAX_SYMBOL_TABLE_PASSES)

    @unittest.skipUnless(os.environ.get('MEMBROWSE_PERF') == '1',
                         'set MEMBROWSE_PERF=1 to check report time')
    def test_report_time(self):
        """Fastest of 3 reports within MEMBROWSE_PERF_BUDGET seconds"""
        budget = float(os.environ.get('MEMBROWSE_PERF_BUDGET', '6.5'))
        times = []
        for _ in range(3):
            start = time.perf_counter()
            _generate()
            times.append(time.perf_counter() - start)
        self.assertLessEqual(
            min(times), budget,
            f'report took {min(times):.2f} s (runs: '
            f'{", ".join(f"{t:.2f}" for t in times)}), budget {budget} s')


if __name__ == '__main__':
    unittest.main()
