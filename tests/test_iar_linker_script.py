#!/usr/bin/env python3

"""
test_iar_linker_script.py - Tests for IAR linker configuration file (.icf) parsing.

Covers:
  - Real-world STM32F407 .icf file (from STMicroelectronics cmsis-device-f4)
  - from...to and from...size region syntax
  - define symbol variable resolution
  - if/else/endif conditionals with isdefinedsymbol()
  - include directive support
  - Region set operations (union, difference, intersection)
  - Size suffixes (K, M, G)
  - Bitwise expressions in addresses
  - Format detection (content-based)
  - Integration through LinkerScriptParser (transparent dispatch)
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from membrowse.linker.parser import LinkerScriptParser, LinkerScriptError
from membrowse.linker.icf_parser import (
    ICFSymbolTable,
    ICFEvaluationError,
)
from membrowse.linker.base import LinkerFormatDetector


TESTS_DIR = Path(__file__).parent
ICF_FILE = TESTS_DIR / "linker_scripts" / "stm32f407xx_flash.icf"


class _ICFTestBase(unittest.TestCase):
    """Shared setup for ICF parser tests requiring temporary .icf files."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.temp_files = []

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_icf(self, content, filename=None):
        if filename is None:
            filename = f"test_{len(self.temp_files)}.icf"
        path = self.temp_dir / filename
        path.write_text(content, encoding='utf-8')
        self.temp_files.append(path)
        return str(path)


class TestIARLinkerScript(unittest.TestCase):
    """Test parsing of a real STM32F407 .icf file via LinkerScriptParser."""

    def test_iar_icf_parses_memory_regions(self):
        """Parser should extract memory regions from an IAR .icf file."""
        parser = LinkerScriptParser(ld_scripts=[str(ICF_FILE)])
        regions = parser.parse_memory_regions()

        self.assertGreater(len(regions), 0,
                           "Parser should extract at least one memory region")

        expected_regions = {
            "ROM_region": {"address": 0x08000000, "size": 0x100000},
            "RAM_region": {"address": 0x20000000, "size": 0x20000},
            "CCMRAM_region": {"address": 0x10000000, "size": 0x10000},
        }

        for region_name, expected in expected_regions.items():
            self.assertIn(region_name, regions,
                          f"Expected '{region_name}' not found. Got: {list(regions.keys())}")
            region = regions[region_name]
            self.assertEqual(region["address"], expected["address"],
                             f"{region_name} address mismatch")
            self.assertEqual(region["limit_size"], expected["size"],
                             f"{region_name} size mismatch")

    def test_output_dict_has_required_keys(self):
        """All regions should have attributes, address, end_address, limit_size."""
        parser = LinkerScriptParser(ld_scripts=[str(ICF_FILE)])
        regions = parser.parse_memory_regions()

        for name, region in regions.items():
            for key in ("attributes", "address", "end_address", "limit_size"):
                self.assertIn(key, region,
                              f"Region '{name}' missing key '{key}'")
            self.assertEqual(region["end_address"],
                             region["address"] + region["limit_size"] - 1,
                             f"Region '{name}' end_address mismatch")


class TestICFFormatDetection(unittest.TestCase):
    """Test content-based format detection."""

    def test_detects_icf_content(self):
        """ICF content with define memory/region should be detected."""
        content = """
        define symbol __ROM_start__ = 0x08000000;
        define memory mem with size = 4G;
        define region ROM = mem:[from __ROM_start__ to 0x0807FFFF];
        """
        self.assertTrue(LinkerFormatDetector.is_icf(content))

    def test_rejects_gnu_ld_content(self):
        """GNU LD content should not be detected as ICF."""
        content = """
        MEMORY {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512K
            RAM (rwx) : ORIGIN = 0x20000000, LENGTH = 128K
        }
        """
        self.assertFalse(LinkerFormatDetector.is_icf(content))

    def test_requires_multiple_markers(self):
        """A single ICF keyword should not trigger detection."""
        content = """
        /* some comment mentioning 'define symbol' */
        __define = 1;
        """
        self.assertFalse(LinkerFormatDetector.is_icf(content))


class TestICFFromToRegions(_ICFTestBase):
    """Test from...to and from...size region syntax."""

    def test_from_to_syntax(self):
        """define region X = mem:[from ADDR to ADDR] with inclusive end."""
        script = self._write_icf("""
        define symbol __start__ = 0x08000000;
        define symbol __end__   = 0x0807FFFF;
        define memory mem with size = 4G;
        define region ROM = mem:[from __start__ to __end__];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertIn("ROM", regions)
        self.assertEqual(regions["ROM"]["address"], 0x08000000)
        self.assertEqual(regions["ROM"]["limit_size"], 0x80000)  # 512 KB

    def test_from_size_syntax(self):
        """define region X = mem:[from ADDR size SIZE]."""
        script = self._write_icf("""
        define memory mem with size = 4G;
        define region RAM = mem:[from 0x20000000 size 0x20000];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertIn("RAM", regions)
        self.assertEqual(regions["RAM"]["address"], 0x20000000)
        self.assertEqual(regions["RAM"]["limit_size"], 0x20000)

    def test_size_suffix_in_region(self):
        """K/M/G suffixes should work in region definitions."""
        script = self._write_icf("""
        define memory mem with size = 4G;
        define region FLASH = mem:[from 0x08000000 size 256K];
        define region SRAM  = mem:[from 0x20000000 size 1M];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertEqual(regions["FLASH"]["limit_size"], 256 * 1024)
        self.assertEqual(regions["SRAM"]["limit_size"], 1024 * 1024)

    def test_inline_hex_addresses(self):
        """Hex addresses directly in mem:[] without symbol references."""
        script = self._write_icf("""
        define memory mem with size = 4G;
        define region ROM = mem:[from 0x08000000 to 0x080FFFFF];
        define region RAM = mem:[from 0x20000000 to 0x2001FFFF];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertEqual(regions["ROM"]["address"], 0x08000000)
        self.assertEqual(regions["ROM"]["limit_size"], 0x100000)
        self.assertEqual(regions["RAM"]["address"], 0x20000000)
        self.assertEqual(regions["RAM"]["limit_size"], 0x20000)


class TestICFConditionals(_ICFTestBase):
    """Test if/else/endif conditional processing."""

    def test_isdefinedsymbol_true_branch(self):
        """When symbol is defined, take the true branch."""
        script = self._write_icf("""
        define symbol __USE_LARGE_RAM__ = 1;
        define memory mem with size = 4G;
        if (isdefinedsymbol(__USE_LARGE_RAM__)) {
            define region RAM = mem:[from 0x20000000 size 0x40000];
        } else {
            define region RAM = mem:[from 0x20000000 size 0x20000];
        }
        define region ROM = mem:[from 0x08000000 size 0x100000];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertEqual(regions["RAM"]["limit_size"], 0x40000)  # 256 KB

    def test_isdefinedsymbol_false_branch(self):
        """When symbol is not defined, take the else branch."""
        script = self._write_icf("""
        define memory mem with size = 4G;
        if (isdefinedsymbol(__USE_LARGE_RAM__)) {
            define region RAM = mem:[from 0x20000000 size 0x40000];
        } else {
            define region RAM = mem:[from 0x20000000 size 0x20000];
        }
        define region ROM = mem:[from 0x08000000 size 0x100000];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertEqual(regions["RAM"]["limit_size"], 0x20000)  # 128 KB

    def test_nested_conditionals(self):
        """Nested if/else blocks should work."""
        script = self._write_icf("""
        define symbol __BOOTLOADER__ = 1;
        define symbol __LARGE__ = 1;
        define memory mem with size = 4G;
        if (isdefinedsymbol(__BOOTLOADER__)) {
            if (isdefinedsymbol(__LARGE__)) {
                define region ROM = mem:[from 0x08010000 size 0xF0000];
            } else {
                define region ROM = mem:[from 0x08010000 size 0x70000];
            }
        } else {
            define region ROM = mem:[from 0x08000000 size 0x100000];
        }
        define region RAM = mem:[from 0x20000000 size 0x20000];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertEqual(regions["ROM"]["address"], 0x08010000)
        self.assertEqual(regions["ROM"]["limit_size"], 0xF0000)

    def test_else_if_chain(self):
        """'else if' pattern should be handled correctly."""
        script = self._write_icf("""
        define symbol __MODE__ = 2;
        define memory mem with size = 4G;
        if (__MODE__ == 1) {
            define region ROM = mem:[from 0x08000000 size 0x40000];
        } else if (__MODE__ == 2) {
            define region ROM = mem:[from 0x08000000 size 0x80000];
        } else {
            define region ROM = mem:[from 0x08000000 size 0x100000];
        }
        define region RAM = mem:[from 0x20000000 size 0x20000];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertEqual(regions["ROM"]["limit_size"], 0x80000)  # Mode 2

    def test_else_if_first_branch_true(self):
        """When the first if is true, else-if branches should not be used."""
        script = self._write_icf("""
        define symbol __MODE__ = 1;
        define memory mem with size = 4G;
        if (__MODE__ == 1) {
            define region ROM = mem:[from 0x08000000 size 0x40000];
        } else if (__MODE__ == 2) {
            define region ROM = mem:[from 0x08000000 size 0x80000];
        }
        define region RAM = mem:[from 0x20000000 size 0x20000];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertEqual(regions["ROM"]["limit_size"], 0x40000)  # Mode 1

    def test_else_if_true_preserves_trailing_content(self):
        """Regions defined after an else-if chain must not be dropped.

        Regression test: the else-if handler was setting after_end to
        len(content), which discards everything after the chain when the
        first branch is taken.
        """
        script = self._write_icf("""
        define symbol __MODE__ = 1;
        define memory mem with size = 4G;
        if (__MODE__ == 1) {
            define region ROM = mem:[from 0x08000000 size 0x40000];
        } else if (__MODE__ == 2) {
            define region ROM = mem:[from 0x08000000 size 0x80000];
        }
        define region RAM = mem:[from 0x20000000 size 0x20000];
        define region CCMRAM = mem:[from 0x10000000 size 0x10000];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertEqual(regions["ROM"]["limit_size"], 0x40000)
        self.assertIn("RAM", regions,
                       "RAM region after else-if chain was dropped")
        self.assertEqual(regions["RAM"]["address"], 0x20000000)
        self.assertEqual(regions["RAM"]["limit_size"], 0x20000)
        self.assertIn("CCMRAM", regions,
                       "CCMRAM region after else-if chain was dropped")
        self.assertEqual(regions["CCMRAM"]["address"], 0x10000000)
        self.assertEqual(regions["CCMRAM"]["limit_size"], 0x10000)

    def test_else_if_false_preserves_trailing_content(self):
        """Regions after an else-if chain must survive when a later branch wins."""
        script = self._write_icf("""
        define symbol __MODE__ = 3;
        define memory mem with size = 4G;
        if (__MODE__ == 1) {
            define region ROM = mem:[from 0x08000000 size 0x40000];
        } else if (__MODE__ == 2) {
            define region ROM = mem:[from 0x08000000 size 0x80000];
        } else {
            define region ROM = mem:[from 0x08000000 size 0x100000];
        }
        define region RAM = mem:[from 0x20000000 size 0x20000];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertEqual(regions["ROM"]["limit_size"], 0x100000)
        self.assertIn("RAM", regions,
                       "RAM region after else-if chain was dropped")

    def test_negated_isdefinedsymbol_takes_true_branch(self):
        """!isdefinedsymbol(UNDEF) should evaluate to true (take true branch).

        Regression: the arithmetic evaluator has no handler for '!', so
        after builtin expansion '!isdefinedsymbol(X)' becomes '!0' which
        raises ICFEvaluationError.  The exception is caught and the
        condition defaults to False — selecting the wrong branch.
        """
        script = self._write_icf("""
        define memory mem with size = 4G;
        if (!isdefinedsymbol(__BOOTLOADER__)) {
            define region ROM = mem:[from 0x08000000 size 0x100000];
        } else {
            define region ROM = mem:[from 0x08010000 size 0xF0000];
        }
        define region RAM = mem:[from 0x20000000 size 0x20000];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        # __BOOTLOADER__ is NOT defined, so !isdefinedsymbol() is true
        # => should pick the first branch starting at 0x08000000
        self.assertEqual(regions["ROM"]["address"], 0x08000000)
        self.assertEqual(regions["ROM"]["limit_size"], 0x100000)

    def test_value_comparison_conditional(self):
        """Conditional with value comparison (not just isdefinedsymbol)."""
        script = self._write_icf("""
        define symbol __RESERVE_OCD_ROM = 1;
        define memory mem with size = 4G;
        if (__RESERVE_OCD_ROM == 1) {
            define region OCD = mem:[from 0x0FE00 size 0x200];
        }
        define region ROM = mem:[from 0x08000000 size 0x100000];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertIn("OCD", regions)
        self.assertEqual(regions["OCD"]["address"], 0x0FE00)
        self.assertEqual(regions["OCD"]["limit_size"], 0x200)


class TestICFIncludeDirective(_ICFTestBase):
    """Test include directive support."""

    def test_include_with_symbols(self):
        """Included file symbols should be available in the main file."""
        self._write_icf("""
        define symbol __ROM_START__ = 0x08000000;
        define symbol __ROM_END__   = 0x080FFFFF;
        define symbol __RAM_START__ = 0x20000000;
        define symbol __RAM_END__   = 0x2001FFFF;
        """, filename="symbols.icf")

        main_script = self._write_icf("""
        include "symbols.icf";
        define memory mem with size = 4G;
        define region ROM = mem:[from __ROM_START__ to __ROM_END__];
        define region RAM = mem:[from __RAM_START__ to __RAM_END__];
        """, filename="main.icf")

        parser = LinkerScriptParser(ld_scripts=[main_script])
        regions = parser.parse_memory_regions()

        self.assertEqual(regions["ROM"]["address"], 0x08000000)
        self.assertEqual(regions["ROM"]["limit_size"], 0x100000)
        self.assertEqual(regions["RAM"]["address"], 0x20000000)
        self.assertEqual(regions["RAM"]["limit_size"], 0x20000)


class TestICFRegionSetOperations(_ICFTestBase):
    """Test region union, difference, and intersection operations."""

    def test_region_union_with_pipe(self):
        """Union of two regions using | operator."""
        script = self._write_icf("""
        define memory mem with size = 4G;
        define region SRAM1 = mem:[from 0x20000000 size 0x10000];
        define region SRAM2 = mem:[from 0x20010000 size 0x10000];
        define region RAM = SRAM1 | SRAM2;
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertIn("RAM", regions)
        # Bounding box: 0x20000000 to 0x2001FFFF
        self.assertEqual(regions["RAM"]["address"], 0x20000000)
        self.assertEqual(regions["RAM"]["limit_size"], 0x20000)

    def test_region_union_with_plus(self):
        """Union of two regions using + operator (IAR alternate syntax)."""
        script = self._write_icf("""
        define memory mem with size = 4G;
        define region SRAM1 = mem:[from 0x20000000 size 0x8000];
        define region SRAM2 = mem:[from 0x20008000 size 0x8000];
        define region RAM = SRAM1 + SRAM2;
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertIn("RAM", regions)
        self.assertEqual(regions["RAM"]["address"], 0x20000000)
        self.assertEqual(regions["RAM"]["limit_size"], 0x10000)

    def test_region_difference(self):
        """Difference of two regions using - operator."""
        script = self._write_icf("""
        define memory mem with size = 4G;
        define region FULL_ROM = mem:[from 0x08000000 size 0x100000];
        define region BOOTLOADER = mem:[from 0x08000000 size 0x10000];
        define region APP_ROM = FULL_ROM - BOOTLOADER;
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertIn("APP_ROM", regions)
        # FULL_ROM is 0x08000000-0x080FFFFF, minus BOOTLOADER 0x08000000-0x0800FFFF
        # Result: 0x08010000-0x080FFFFF
        self.assertEqual(regions["APP_ROM"]["address"], 0x08010000)
        self.assertEqual(regions["APP_ROM"]["limit_size"], 0xF0000)

    def test_empty_region_literal(self):
        """define region X = []; should produce an empty region."""
        script = self._write_icf("""
        define memory mem with size = 4G;
        define region EMPTY = [];
        define region ROM = mem:[from 0x08000000 size 0x100000];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertIn("ROM", regions)
        self.assertNotIn("EMPTY", regions)

    def test_union_with_empty_region(self):
        """Union of a real region with an empty region should yield the real one."""
        script = self._write_icf("""
        define memory mem with size = 4G;
        define region BANK1 = mem:[from 0x08000000 size 0x100000];
        define region BANK2 = [];
        define region ROM = BANK1 | BANK2;
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertIn("ROM", regions)
        self.assertEqual(regions["ROM"]["address"], 0x08000000)
        self.assertEqual(regions["ROM"]["limit_size"], 0x100000)

    def test_logical_or_in_conditional(self):
        """Conditional using || operator should select correct branch."""
        script = self._write_icf("""
        define symbol A = 0;
        define symbol B = 1;
        define memory mem with size = 4G;
        if (A || B) {
            define region ROM = mem:[from 0x08000000 size 0x100000];
        } else {
            define region ROM = mem:[from 0x08000000 size 0x40000];
        }
        define region RAM = mem:[from 0x20000000 size 0x20000];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        # A=0 || B=1 => true => size 0x100000
        self.assertEqual(regions["ROM"]["limit_size"], 0x100000)

    def test_logical_and_in_conditional(self):
        """Conditional using && operator should select correct branch."""
        script = self._write_icf("""
        define symbol A = 1;
        define symbol B = 0;
        define memory mem with size = 4G;
        if (A && B) {
            define region ROM = mem:[from 0x08000000 size 0x100000];
        } else {
            define region ROM = mem:[from 0x08000000 size 0x40000];
        }
        define region RAM = mem:[from 0x20000000 size 0x20000];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        # A=1 && B=0 => false => size 0x40000
        self.assertEqual(regions["ROM"]["limit_size"], 0x40000)

    def test_ternary_in_symbol_definition(self):
        """Ternary operator in define symbol should resolve correctly."""
        script = self._write_icf("""
        define symbol MODE = 1;
        define symbol SIZE = MODE == 1 ? 0x100000 : 0x40000;
        define memory mem with size = 4G;
        define region ROM = mem:[from 0x08000000 size SIZE];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertEqual(regions["ROM"]["limit_size"], 0x100000)


class TestICFSymbolTable(unittest.TestCase):
    """Unit tests for ICFSymbolTable expression evaluation."""

    def test_hex_literal(self):
        symbols = ICFSymbolTable()
        self.assertEqual(symbols.evaluate("0x08000000"), 0x08000000)

    def test_decimal_literal(self):
        symbols = ICFSymbolTable()
        self.assertEqual(symbols.evaluate("1024"), 1024)

    def test_size_suffix_k(self):
        symbols = ICFSymbolTable()
        self.assertEqual(symbols.evaluate("256K"), 256 * 1024)

    def test_size_suffix_m(self):
        symbols = ICFSymbolTable()
        self.assertEqual(symbols.evaluate("4M"), 4 * 1024 * 1024)

    def test_size_suffix_g(self):
        symbols = ICFSymbolTable()
        self.assertEqual(symbols.evaluate("4G"), 4 * 1024 * 1024 * 1024)

    def test_arithmetic(self):
        symbols = ICFSymbolTable()
        self.assertEqual(symbols.evaluate("0x08000000 + 0x100000"), 0x08100000)

    def test_bitwise_and(self):
        symbols = ICFSymbolTable()
        self.assertEqual(symbols.evaluate("0xFF00 & 0x0FF0"), 0x0F00)

    def test_bitwise_or(self):
        symbols = ICFSymbolTable()
        self.assertEqual(symbols.evaluate("0xF000 | 0x0F00"), 0xFF00)

    def test_bitwise_not(self):
        symbols = ICFSymbolTable()
        # ~0 in Python is -1; we test with a mask
        self.assertEqual(symbols.evaluate("~0 & 0xFF"), 0xFF)

    def test_shift_left(self):
        symbols = ICFSymbolTable()
        self.assertEqual(symbols.evaluate("1 << 20"), 1024 * 1024)

    def test_comparison_equal(self):
        symbols = ICFSymbolTable()
        self.assertEqual(symbols.evaluate("1 == 1"), 1)
        self.assertEqual(symbols.evaluate("1 == 0"), 0)

    def test_comparison_greater(self):
        symbols = ICFSymbolTable()
        self.assertEqual(symbols.evaluate("5 > 3"), 1)
        self.assertEqual(symbols.evaluate("3 > 5"), 0)

    def test_isdefinedsymbol_true(self):
        symbols = ICFSymbolTable()
        symbols._resolved["MY_SYM"] = 42
        self.assertEqual(symbols.evaluate("isdefinedsymbol(MY_SYM)"), 1)

    def test_isdefinedsymbol_false(self):
        symbols = ICFSymbolTable()
        self.assertEqual(symbols.evaluate("isdefinedsymbol(MISSING_SYM)"), 0)

    def test_symbol_substitution(self):
        symbols = ICFSymbolTable()
        symbols._resolved["__ROM_START__"] = 0x08000000
        symbols._resolved["__ROM_SIZE__"] = 0x100000
        self.assertEqual(
            symbols.evaluate("__ROM_START__ + __ROM_SIZE__"),
            0x08100000
        )

    def test_multi_pass_resolution(self):
        """Symbols referencing other symbols should resolve iteratively."""
        symbols = ICFSymbolTable()
        symbols.define_raw("BASE", "0x08000000")
        symbols.define_raw("OFFSET", "0x10000")
        symbols.define_raw("APP_START", "BASE + OFFSET")
        symbols.resolve_all()
        self.assertEqual(symbols.evaluate("APP_START"), 0x08010000)

    def test_logical_or(self):
        """Logical OR operator (||)."""
        symbols = ICFSymbolTable()
        self.assertEqual(symbols.evaluate("0 || 0"), 0)
        self.assertEqual(symbols.evaluate("1 || 0"), 1)
        self.assertEqual(symbols.evaluate("0 || 1"), 1)
        self.assertEqual(symbols.evaluate("1 || 1"), 1)

    def test_logical_and(self):
        """Logical AND operator (&&)."""
        symbols = ICFSymbolTable()
        self.assertEqual(symbols.evaluate("0 && 0"), 0)
        self.assertEqual(symbols.evaluate("1 && 0"), 0)
        self.assertEqual(symbols.evaluate("0 && 1"), 0)
        self.assertEqual(symbols.evaluate("1 && 1"), 1)

    def test_logical_or_with_comparison(self):
        """Logical OR combined with comparison, as in real ICF files."""
        symbols = ICFSymbolTable()
        # (0x08000000 != 0x0 || 0x080FFFFF != 0x0) -> (1 || 1) -> 1
        self.assertEqual(
            symbols.evaluate("(0x08000000 != 0x0 || 0x080FFFFF != 0x0)"), 1)
        # (0x0 != 0x0 || 0x0 != 0x0) -> (0 || 0) -> 0
        self.assertEqual(
            symbols.evaluate("(0x0 != 0x0 || 0x0 != 0x0)"), 0)

    def test_logical_and_with_isdefinedsymbol(self):
        """Logical AND with isdefinedsymbol, as in Renesas/Infineon ICF files."""
        symbols = ICFSymbolTable()
        symbols._resolved["A"] = 1
        symbols._resolved["B"] = 1
        self.assertEqual(
            symbols.evaluate("isdefinedsymbol(A) && isdefinedsymbol(B)"), 1)
        self.assertEqual(
            symbols.evaluate("isdefinedsymbol(A) && isdefinedsymbol(MISSING)"), 0)

    def test_negated_logical_and(self):
        """(!expr) && (!expr) pattern used in Infineon Traveo II."""
        symbols = ICFSymbolTable()
        # (!isdefinedsymbol(X)) && (!isdefinedsymbol(Y)) with both undefined
        # After builtin expansion: (!0) && (!0) -> (1) && (1) -> 1
        self.assertEqual(symbols.evaluate("(!0) && (!0)"), 1)
        self.assertEqual(symbols.evaluate("(!1) && (!0)"), 0)

    def test_ternary_operator(self):
        """Ternary operator (?:)."""
        symbols = ICFSymbolTable()
        self.assertEqual(symbols.evaluate("1 ? 42 : 99"), 42)
        self.assertEqual(symbols.evaluate("0 ? 42 : 99"), 99)

    def test_ternary_with_comparison(self):
        """Ternary with comparison condition, as in Renesas FSP."""
        symbols = ICFSymbolTable()
        self.assertEqual(symbols.evaluate("(1 == 1) ? 0x1000 : 0x2000"), 0x1000)
        self.assertEqual(symbols.evaluate("(1 == 0) ? 0x1000 : 0x2000"), 0x2000)

    def test_ternary_nested(self):
        """Nested ternary (right-associative): a ? b : c ? d : e."""
        symbols = ICFSymbolTable()
        # 0 ? 1 : (1 ? 2 : 3) -> 2
        self.assertEqual(symbols.evaluate("0 ? 1 : 1 ? 2 : 3"), 2)
        # 1 ? 10 : (0 ? 20 : 30) -> 10
        self.assertEqual(symbols.evaluate("1 ? 10 : 0 ? 20 : 30"), 10)

    def test_isempty_unknown_region(self):
        """isempty() on unknown region should return 1 (empty)."""
        symbols = ICFSymbolTable()
        self.assertEqual(symbols.evaluate("isempty(MISSING_REGION)"), 1)

    def test_isempty_with_negation(self):
        """!isempty() pattern used in Nuvoton/Goodix ICF files."""
        symbols = ICFSymbolTable()
        self.assertEqual(symbols.evaluate("!isempty(MISSING)"), 0)


class TestICFBitwiseExpressions(_ICFTestBase):
    """Test bitwise operations in ICF scripts (used in RL78, TI, etc.)."""

    def test_bitwise_mask_in_symbol(self):
        """Bitwise AND used to compute mirror addresses."""
        script = self._write_icf("""
        define symbol _FLASH_END = 0x1FFFF;
        define symbol _ROM_NEAR_END = _FLASH_END & 0x0FFFF;
        define memory mem with size = 4G;
        define region ROM_near = mem:[from 0x00000 to _ROM_NEAR_END];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertIn("ROM_near", regions)
        # 0x1FFFF & 0x0FFFF = 0x0FFFF
        self.assertEqual(regions["ROM_near"]["address"], 0x00000)
        self.assertEqual(regions["ROM_near"]["end_address"], 0x0FFFF)


class TestICFNordicSoftDevice(_ICFTestBase):
    """Test Nordic nRF BLE SoftDevice-style .icf patterns."""

    def test_nordic_nrf52_softdevice_layout(self):
        """nRF52 with SoftDevice: ROM/RAM start offsets for BLE stack."""
        script = self._write_icf("""
        define symbol __ICFEDIT_intvec_start__ = 0x19000;
        define symbol __ICFEDIT_region_ROM_start__ = 0x19000;
        define symbol __ICFEDIT_region_ROM_end__   = 0x2ffff;
        define symbol __ICFEDIT_region_RAM_start__ = 0x20001b48;
        define symbol __ICFEDIT_region_RAM_end__   = 0x20005fff;
        define symbol __ICFEDIT_size_cstack__ = 2048;
        define symbol __ICFEDIT_size_heap__   = 2048;

        define memory mem with size = 4G;
        define region ROM_region = mem:[from __ICFEDIT_region_ROM_start__
                                        to   __ICFEDIT_region_ROM_end__];
        define region RAM_region = mem:[from __ICFEDIT_region_RAM_start__
                                        to   __ICFEDIT_region_RAM_end__];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertEqual(regions["ROM_region"]["address"], 0x19000)
        self.assertEqual(regions["ROM_region"]["limit_size"],
                         0x2ffff - 0x19000 + 1)
        self.assertEqual(regions["RAM_region"]["address"], 0x20001b48)
        self.assertEqual(regions["RAM_region"]["limit_size"],
                         0x20005fff - 0x20001b48 + 1)


class TestICFExportedSymbol(_ICFTestBase):
    """Test 'define exported symbol' variant."""

    def test_exported_symbol_parsed(self):
        """'define exported symbol' should be extracted like 'define symbol'."""
        script = self._write_icf("""
        define exported symbol __link_file_version_2 = 1;
        define symbol __ROM_START__ = 0x08000000;
        define symbol __ROM_END__   = 0x0807FFFF;
        define memory mem with size = 4G;
        define region ROM = mem:[from __ROM_START__ to __ROM_END__];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertIn("ROM", regions)
        self.assertEqual(regions["ROM"]["address"], 0x08000000)


class TestICFMultilineRegionSpan(_ICFTestBase):
    """Bug: _MEM_SPAN_PATTERN lacks re.DOTALL so multi-line from...to fails.

    When `from` and `to` are on separate lines (common in real .icf files),
    the `.+?` in the regex doesn't match the newline, causing the span to
    be silently dropped and the region to disappear from the output.
    """

    def test_from_to_on_separate_lines(self):
        """Region with from/to split across lines must be parsed."""
        script = self._write_icf("""
        define memory mem with size = 4G;
        define region ROM = mem:[from 0x08000000
                                 to   0x080FFFFF];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertIn("ROM", regions,
                       "Region with multi-line from...to was silently dropped")
        self.assertEqual(regions["ROM"]["address"], 0x08000000)
        self.assertEqual(regions["ROM"]["limit_size"], 0x100000)

    def test_from_size_on_separate_lines(self):
        """Region with from/size split across lines must be parsed."""
        script = self._write_icf("""
        define memory mem with size = 4G;
        define region RAM = mem:[from 0x20000000
                                 size 0x20000];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertIn("RAM", regions,
                       "Region with multi-line from...size was silently dropped")
        self.assertEqual(regions["RAM"]["address"], 0x20000000)
        self.assertEqual(regions["RAM"]["limit_size"], 0x20000)

    def test_symbols_with_multiline_region(self):
        """Symbol references in a multi-line region definition must resolve."""
        script = self._write_icf("""
        define symbol __ROM_START__ = 0x19000;
        define symbol __ROM_END__   = 0x2FFFF;
        define memory mem with size = 4G;
        define region ROM_region = mem:[from __ROM_START__
                                        to   __ROM_END__];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertIn("ROM_region", regions,
                       "Region with symbol refs on separate lines was dropped")
        self.assertEqual(regions["ROM_region"]["address"], 0x19000)
        self.assertEqual(regions["ROM_region"]["limit_size"],
                         0x2FFFF - 0x19000 + 1)


class TestICFSetOperatorPrecedence(_ICFTestBase):
    """Bug: _eval_region_set_expr tries union before difference/intersection.

    This means `A - B | C` is parsed as `A - (B | C)` instead of the
    correct `(A - B) | C`.  Union should be lowest precedence.
    """

    def test_difference_then_union(self):
        """FULL - BOOT | EXTRA should equal (FULL - BOOT) | EXTRA."""
        script = self._write_icf("""
        define memory mem with size = 4G;
        define region FULL  = mem:[from 0x08000000 size 0x100000];
        define region BOOT  = mem:[from 0x08000000 size 0x10000];
        define region EXTRA = mem:[from 0x10000000 size 0x10000];
        define region APP   = FULL - BOOT | EXTRA;
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertIn("APP", regions)
        # Correct: (FULL - BOOT) | EXTRA
        #   FULL - BOOT = [0x08010000, 0x080FFFFF]
        #   union EXTRA = [0x10000000, 0x1000FFFF]
        #   bounding box = [0x08010000, 0x1000FFFF]
        #
        # Wrong (current): FULL - (BOOT | EXTRA)
        #   BOOT | EXTRA spans don't overlap FULL except BOOT part
        #   so result is FULL minus BOOT portion only, missing EXTRA entirely
        #   bounding box = [0x08010000, 0x080FFFFF]
        self.assertEqual(regions["APP"]["address"], 0x08010000)
        # The result must include EXTRA, so end_address >= 0x1000FFFF
        self.assertGreaterEqual(regions["APP"]["end_address"], 0x1000FFFF,
                                "Union with EXTRA was lost due to wrong "
                                "operator precedence (union bound tighter "
                                "than difference)")

    def test_intersection_then_union(self):
        """A & B | C should equal (A & B) | C, not A & (B | C)."""
        script = self._write_icf("""
        define memory mem with size = 4G;
        define region A = mem:[from 0x08000000 size 0x20000];
        define region B = mem:[from 0x08010000 size 0x20000];
        define region C = mem:[from 0x20000000 size 0x10000];
        define region RESULT = A & B | C;
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertIn("RESULT", regions)
        # Correct: (A & B) | C
        #   A & B = overlap [0x08010000, 0x0801FFFF]
        #   union C = [0x20000000, 0x2000FFFF]
        #   bounding box starts at 0x08010000, ends at 0x2000FFFF
        #
        # Wrong: A & (B | C) — B|C bounding box is [0x08010000, 0x2000FFFF],
        #   intersect with A [0x08000000, 0x0801FFFF] = [0x08010000, 0x0801FFFF]
        #   C is lost entirely
        self.assertGreaterEqual(regions["RESULT"]["end_address"], 0x2000FFFF,
                                "Union with C was lost due to wrong operator "
                                "precedence (union bound tighter than "
                                "intersection)")


class TestICFChainedDifference(_ICFTestBase):
    """Bug: _split_set_op scans right-to-left, making `-` right-associative.

    `A - B - C` is parsed as `A - (B - C)` instead of the correct
    left-associative `(A - B) - C`.
    """

    def test_chained_difference_is_left_associative(self):
        """A - B - C should equal (A - B) - C."""
        script = self._write_icf("""
        define memory mem with size = 4G;
        define region FULL = mem:[from 0x08000000 size 0x100000];
        define region HEAD = mem:[from 0x08000000 size 0x10000];
        define region TAIL = mem:[from 0x080F0000 size 0x10000];
        define region MIDDLE = FULL - HEAD - TAIL;
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertIn("MIDDLE", regions)
        # Correct (left-associative): (FULL - HEAD) - TAIL
        #   FULL - HEAD = [0x08010000, 0x080FFFFF]
        #   minus TAIL  = [0x08010000, 0x080EFFFF]
        #   address = 0x08010000, size = 0xE0000
        #
        # Wrong (right-associative): FULL - (HEAD - TAIL)
        #   HEAD - TAIL = HEAD (no overlap) = [0x08000000, 0x0800FFFF]
        #   FULL - that = [0x08010000, 0x080FFFFF]  (TAIL not removed)
        #   address = 0x08010000, size = 0xF0000
        self.assertEqual(regions["MIDDLE"]["address"], 0x08010000)
        self.assertEqual(regions["MIDDLE"]["limit_size"], 0xE0000,
                         "Chained difference is right-associative: "
                         "A - B - C parsed as A - (B - C) instead of "
                         "(A - B) - C")


class TestICFInvalidScripts(_ICFTestBase):
    """Test that invalid ICF scripts raise errors instead of silently succeeding."""

    def test_unresolvable_symbols_in_regions(self):
        """Regions referencing undefined symbols should raise LinkerScriptError."""
        script = self._write_icf("""
        define memory mem with size = 4G;
        define region ROM = mem:[from __UNDEFINED_START__ to __UNDEFINED_END__];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        with self.assertRaises(LinkerScriptError):
            parser.parse_memory_regions()

    def test_all_regions_fail_to_resolve(self):
        """When every region fails, parser should raise not return empty dict."""
        script = self._write_icf("""
        define memory mem with size = 4G;
        define region ROM = mem:[from __MISSING_A__ to __MISSING_B__];
        define region RAM = mem:[from __MISSING_C__ size __MISSING_D__];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        with self.assertRaises(LinkerScriptError):
            parser.parse_memory_regions()

    def test_set_op_references_unknown_region(self):
        """Set operation referencing a non-existent region drops that region."""
        script = self._write_icf("""
        define memory mem with size = 4G;
        define region ROM = mem:[from 0x08000000 size 0x100000];
        define region APP = ROM - NONEXISTENT;
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        # ROM is valid and should be present; APP cannot resolve
        self.assertIn("ROM", regions)
        self.assertNotIn("APP", regions)

    def test_all_set_ops_fail(self):
        """When all regions are set ops referencing unknowns, should raise."""
        script = self._write_icf("""
        define memory mem with size = 4G;
        define region APP = NONEXISTENT_A | NONEXISTENT_B;
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        with self.assertRaises(LinkerScriptError):
            parser.parse_memory_regions()

    def test_no_regions_defined_returns_empty(self):
        """An ICF file with symbols but no regions should return empty dict."""
        script = self._write_icf("""
        define symbol __ROM_START__ = 0x08000000;
        define symbol __ROM_END__   = 0x080FFFFF;
        define memory mem with size = 4G;
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()
        self.assertEqual(regions, {})

    def test_region_end_before_start_raises(self):
        """Region where end address < start address should not silently succeed."""
        script = self._write_icf("""
        define memory mem with size = 4G;
        define region BAD = mem:[from 0x20000000 to 0x10000000];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        with self.assertRaises(LinkerScriptError):
            parser.parse_memory_regions()

    def test_partial_failure_preserves_valid_regions(self):
        """When some regions fail, valid ones should still be returned."""
        script = self._write_icf("""
        define memory mem with size = 4G;
        define region ROM = mem:[from 0x08000000 size 0x100000];
        define region BAD = mem:[from __UNDEFINED__ size 0x1000];
        """)
        parser = LinkerScriptParser(ld_scripts=[script])
        regions = parser.parse_memory_regions()

        self.assertIn("ROM", regions)
        self.assertEqual(regions["ROM"]["address"], 0x08000000)
        self.assertNotIn("BAD", regions)


if __name__ == "__main__":
    unittest.main()
