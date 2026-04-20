#!/usr/bin/env python3
"""
Tests for dual VMA/LMA section attribution.

Sections placed via linker AT() (e.g. `.data : { ... } > RAM AT > FLASH`)
have distinct runtime (VMA) and storage (LMA) addresses. Their bytes cost
space in both regions — runtime working copy in RAM, init image in flash.
These tests verify the mapper credits both.
"""

import os
import unittest
from elftools.elf.elffile import ELFFile

from membrowse.analysis.sections import SectionAnalyzer
from membrowse.analysis.mapper import MemoryMapper
from membrowse.core.models import MemoryRegion, MemorySection


# STM32 MicroPython firmware: .data is placed with AT() so VMA is in SRAM
# (0x20000000) and LMA is in flash (0x08075914, size 0x34). .text has
# VMA == LMA, and .bss is SHT_NOBITS with no file image.
FIXTURE = os.path.join(
    os.path.dirname(__file__),
    'fixtures', 'micropython', 'stm32', 'firmware.elf')

DATA_VMA = 0x20000000
DATA_LMA = 0x08075914
DATA_SIZE = 0x34


class TestLmaComputation(unittest.TestCase):
    """SectionAnalyzer should compute LMA for AT()-placed sections."""

    def test_data_section_has_distinct_lma(self):
        """`.data` placed with AT() should carry its flash LMA."""
        with open(FIXTURE, 'rb') as f:
            elffile = ELFFile(f)
            sections = SectionAnalyzer(elffile).analyze_sections()

        by_name = {s.name: s for s in sections}

        data = by_name['.data']
        self.assertEqual(data.address, DATA_VMA)
        self.assertEqual(data.lma, DATA_LMA)

        # .text is flash-resident with VMA == LMA — no split to track.
        self.assertIsNone(by_name['.text'].lma)

        # .bss is SHT_NOBITS — no file image, so no LMA.
        self.assertIsNone(by_name['.bss'].lma)


class TestDualAttribution(unittest.TestCase):
    """MemoryMapper should credit AT()-placed sections to both regions."""

    def _run(self):
        """Analyze the fixture and map its sections to FLASH/RAM regions."""
        with open(FIXTURE, 'rb') as f:
            elffile = ELFFile(f)
            sections = SectionAnalyzer(elffile).analyze_sections()

        regions = {
            'FLASH': MemoryRegion(
                address=0x08000000, limit_size=0x100000, type='FLASH'),
            'RAM': MemoryRegion(
                address=0x20000000, limit_size=0x20000, type='RAM'),
        }
        MemoryMapper.map_sections_to_regions(sections, regions)
        MemoryMapper.calculate_utilization(regions)
        return regions

    def test_data_appears_in_both_regions(self):
        """`.data` must appear once in FLASH (at LMA) and once in RAM (at VMA)."""
        regions = self._run()
        flash_data = [s for s in regions['FLASH'].sections
                      if s['name'] == '.data']
        ram_data = [s for s in regions['RAM'].sections
                    if s['name'] == '.data']

        self.assertEqual(len(flash_data), 1)
        self.assertEqual(len(ram_data), 1)

        # Addresses disambiguate the two entries.
        self.assertEqual(flash_data[0]['address'], DATA_LMA)
        self.assertEqual(ram_data[0]['address'], DATA_VMA)
        self.assertEqual(flash_data[0]['size'], DATA_SIZE)
        self.assertEqual(ram_data[0]['size'], DATA_SIZE)

    def test_used_size_includes_data_in_both_regions(self):
        """Both FLASH and RAM totals must include .data's bytes."""
        regions = self._run()

        flash_names = {s['name'] for s in regions['FLASH'].sections}
        ram_names = {s['name'] for s in regions['RAM'].sections}
        self.assertIn('.data', flash_names)
        self.assertIn('.data', ram_names)

        flash_sum = sum(s['size'] for s in regions['FLASH'].sections)
        ram_sum = sum(s['size'] for s in regions['RAM'].sections)
        self.assertEqual(regions['FLASH'].used_size, flash_sum)
        self.assertEqual(regions['RAM'].used_size, ram_sum)

    def test_bss_only_in_ram(self):
        """NOBITS sections have no file image, so no LMA attribution."""
        regions = self._run()
        flash_names = [s['name'] for s in regions['FLASH'].sections]
        ram_names = [s['name'] for s in regions['RAM'].sections]
        self.assertNotIn('.bss', flash_names)
        self.assertIn('.bss', ram_names)

    def test_section_entries_have_no_lma_key(self):
        """Schema preservation: section dicts must not leak the internal
        `lma` field added to MemorySection."""
        regions = self._run()
        for region in regions.values():
            for entry in region.sections:
                self.assertNotIn('lma', entry,
                                 f"section {entry['name']} leaked 'lma'")


class TestIdempotentLmaAttribution(unittest.TestCase):
    """A second map_sections_to_regions call (e.g. after region inference
    runs on unmapped sections) must not double-credit the LMA image."""

    def test_second_pass_does_not_double_credit(self):
        """Calling the mapper twice on the same section list must still
        produce a single LMA entry in the flash region."""
        section = MemorySection(
            name='.data', address=0x20000000, size=0x100, type='data',
            lma=0x08004000)
        regions = {
            'FLASH': MemoryRegion(
                address=0x08000000, limit_size=0x100000, type='FLASH'),
            'RAM': MemoryRegion(
                address=0x20000000, limit_size=0x20000, type='RAM'),
        }
        MemoryMapper.map_sections_to_regions([section], regions)
        # Simulate the generator's retry path on the same section list.
        MemoryMapper.map_sections_to_regions([section], regions)

        flash_data = [s for s in regions['FLASH'].sections
                      if s['name'] == '.data']
        self.assertEqual(len(flash_data), 1,
                         "LMA attribution must be idempotent across retries")


class TestNoLmaWhenEqual(unittest.TestCase):
    """When VMA == LMA, no dual attribution should happen."""

    def test_no_duplicate_for_flash_only_section(self):
        """A section without a distinct LMA must appear in exactly one region."""
        sections = [
            MemorySection(
                name='.text', address=0x08000000, size=0x1000, type='code'),
        ]
        regions = {
            'FLASH': MemoryRegion(
                address=0x08000000, limit_size=0x100000, type='FLASH'),
        }
        MemoryMapper.map_sections_to_regions(sections, regions)
        text_entries = [s for s in regions['FLASH'].sections
                        if s['name'] == '.text']
        self.assertEqual(len(text_entries), 1)


if __name__ == '__main__':
    unittest.main()
