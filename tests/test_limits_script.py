#!/usr/bin/env python3
"""Tests for --limits: separate attribution + limits linker scripts.

Motivating bug: when a binary overflows a declared MEMORY region (the
linker placed sections past ``ORIGIN + LENGTH``), membrowse understates
the overflow because spilled sections fall outside every declared
address range and get treated as orphans. The fix decouples attribution
(address-based section classification) from limits (utilization
denominator): the attribution script may be inflated to swallow
overflow sections, and a separate limits script supplies the real
capacity for each region.
"""

import os
import tempfile
import unittest

from membrowse.commands.report import _resolve_real_limits
from membrowse.core.generator import ReportGenerator
from membrowse.core.models import MemoryRegion, MemorySection
from membrowse.analysis.mapper import MemoryMapper


FIXTURE_ELF = os.path.join(
    os.path.dirname(__file__),
    'fixtures', 'micropython', 'stm32', 'firmware.elf')


def _write_script(dir_path: str, name: str, content: str) -> str:
    """Write a linker script to a temp dir and return its path."""
    path = os.path.join(dir_path, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


class TestResolveRealLimits(unittest.TestCase):
    """``_resolve_real_limits`` merges the limits script onto the parsed
    attribution regions, enforcing ORIGIN agreement."""

    def test_swap_on_matching_region(self):
        """Matching region name + ORIGIN → real limit_size is returned."""
        with tempfile.TemporaryDirectory() as td:
            limits = _write_script(td, 'limits.ld', """
                MEMORY {
                    FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 256K
                }
            """)
            attribution = {
                'FLASH': {'address': 0x08000000,
                          'limit_size': 0x100000,  # 1 MB attribution
                          'end_address': 0x08100000 - 1,
                          'attributes': 'rx'},
            }
            real = _resolve_real_limits(limits, attribution, None, None)
            self.assertEqual(real, {'FLASH': 256 * 1024})

    def test_origin_mismatch_raises(self):
        """Attribution and limits disagree on ORIGIN → ValueError.
        Catches the user mixing up two unrelated builds."""
        with tempfile.TemporaryDirectory() as td:
            limits = _write_script(td, 'limits.ld', """
                MEMORY {
                    FLASH (rx) : ORIGIN = 0x08008000, LENGTH = 256K
                }
            """)
            attribution = {
                'FLASH': {'address': 0x08000000,
                          'limit_size': 0x100000,
                          'end_address': 0x08100000 - 1,
                          'attributes': 'rx'},
            }
            with self.assertRaises(ValueError) as ctx:
                _resolve_real_limits(limits, attribution, None, None)
            self.assertIn('ORIGIN mismatch', str(ctx.exception))
            self.assertIn('FLASH', str(ctx.exception))

    def test_region_missing_in_limits_keeps_attribution(self):
        """Region only in attribution → no swap for it (absent from result)."""
        with tempfile.TemporaryDirectory() as td:
            limits = _write_script(td, 'limits.ld', """
                MEMORY {
                    FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 256K
                }
            """)
            attribution = {
                'FLASH': {'address': 0x08000000, 'limit_size': 0x100000,
                          'end_address': 0x08100000 - 1, 'attributes': 'rx'},
                'RAM':   {'address': 0x20000000, 'limit_size': 0x20000,
                          'end_address': 0x20020000 - 1, 'attributes': 'rw'},
            }
            real = _resolve_real_limits(limits, attribution, None, None)
            self.assertIn('FLASH', real)
            self.assertNotIn('RAM', real)

    def test_region_missing_in_attribution_is_skipped(self):
        """Region only in limits → warn + skip (no crash)."""
        with tempfile.TemporaryDirectory() as td:
            limits = _write_script(td, 'limits.ld', """
                MEMORY {
                    FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 256K
                    EXTRA (rw) : ORIGIN = 0x30000000, LENGTH = 16K
                }
            """)
            attribution = {
                'FLASH': {'address': 0x08000000, 'limit_size': 0x100000,
                          'end_address': 0x08100000 - 1, 'attributes': 'rx'},
            }
            real = _resolve_real_limits(limits, attribution, None, None)
            self.assertEqual(real, {'FLASH': 256 * 1024})

    def test_limits_larger_than_attribution_warns(self):
        """limits > attribution is unusual but legal (smaller-than-built check)."""
        with tempfile.TemporaryDirectory() as td:
            limits = _write_script(td, 'limits.ld', """
                MEMORY {
                    FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 2M
                }
            """)
            attribution = {
                'FLASH': {'address': 0x08000000, 'limit_size': 0x100000,
                          'end_address': 0x08100000 - 1, 'attributes': 'rx'},
            }
            with self.assertLogs('membrowse.commands.report',
                                 level='WARNING') as logs:
                real = _resolve_real_limits(limits, attribution, None, None)
            self.assertEqual(real, {'FLASH': 2 * 1024 * 1024})
            self.assertTrue(any('larger than attribution' in m for m in logs.output))

    def test_no_limits_path_returns_none(self):
        """Omitting --limits is unchanged behavior: None signals 'no swap'."""
        self.assertIsNone(_resolve_real_limits(None, {'F': {}}, None, None))

    def test_missing_limits_file_raises(self):
        """Non-existent limits path → ValueError, not a silent skip."""
        with self.assertRaises(ValueError):
            _resolve_real_limits('/nonexistent.ld', {'F': {
                'address': 0, 'limit_size': 1}}, None, None)


class TestUtilizationSwap(unittest.TestCase):
    """The ``real_limits`` mapping replaces ``limit_size`` before
    ``calculate_utilization`` runs, so used/free/utilization reflect the
    real capacity while sections were attributed against the (wider)
    attribution range."""

    def test_overflow_section_counted_after_swap(self):
        """A section placed past the real region end is still attributed
        to the region (via wider attribution range), and utilization
        reports the overflow against the real limit."""
        # Attribution: FLASH spans 0x08000000..0x08100000 (1 MB wide)
        # Real limit:  256 KB
        # Section:     .overflow at 0x08050000, size 0x8000 — past the real
        #              256 KB end but inside the 1 MB attribution range.
        regions = {
            'FLASH': MemoryRegion(
                address=0x08000000, limit_size=0x100000, type='FLASH'),
        }
        sections = [
            MemorySection(name='.text',     address=0x08000000,
                          size=0x1000, type='code'),
            MemorySection(name='.overflow', address=0x08050000,
                          size=0x8000, type='code'),
        ]
        MemoryMapper.map_sections_to_regions(sections, regions)

        real_limits = {'FLASH': 256 * 1024}
        for name, real in real_limits.items():
            regions[name].limit_size = real
        MemoryMapper.calculate_utilization(regions)

        flash = regions['FLASH']
        self.assertEqual(flash.limit_size, 256 * 1024)
        # Both sections attributed:
        names = {s['name'] for s in flash.sections}
        self.assertEqual(names, {'.text', '.overflow'})
        # used == sum of both; free is negative (overflow).
        self.assertEqual(flash.used_size, 0x1000 + 0x8000)
        self.assertEqual(flash.free_size, 256 * 1024 - (0x1000 + 0x8000))
        self.assertGreater(flash.utilization_percent, 0)

    def test_lma_overflow_credited(self):
        """An AT()-placed section whose LMA lands past the real flash end
        but inside the wider attribution range must still be credited to
        flash (dual-attribution doesn't silently drop it)."""
        regions = {
            'FLASH': MemoryRegion(
                address=0x08000000, limit_size=0x100000, type='FLASH'),
            'RAM':   MemoryRegion(
                address=0x20000000, limit_size=0x20000, type='RAM'),
        }
        # .data runs in RAM (VMA) but its init image sits in flash (LMA)
        # past the real 256 KB limit, inside the 1 MB attribution range.
        data = MemorySection(
            name='.data', address=0x20000000, size=0x100, type='data',
            lma=0x08050000)
        MemoryMapper.map_sections_to_regions([data], regions)

        # Swap to the real (smaller) limit, recompute.
        regions['FLASH'].limit_size = 256 * 1024
        MemoryMapper.calculate_utilization(regions)

        flash_names = [s['name'] for s in regions['FLASH'].sections]
        self.assertIn('.data', flash_names)  # LMA attribution survived
        self.assertEqual(regions['FLASH'].used_size, 0x100)


class TestReportGeneratorLimitsSwap(unittest.TestCase):
    """``ReportGenerator(real_limits=...)`` plumbing: the swap happens
    between mapping and utilization, yielding post-swap denominators in
    the final report."""

    def _fixture(self):
        if not os.path.exists(FIXTURE_ELF):
            self.skipTest(f"Fixture ELF not found: {FIXTURE_ELF}")

    def test_swap_changes_only_the_denominator(self):
        """Swapping limit_size changes utilization math but not the set of
        attributed sections."""
        self._fixture()
        regions_data = {
            # Wide attribution: 1 MB flash, captures all of micropython's
            # .text/.isr_* sections (they end near 0x08075914).
            'FLASH': {'address': 0x08000000, 'limit_size': 0x100000,
                      'end_address': 0x08100000 - 1, 'attributes': 'rx'},
            'RAM':   {'address': 0x20000000, 'limit_size': 0x20000,
                      'end_address': 0x20020000 - 1, 'attributes': 'rw'},
        }

        baseline = ReportGenerator(FIXTURE_ELF, regions_data).generate_report()

        # Now impose a smaller real limit on FLASH. Used should be unchanged
        # (same sections attributed); limit shrinks; utilization rises.
        shrunken = ReportGenerator(
            FIXTURE_ELF, regions_data,
            real_limits={'FLASH': 0x80000},  # 512 KB
        ).generate_report()

        b = baseline['memory_layout']['FLASH']
        s = shrunken['memory_layout']['FLASH']
        self.assertEqual(b['used_size'], s['used_size'])
        self.assertEqual(s['limit_size'], 0x80000)
        self.assertGreater(s['utilization_percent'], b['utilization_percent'])
        self.assertEqual(s['free_size'], s['limit_size'] - s['used_size'])

    def test_no_real_limits_is_unchanged_behavior(self):
        """Omitting real_limits produces a report identical to the
        pre-feature code path (byte-for-byte on memory_layout)."""
        self._fixture()
        regions_data = {
            'FLASH': {'address': 0x08000000, 'limit_size': 0x100000,
                      'end_address': 0x08100000 - 1, 'attributes': 'rx'},
            'RAM':   {'address': 0x20000000, 'limit_size': 0x20000,
                      'end_address': 0x20020000 - 1, 'attributes': 'rw'},
        }
        with_none = ReportGenerator(
            FIXTURE_ELF, regions_data, real_limits=None).generate_report()
        with_empty = ReportGenerator(
            FIXTURE_ELF, regions_data, real_limits={}).generate_report()
        self.assertEqual(with_none['memory_layout'],
                         with_empty['memory_layout'])

    def test_real_limits_for_unknown_region_is_ignored(self):
        """A real_limits entry for a region that doesn't exist (e.g. the
        limits script had an extra region) must not crash or create
        phantom entries."""
        self._fixture()
        regions_data = {
            'FLASH': {'address': 0x08000000, 'limit_size': 0x100000,
                      'end_address': 0x08100000 - 1, 'attributes': 'rx'},
        }
        report = ReportGenerator(
            FIXTURE_ELF, regions_data,
            real_limits={'FLASH': 0x80000, 'NONEXISTENT': 999},
        ).generate_report()
        self.assertIn('FLASH', report['memory_layout'])
        self.assertNotIn('NONEXISTENT', report['memory_layout'])


if __name__ == '__main__':
    unittest.main()
