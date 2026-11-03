#!/usr/bin/env python3
"""
Tests for --exclude-alignment: padding from explicit ``. = ALIGN(n)``
statements is taken off section sizes.

The fixture in ``tests/fixtures/alignment`` (rebuilt by its ``build.sh``)
models Trezor's firmware.ld: ``.kernel`` holds an embedded image padded to
8 KB, ``.reserved`` has a reservation directly above an ALIGN, ``.flash``
ends with symbol-less string literals and ``ALIGN(512)``, ``.data`` ends
with ``ALIGN(512)``, and ``.stack`` is a pure reservation.
"""

import argparse
import os
import tempfile
import unittest
from unittest import mock

from elftools.elf.elffile import ELFFile

from membrowse.analysis.alignment import (
    detect_alignment_padding,
    estimate_alignment_padding,
    exclude_padding,
)
from membrowse.analysis.ldmap_parser import MapFileParser
from membrowse.analysis.lldmap_parser import LLDMapFileParser
from membrowse.commands.onboard import add_onboard_parser
from membrowse.commands.report import add_report_parser, generate_report
from membrowse.core.models import MemorySection

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), 'fixtures', 'alignment')
ELF = os.path.join(FIXTURE_DIR, 'fw.elf')
MAP = os.path.join(FIXTURE_DIR, 'fw.map')
LD = os.path.join(FIXTURE_DIR, 'fw.ld')
LLD_ELF = os.path.join(FIXTURE_DIR, 'fw-lld.elf')
LLD_MAP = os.path.join(FIXTURE_DIR, 'fw-lld.map')

# Fill below each ALIGN line in fw.map.
MAP_PADDING = {
    '.kernel': 0x1edd,
    '.reserved': 0x1fc,
    '.flash': 0x19b,
    '.data': 0x1f0,
}


# Size of each ALIGN row in fw-lld.map (clang's code differs from gcc's).
LLD_MAP_PADDING = {
    '.kernel': 0x1edd,
    '.reserved': 0x1ec,
    '.flash': 0x171,
    '.data': 0x1f0,
}


def _read_map(path=MAP):
    with open(path, encoding='utf-8') as f:
        return f.read()


class TestMapAlignmentFill(unittest.TestCase):
    """MapFileParser.alignment_fill reads the fill below ALIGN lines."""

    def test_fixture(self):
        """Every ALIGN fill in the fixture map, and nothing else."""
        self.assertEqual(MapFileParser.alignment_fill(_read_map()),
                         MAP_PADDING)

    def test_reservation_above_align_is_not_padding(self):
        """Trezor kernel.map: the 0x400 fill belongs to the reservation,
        and the ALIGN below it produced no fill."""
        content = (
            ".flash          0x0c050200    0x10600\n"
            "                0x0c050600                . = (. + 0x400)\n"
            " *fill*         0x0c050200      0x400 \n"
            "                0x0c050600                . = ALIGN (CODE_ALIGNMENT)\n"
            " .text          0x0c050600      0x10200 kernel.o\n"
        )
        self.assertEqual(MapFileParser.alignment_fill(content), {})

    def test_object_alignment_fill_is_not_padding(self):
        """Fill between input sections stays part of the section."""
        content = (
            ".text           0x08000000      0x210\n"
            " .text.a        0x08000000        0xe a.o\n"
            " *fill*         0x0800000e        0x2 \n"
            " .text.b        0x08000010        0x8 b.o\n"
            "                0x08000200                . = ALIGN (0x200)\n"
            " *fill*         0x08000018      0x1e8 \n"
        )
        self.assertEqual(MapFileParser.alignment_fill(content),
                         {'.text': 0x1e8})

    def test_wrapped_header_and_fill_pattern(self):
        """A long output section name wraps; a fill pattern may follow."""
        content = (
            ".a_very_long_output_section_name\n"
            "                0x08000000      0x200\n"
            " .text.a        0x08000000       0x10 a.o\n"
            "                0x08000200                . = ALIGN (., 0x200)\n"
            " *fill*         0x08000010      0x1f0 ffffffff\n"
        )
        self.assertEqual(MapFileParser.alignment_fill(content),
                         {'.a_very_long_output_section_name': 0x1f0})

    def test_fill_is_attributed_to_its_own_section(self):
        """An ALIGN at the end of one section is not carried into the next."""
        content = (
            ".text           0x08000000      0x200\n"
            "                0x08000200                . = ALIGN (0x200)\n"
            ".data           0x20000000        0x8\n"
            " *fill*         0x20000000        0x8 \n"
        )
        self.assertEqual(MapFileParser.alignment_fill(content), {})


class TestLldMapAlignmentFill(unittest.TestCase):
    """LLDMapFileParser.alignment_fill reads the size of ALIGN rows."""

    def test_fixture(self):
        """Every ALIGN row in the fixture map, and nothing else: the
        reservation row in .reserved and the .stack reservation are kept."""
        self.assertEqual(
            LLDMapFileParser.alignment_fill(_read_map(LLD_MAP)),
            LLD_MAP_PADDING)

    def test_align_between_sections_pads_no_section(self):
        """A top-level ALIGN is a gap between sections, not padding."""
        content = (
            "     VMA      LMA     Size Align Out     In      Symbol\n"
            " 8000000  8000000       10     4 .text\n"
            " 8000000  8000000       10     4         a.o:(.text)\n"
            " 8000010  8000010      1f0     1 . = ALIGN ( 0x200 )\n"
            " 8000200  8000200        4     4 .rodata\n"
            " 8000200  8000200        4     4         a.o:(.rodata)\n"
        )
        self.assertEqual(LLDMapFileParser.alignment_fill(content), {})


class TestElfEstimate(unittest.TestCase):
    """estimate_alignment_padding works from the ELF alone."""

    def _estimate(self):
        with open(ELF, 'rb') as f:
            return estimate_alignment_padding(ELFFile(f))

    def test_fixture(self):
        """Labelled image, code and data are found; reservations are not."""
        padding = self._estimate()
        self.assertEqual(padding['.kernel'], MAP_PADDING['.kernel'])
        self.assertEqual(padding['.data'], MAP_PADDING['.data'])
        # The last string literal's NUL terminator looks like zero fill.
        self.assertEqual(padding['.flash'], MAP_PADDING['.flash'] + 1)
        # No label marks where .reserved's content ends, and .stack is a
        # NOBITS reservation: neither may be taken for padding.
        self.assertNotIn('.reserved', padding)
        self.assertNotIn('.stack', padding)


class TestDetect(unittest.TestCase):
    """detect_alignment_padding picks the map or falls back to the ELF."""

    def _detect(self, map_path):
        with open(ELF, 'rb') as f:
            return detect_alignment_padding(ELFFile(f), map_path)

    def test_gnu_ld_map_is_exact(self):
        """A GNU LD map gives the exact fill, without a warning."""
        with mock.patch('membrowse.analysis.alignment.logger') as logger:
            self.assertEqual(self._detect(MAP), MAP_PADDING)
        logger.warning.assert_not_called()

    def test_no_map_falls_back_with_warning(self):
        """Without a map, the ELF estimate is used and a warning logged."""
        with self.assertLogs('membrowse.analysis.alignment',
                             'WARNING') as logs:
            padding = self._detect(None)
        self.assertIn('no map file given', logs.output[0])
        self.assertEqual(padding['.kernel'], MAP_PADDING['.kernel'])

    def test_unreadable_map_falls_back(self):
        """A map that cannot be read falls back to the ELF estimate."""
        with self.assertLogs('membrowse.analysis.alignment',
                             'WARNING') as logs:
            padding = self._detect(os.path.join(FIXTURE_DIR, 'missing.map'))
        self.assertIn('cannot read map file', logs.output[0])
        self.assertIn('.data', padding)

    def test_lld_map_is_exact(self):
        """An LLD map gives the exact fill, without a warning."""
        with open(LLD_ELF, 'rb') as f, mock.patch(
                'membrowse.analysis.alignment.logger') as logger:
            padding = detect_alignment_padding(ELFFile(f), LLD_MAP)
        self.assertEqual(padding, LLD_MAP_PADDING)
        logger.warning.assert_not_called()

    def test_iar_map_has_no_padding(self):
        """An IAR map: nothing to exclude, and no ELF guess."""
        with tempfile.NamedTemporaryFile(
                'w', suffix='.map', delete=False) as f:
            f.write("*** PLACEMENT SUMMARY\n")
            path = f.name
        try:
            with mock.patch('membrowse.analysis.alignment.logger') as logger:
                padding = self._detect(path)
        finally:
            os.unlink(path)
        self.assertEqual(padding, {})
        logger.warning.assert_not_called()

    def test_iar_toolchain_without_map_has_no_padding(self):
        """An IAR-built ELF without a map: nothing to exclude."""
        with open(ELF, 'rb') as f, mock.patch(
                'membrowse.analysis.alignment.logger') as logger:
            padding = detect_alignment_padding(
                ELFFile(f), None, toolchain='iar-9.40.1')
        self.assertEqual(padding, {})
        logger.warning.assert_not_called()


class TestExcludePadding(unittest.TestCase):
    """exclude_padding shrinks sections, keeping their addresses."""

    def test_shrinks_and_clamps(self):
        """Padding comes off the size; it never exceeds the section."""
        sections = [
            MemorySection(name='.flash', address=0x1000, size=0x200,
                          type='code'),
            MemorySection(name='.tiny', address=0x2000, size=0x10,
                          type='rodata'),
            MemorySection(name='.bss', address=0x3000, size=0x40,
                          type='data'),
        ]
        result, excluded = exclude_padding(
            sections, {'.flash': 0x1f0, '.tiny': 0x100})
        by_name = {s.name: s for s in result}
        self.assertEqual(by_name['.flash'].size, 0x10)
        self.assertEqual(by_name['.flash'].address, 0x1000)
        self.assertEqual(by_name['.flash'].end_address, 0x1010)
        self.assertEqual(by_name['.tiny'].size, 0)
        self.assertEqual(by_name['.bss'].size, 0x40)
        self.assertEqual(excluded, {'.flash': 0x1f0, '.tiny': 0x10})
        # The input sections are left untouched.
        self.assertEqual(sections[0].size, 0x200)


class TestReport(unittest.TestCase):
    """generate_report applies the padding only with exclude_alignment."""

    @staticmethod
    def _used(report):
        return {name: region['used_size']
                for name, region in report['memory_layout'].items()}

    def test_off_by_default(self):
        """Without the flag, padding stays counted even with a map file."""
        report = generate_report(ELF, LD, map_file=MAP)
        self.assertEqual(self._used(report),
                         {'FLASH': 0x2a00, 'RAM': 0xa00})

    def test_map_file_exclusion(self):
        """With the flag and a map, every ALIGN fill is taken off."""
        report = generate_report(ELF, LD, map_file=MAP,
                                 exclude_alignment=True)
        flash_padding = sum(MAP_PADDING.values())  # .data counts in both
        self.assertEqual(self._used(report), {
            'FLASH': 0x2a00 - flash_padding,
            'RAM': 0xa00 - MAP_PADDING['.data'],
        })
        flash = {s['name']: s for s in
                 report['memory_layout']['FLASH']['sections']}
        self.assertEqual(flash['.kernel']['size'], 0x123)
        self.assertEqual(flash['.kernel']['end_address'], 0x08000123)

    def test_lld_map_file_exclusion(self):
        """With the flag and an LLD map, every ALIGN row is taken off."""
        plain = generate_report(LLD_ELF, LD, map_file=LLD_MAP)
        excluded = generate_report(LLD_ELF, LD, map_file=LLD_MAP,
                                   exclude_alignment=True)
        self.assertEqual(
            self._used(plain)['FLASH'] - self._used(excluded)['FLASH'],
            sum(LLD_MAP_PADDING.values()))
        self.assertEqual(
            self._used(plain)['RAM'] - self._used(excluded)['RAM'],
            LLD_MAP_PADDING['.data'])

    def test_default_regions(self):
        """Without linker scripts, the default regions exclude it too."""
        plain = generate_report(ELF, map_file=MAP)
        excluded = generate_report(ELF, map_file=MAP, exclude_alignment=True)
        self.assertEqual(
            sum(self._used(plain).values())
            - sum(self._used(excluded).values()),
            # .data appears once in the default regions
            sum(MAP_PADDING.values()))


class TestCliFlag(unittest.TestCase):
    """--exclude-alignment is accepted by report and onboard."""

    def _parse(self, add_parser, argv):
        parser = argparse.ArgumentParser()
        add_parser(parser.add_subparsers(dest='command'))
        return parser.parse_args(argv)

    def test_report(self):
        """report: off by default, on with the flag."""
        self.assertFalse(self._parse(
            add_report_parser, ['report', ELF]).exclude_alignment)
        self.assertTrue(self._parse(
            add_report_parser,
            ['report', ELF, '--exclude-alignment']).exclude_alignment)

    def test_onboard(self):
        """onboard: off by default, on with the flag."""
        base = ['onboard', '5', 'make', ELF, 'tgt', 'key']
        self.assertFalse(self._parse(
            add_onboard_parser, base).exclude_alignment)
        self.assertTrue(self._parse(
            add_onboard_parser,
            base + ['--exclude-alignment']).exclude_alignment)


if __name__ == '__main__':
    unittest.main()
