#!/usr/bin/env python3
"""
Tests for TinyGo firmware built with --emit-relocs (ARM) and for AVR,
whose DWARF uses 2 byte addresses that pyelftools cannot parse.

Fixtures are examples/blinky1 built with TinyGo 0.44.0 for pca10040 and
arduino.
"""

import unittest
from pathlib import Path

from elftools.elf.elffile import ELFFile

from membrowse.analysis.dwarf import _iter_cu_headers
from membrowse.core import ReportGenerator
from membrowse.linker.parser import LinkerScriptParser

FIXTURES = Path(__file__).parent / "fixtures" / "tinygo"
LINKER = FIXTURES / "linker"


def _generate(elf_name, scripts, defines=None):
    elf_path = str(FIXTURES / elf_name)
    regions = LinkerScriptParser(
        [str(LINKER / s) for s in scripts],
        elf_file=elf_path,
        user_variables=defines,
    ).parse_memory_regions()
    return ReportGenerator(elf_path, regions).generate_report()


class TestTinyGoARM(unittest.TestCase):
    """ARM ELF with R_ARM_NONE entries in .rel.debug_* sections"""

    def test_report_with_source_mapping(self):
        """Report succeeds and maps symbols to Go source files"""
        report = _generate("pca10040.elf", ["nrf52.ld", "arm.ld"])

        layout = report['memory_layout']
        self.assertEqual(layout['FLASH_TEXT']['used_size'], 4648)
        self.assertEqual(layout['RAM']['used_size'], 2276)

        symbols = {s['name']: s for s in report['symbols']}
        self.assertEqual(symbols['runtime.alloc']['source_file'], 'gc_blocks.go')

        # Globals at an offset inside LLVM merged globals
        self.assertEqual(
            symbols['internal/task.currentTask']['source_file'], 'task_stack_unicore.go')
        self.assertEqual(symbols['runtime.gcNumGC']['source_file'], 'gc_blocks.go')

        # TinyGo names every CU "<unknown>", which is not a source file
        self.assertFalse(any(s['source_file'] == '<unknown>' for s in report['symbols']))

    def test_address_sizes(self):
        """CU headers declare 4 byte addresses"""
        with open(FIXTURES / "pca10040.elf", 'rb') as f:
            dwarfinfo = ELFFile(f).get_dwarf_info(relocate_dwarf_sections=False)
            sizes = {h['address_size'] for _, h in _iter_cu_headers(dwarfinfo)}
            self.assertEqual(sizes, {4})


class TestTinyGoAVR(unittest.TestCase):
    """AVR ELF with 2 byte DWARF addresses"""

    def test_report_without_source_mapping(self):
        """Report succeeds with a warning and no source files"""
        with self.assertLogs('membrowse.analysis.dwarf', level='WARNING') as logs:
            report = _generate(
                "arduino.elf", ["atmega328p.ld", "avr.ld"],
                {'_bootloader_size': '512', '_stack_size': '512'})
        self.assertIn('unsupported address size 2', logs.output[0])

        layout = report['memory_layout']
        self.assertEqual(layout['FLASH_TEXT']['used_size'], 928)
        self.assertEqual(layout['RAM']['used_size'], 560)

        self.assertTrue(report['symbols'])
        self.assertTrue(all(not s['source_file'] for s in report['symbols']))

    def test_address_sizes(self):
        """CU headers declare 2 byte addresses"""
        with open(FIXTURES / "arduino.elf", 'rb') as f:
            dwarfinfo = ELFFile(f).get_dwarf_info()
            sizes = {h['address_size'] for _, h in _iter_cu_headers(dwarfinfo)}
            self.assertEqual(sizes, {2})


if __name__ == '__main__':
    unittest.main()
