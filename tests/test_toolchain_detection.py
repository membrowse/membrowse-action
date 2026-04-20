#!/usr/bin/env python3
"""Unit tests for toolchain detection and upload-metadata plumbing."""

import unittest
from pathlib import Path

from elftools.elf.elffile import ELFFile

from membrowse.analysis.sections import SectionAnalyzer, _TOOLCHAIN_PATTERNS
from membrowse.commands.report import _build_enriched_report
from membrowse.core.generator import ReportGenerator


FIXTURES = Path(__file__).parent / 'fixtures'
STM32_ELF = FIXTURES / 'micropython' / 'stm32' / 'firmware.elf'
ESP32_ELF = FIXTURES / 'micropython' / 'esp32' / 'micropython.elf'


def _run_patterns(sample: bytes):
    """Run a sample through the detector's pattern table and return the
    resulting ``name-version`` string, or None if nothing matched."""
    for name, pattern in _TOOLCHAIN_PATTERNS:
        match = pattern.search(sample)
        if match:
            return f'{name}-{match.group(1).decode("ascii")}'
    return None


class TestToolchainPatterns(unittest.TestCase):
    """Regex-level checks for the detector's .comment patterns."""

    def test_gcc_with_parenthetical_prefix(self):
        """GCC entry with a parenthesized distributor prefix."""
        self.assertEqual(
            _run_patterns(b'GCC: (15:10.3-2021.07-4) 10.3.1 20210621 (release)'),
            'gcc-10.3.1')

    def test_gcc_crosstool_ng(self):
        """GCC entry produced by crosstool-NG (ESP-IDF style)."""
        self.assertEqual(
            _run_patterns(b'GCC: (crosstool-NG esp-14.2.0_20241119) 14.2.0'),
            'gcc-14.2.0')

    def test_gcc_simple(self):
        """GCC entry with the plain ``(GNU)`` distributor."""
        self.assertEqual(_run_patterns(b'GCC: (GNU) 12.2.0'), 'gcc-12.2.0')

    def test_clang_bare(self):
        """clang entry with no distributor prefix."""
        self.assertEqual(_run_patterns(b'clang version 15.0.7'), 'clang-15.0.7')

    def test_clang_distro_prefix(self):
        """clang entry carrying a distributor prefix (Ubuntu, etc.)."""
        self.assertEqual(
            _run_patterns(b'Ubuntu clang version 14.0.0-1ubuntu1'),
            'clang-14.0.0')

    def test_iar(self):
        """IAR ARM compiler .comment string."""
        self.assertEqual(
            _run_patterns(b'IAR ANSI C/C++ Compiler V9.40.1.375/W32 for ARM'),
            'iar-9.40.1')

    def test_rustc(self):
        """rustc's actual .comment format (no ``version`` keyword)."""
        self.assertEqual(
            _run_patterns(b'rustc 1.75.0 (82e1608df 2023-12-21)'),
            'rustc-1.75.0')

    def test_rustc_with_version_keyword(self):
        """rustc entry with an explicit ``version`` keyword, kept covered
        so the optional branch of the pattern isn't silently retired."""
        self.assertEqual(
            _run_patterns(b'rustc version 1.75.0'),
            'rustc-1.75.0')

    def test_unknown_returns_none(self):
        """Unrecognized .comment content produces no match."""
        self.assertIsNone(_run_patterns(b'some random bytes'))


class TestToolchainFromFixtures(unittest.TestCase):
    """End-to-end detection against real fixture ELFs."""

    def _detect(self, elf_path: Path):
        """Open ``elf_path`` and run the real SectionAnalyzer detector."""
        with open(elf_path, 'rb') as fh:
            return SectionAnalyzer(ELFFile(fh)).detect_toolchain()

    def test_stm32_fixture_is_gcc(self):
        """STM32 micropython fixture was built with arm-none-eabi-gcc 10.3.1."""
        self.assertTrue(STM32_ELF.exists(), f"missing fixture: {STM32_ELF}")
        self.assertEqual(self._detect(STM32_ELF), 'gcc-10.3.1')

    def test_esp32_fixture_is_gcc(self):
        """ESP32 fixture has multiple GCC .comment entries from crosstool-NG;
        the detector picks the first (the primary esp toolchain, 14.2.0)."""
        self.assertTrue(ESP32_ELF.exists(), f"missing fixture: {ESP32_ELF}")
        self.assertEqual(self._detect(ESP32_ELF), 'gcc-14.2.0')


class TestReportCarriesArchAndToolchain(unittest.TestCase):
    """The generator should emit ISA-valued architecture and toolchain."""

    def test_stm32_report(self):
        """STM32 fixture → architecture='ARM', toolchain='gcc-10.3.1'."""
        self.assertTrue(STM32_ELF.exists(), f"missing fixture: {STM32_ELF}")
        report = ReportGenerator(str(STM32_ELF)).generate_report()
        self.assertEqual(report['architecture'], 'ARM')
        self.assertEqual(report['toolchain'], 'gcc-10.3.1')

    def test_esp32_report(self):
        """ESP32 fixture → architecture='Xtensa', toolchain='gcc-14.2.0'."""
        self.assertTrue(ESP32_ELF.exists(), f"missing fixture: {ESP32_ELF}")
        report = ReportGenerator(str(ESP32_ELF)).generate_report()
        self.assertEqual(report['architecture'], 'Xtensa')
        self.assertEqual(report['toolchain'], 'gcc-14.2.0')


class TestEnrichedReportMetadata(unittest.TestCase):
    """_build_enriched_report must lift architecture/toolchain from the
    memory_analysis report into top-level metadata (where core reads them)."""

    def test_copies_architecture_and_toolchain(self):
        """Both fields land at metadata.architecture / metadata.toolchain."""
        report = {'architecture': 'ARM', 'toolchain': 'gcc-10.3.1'}
        enriched = _build_enriched_report(
            report,
            commit_info={'commit_hash': 'abc', 'repository': 'r'},
            target_name='stm32',
        )
        self.assertEqual(enriched['metadata']['architecture'], 'ARM')
        self.assertEqual(enriched['metadata']['toolchain'], 'gcc-10.3.1')
        self.assertIs(enriched['memory_analysis'], report)

    def test_missing_fields_become_none(self):
        """A report with no arch/toolchain surfaces as None in metadata."""
        enriched = _build_enriched_report(
            report={},
            commit_info={'commit_hash': 'abc', 'repository': 'r'},
            target_name='stm32',
        )
        self.assertIsNone(enriched['metadata']['architecture'])
        self.assertIsNone(enriched['metadata']['toolchain'])


if __name__ == '__main__':
    unittest.main()
