#!/usr/bin/env python3
"""Tests for map file parsers (GNU LD and IAR)."""

import unittest
import tempfile
from pathlib import Path

from membrowse.analysis.mapfile import (
    MapFileParser, IARMapFileParser, MapFileResolver, _detect_map_format
)
from membrowse.core.exceptions import MapFileParseError


MAP_WITH_ARCHIVES = """\
Memory Configuration

Name             Origin             Length             Attributes
FLASH            0x0000000008000000 0x0000000000040000 xr
RAM              0x0000000020000000 0x0000000000010000 xrw
*default*        0x0000000000000000 0xffffffffffffffff

Linker script and memory map

LOAD build/src/main.o
LOAD build/lib/libstm32hal.a

.text           0x0000000008000000       0x100
                0x0000000008000000                . = ALIGN (0x4)
 *(.text)
 .text          0x0000000008000000       0xac libstm32hal.a(stm32_startup.o)
                0x0000000008000000                Reset_Handler
                0x0000000008000020                SystemInit
 .text          0x00000000080000ac       0x34 libapp.a(main.o)
                0x00000000080000ac                main
 .text.startup  0x00000000080000e0       0x10 build/src/init.o
                0x00000000080000e0                system_init
 .glue_7        0x00000000080000f0        0x0 linker stubs
"""

MAP_BARE_OBJECT = """\
Linker script and memory map

 .text          0x0000000008000010       0xac /path/to/build/firmware.o
                0x0000000008000010                interrupt_handler
"""

MAP_WITH_FILL = """\
Linker script and memory map

 *fill*         0x0000000020000408     0x1000
 .text          0x0000000008000010       0xac libfoo.a(bar.o)
                0x0000000008000010                bar_func
"""

MAP_DEBUG_SECTIONS = """\
Linker script and memory map

 .text          0x0000000008000010       0xac libfoo.a(bar.o)
                0x0000000008000010                real_func

.debug_info     0x0000000000000000      0x2fc
 .debug_info    0x0000000000000000      0x2fc libfoo.a(bar.o)
"""

MAP_WITH_COMMON = """\
Linker script and memory map

 .bss           0x0000000020000000      0x100 main.o
 COMMON         0x0000000020000100        0x4 main.o
 COMMON         0x0000000020000104        0x8 libsensor.a(accel.o)
"""

MAP_TWO_LINE_FORMAT = """\
Linker script and memory map

 .text.short    0x0000000008000010       0xac build/main.o
                0x0000000008000010                short_func
 .text.very_long_section_name_that_wraps
                0x00000000080000bc       0x34 build/utils.o
                0x00000000080000bc                long_func
 .text.from_archive
                0x00000000080000f0       0x20 libhal.a(gpio.o)
                0x00000000080000f0                gpio_init
"""

MAP_TWO_LINE_ZERO_ADDRESS = """\
Linker script and memory map

 .text.Reset_Handler
                0x0000000000000000       0x50 build/startup.o
 .text.real
                0x0000000008000100       0x10 build/real.o
"""

MAP_EMPTY = """\
Memory Configuration

Name             Origin             Length             Attributes
"""


class TestMapFileParser(unittest.TestCase):
    """Unit tests for MapFileParser."""

    def setUp(self):
        self.parser = MapFileParser()

    def test_archive_entry_parsed(self):
        result = self.parser.parse(MAP_WITH_ARCHIVES)
        self.assertIn(0x08000000, result)
        archive, obj = result[0x08000000]
        self.assertEqual(archive, 'libstm32hal.a')
        self.assertEqual(obj, 'stm32_startup.o')

    def test_second_archive_entry(self):
        result = self.parser.parse(MAP_WITH_ARCHIVES)
        self.assertIn(0x080000ac, result)
        archive, obj = result[0x080000ac]
        self.assertEqual(archive, 'libapp.a')
        self.assertEqual(obj, 'main.o')

    def test_bare_object_file(self):
        result = self.parser.parse(MAP_WITH_ARCHIVES)
        self.assertIn(0x080000e0, result)
        archive, obj = result[0x080000e0]
        self.assertEqual(archive, '')
        self.assertEqual(obj, 'build/src/init.o')

    def test_bare_object_absolute_path(self):
        result = self.parser.parse(MAP_BARE_OBJECT)
        self.assertIn(0x08000010, result)
        archive, obj = result[0x08000010]
        self.assertEqual(archive, '')
        self.assertEqual(obj, '/path/to/build/firmware.o')

    def test_linker_stubs_skipped(self):
        result = self.parser.parse(MAP_WITH_ARCHIVES)
        # 0x080000f0 is linker stubs, should not be in result
        self.assertNotIn(0x080000f0, result)

    def test_fill_lines_skipped(self):
        result = self.parser.parse(MAP_WITH_FILL)
        # Fill address should not appear
        self.assertNotIn(0x20000408, result)
        # Real entry should still be present
        self.assertIn(0x08000010, result)

    def test_zero_address_debug_sections_skipped(self):
        result = self.parser.parse(MAP_DEBUG_SECTIONS)
        # Address 0 (debug sections) should not be in result
        self.assertNotIn(0x0, result)
        # Real entry should be present
        self.assertIn(0x08000010, result)

    def test_empty_map_returns_empty_dict(self):
        result = self.parser.parse(MAP_EMPTY)
        self.assertEqual(result, {})

    def test_empty_string_returns_empty_dict(self):
        result = self.parser.parse('')
        self.assertEqual(result, {})

    def test_common_section_bare_object(self):
        result = self.parser.parse(MAP_WITH_COMMON)
        self.assertIn(0x20000100, result)
        archive, obj = result[0x20000100]
        self.assertEqual(archive, '')
        self.assertEqual(obj, 'main.o')

    def test_common_section_archive(self):
        result = self.parser.parse(MAP_WITH_COMMON)
        self.assertIn(0x20000104, result)
        archive, obj = result[0x20000104]
        self.assertEqual(archive, 'libsensor.a')
        self.assertEqual(obj, 'accel.o')

    def test_first_occurrence_wins(self):
        """When multiple input sections share an address, first one wins."""
        content = """\
Linker script and memory map

 .text          0x0000000008000010       0xac libfirst.a(first.o)
 .text          0x0000000008000010       0x00 libsecond.a(second.o)
"""
        result = self.parser.parse(content)
        archive, obj = result[0x08000010]
        self.assertEqual(archive, 'libfirst.a')
        self.assertEqual(obj, 'first.o')

    def test_two_line_bare_object(self):
        """Two-line format: section name wraps, continuation has address."""
        result = self.parser.parse(MAP_TWO_LINE_FORMAT)
        self.assertIn(0x080000bc, result)
        archive, obj = result[0x080000bc]
        self.assertEqual(archive, '')
        self.assertEqual(obj, 'build/utils.o')

    def test_two_line_archive(self):
        """Two-line format with archive(object) on continuation line."""
        result = self.parser.parse(MAP_TWO_LINE_FORMAT)
        self.assertIn(0x080000f0, result)
        archive, obj = result[0x080000f0]
        self.assertEqual(archive, 'libhal.a')
        self.assertEqual(obj, 'gpio.o')

    def test_two_line_mixed_with_single_line(self):
        """Single-line entries still work alongside two-line entries."""
        result = self.parser.parse(MAP_TWO_LINE_FORMAT)
        self.assertIn(0x08000010, result)
        archive, obj = result[0x08000010]
        self.assertEqual(archive, '')
        self.assertEqual(obj, 'build/main.o')

    def test_two_line_zero_address_skipped(self):
        """Two-line entries with address 0 are skipped."""
        result = self.parser.parse(MAP_TWO_LINE_ZERO_ADDRESS)
        self.assertNotIn(0x0, result)
        self.assertIn(0x08000100, result)


class TestMapFileParserFileField(unittest.TestCase):
    """Unit tests for _parse_file_field static method."""

    def test_archive_with_object(self):
        archive, obj = MapFileParser._parse_file_field(  # pylint: disable=protected-access
            'libstm32hal.a(stm32_gpio.o)')
        self.assertEqual(archive, 'libstm32hal.a')
        self.assertEqual(obj, 'stm32_gpio.o')

    def test_archive_with_path(self):
        archive, obj = MapFileParser._parse_file_field(  # pylint: disable=protected-access
            '/usr/lib/libm.a(s_sin.o)')
        self.assertEqual(archive, '/usr/lib/libm.a')
        self.assertEqual(obj, 's_sin.o')

    def test_bare_object(self):
        archive, obj = MapFileParser._parse_file_field(  # pylint: disable=protected-access
            'build/src/main.o')
        self.assertEqual(archive, '')
        self.assertEqual(obj, 'build/src/main.o')

    def test_linker_stubs(self):
        archive, obj = MapFileParser._parse_file_field(  # pylint: disable=protected-access
            'linker stubs')
        self.assertEqual(archive, '')
        self.assertEqual(obj, '')

    def test_empty_string(self):
        archive, obj = MapFileParser._parse_file_field(  # pylint: disable=protected-access
            '')
        self.assertEqual(archive, '')
        self.assertEqual(obj, '')


class TestMapFileResolver(unittest.TestCase):
    """Unit tests for MapFileResolver."""

    def test_null_resolver_returns_empty(self):
        resolver = MapFileResolver.null()
        self.assertEqual(resolver.resolve(0x08000000), ('', ''))

    def test_resolve_known_address(self):
        resolver = MapFileResolver({
            0x08000000: ('libfoo.a', 'foo.o'),
        })
        self.assertEqual(resolver.resolve(0x08000000), ('libfoo.a', 'foo.o'))

    def test_resolve_unknown_address(self):
        resolver = MapFileResolver({
            0x08000000: ('libfoo.a', 'foo.o'),
        })
        self.assertEqual(resolver.resolve(0xDEADBEEF), ('', ''))

    def test_resolve_thumb_address(self):
        """ARM Thumb functions have bit 0 set in ELF st_value."""
        resolver = MapFileResolver({
            0x080000ac: ('libapp.a', 'main.o'),
        })
        # ELF stores 0x080000ad (Thumb bit set), map file has 0x080000ac
        self.assertEqual(
            resolver.resolve(0x080000ad), ('libapp.a', 'main.o'))

    def test_resolve_exact_match_preferred_over_thumb(self):
        """Exact address match takes priority over Thumb-bit fallback."""
        resolver = MapFileResolver({
            0x080000ac: ('libfoo.a', 'foo.o'),
            0x080000ad: ('libbar.a', 'bar.o'),
        })
        self.assertEqual(
            resolver.resolve(0x080000ad), ('libbar.a', 'bar.o'))

    def test_from_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            map_path = Path(tmpdir) / 'test.map'
            map_path.write_text(MAP_WITH_ARCHIVES, encoding='utf-8')
            resolver = MapFileResolver.from_file(str(map_path))
        self.assertEqual(
            resolver.resolve(0x08000000),
            ('libstm32hal.a', 'stm32_startup.o')
        )

    def test_from_file_missing_raises(self):
        with self.assertRaises(MapFileParseError):
            MapFileResolver.from_file('/nonexistent/path/to.map')

    def test_from_file_with_test_firmware_map(self):
        """Parse the existing test fixture map file."""
        map_path = Path(__file__).parent / 'test_firmware.map'
        if not map_path.exists():
            self.skipTest('test_firmware.map fixture not found')
        resolver = MapFileResolver.from_file(str(map_path))
        # The fixture uses bare .o paths, so archive should be empty
        # and at least some addresses should resolve
        archive, obj = resolver.resolve(0x08000010)
        self.assertEqual(archive, '')
        self.assertTrue(obj.endswith('.o'),
                        f"Expected .o file, got {obj!r}")


# ============================================================
# IAR map file test fixtures and tests
# ============================================================

IAR_MAP_BASIC = """\
###############################################################################
#
# IAR ELF Linker V9.30.1 for ARM                 02/Mar/2026  10:00:00
#
###############################################################################

*******************************************************************************
*** PLACEMENT SUMMARY
***

"A1":  place at 0x00000000 { ro section .intvec };
"P1":  place in [from 0x00000000 to 0x0001ffff] { ro };
"P2":  place in [from 0x20000000 to 0x20001fff] { rw, block CSTACK };

  Section          Kind        Address    Size  Object
  -------          ----        -------    ----  ------
"A1":                                      0xe0
  .intvec          ro code  0x00000000    0xe0  startup.o [1]
                          - 0x000000e0    0xe0

"P1":                                    0x2000
  .text            ro code  0x000000e0  0x1000  main.o [1]
  .text            ro code  0x000010e0   0x200  uart.o [1]
  .text            ro code  0x000012e0    0x80  sprintf.o [3]
  .text            ro code  0x00001360    0x40  ABImemcpy.o [5]
  .rodata          const    0x000013a0   0x100  main.o [1]
                          - 0x000014a0  0x13c0

"P2":                                     0x400
  .bss             zero     0x20000000   0x200  main.o [1]
  .bss             zero     0x20000200   0x100  uart.o [1]
                          - 0x20000300   0x300

*******************************************************************************
*** MODULE SUMMARY
***

    Module            ro code  ro data  rw data
    ------            -------  -------  -------
C:\\Project\\Debug\\Obj: [1]
    main.o              4 096      256      512
    startup.o             224
    uart.o                512               256
    -------------------------------------------
    Total:              4 832      256      768

command line: [2]
    -------------------------------------------
    Total:

dl7M_tlf.a: [3]
    sprintf.o               128
    -------------------------------------------
    Total:                  128

m7M_tl.a: [4]
    -------------------------------------------
    Total:

rt7M_tl.a: [5]
    ABImemcpy.o              64
    -------------------------------------------
    Total:                   64

*******************************************************************************
*** ENTRY LIST
***

Entry                Address   Size  Type      Object
-----                -------   ----  ----      ------
main              0x000000e1  0x100  Code  Gb  main.o [1]
"""

IAR_MAP_NO_LIBRARIES = """\
*******************************************************************************
*** PLACEMENT SUMMARY
***

  Section          Kind        Address    Size  Object
  -------          ----        -------    ----  ------
"P1":                                     0x100
  .text            ro code  0x00000100    0x80  main.o [1]
  .text            ro code  0x00000180    0x40  led.o [1]

*******************************************************************************
*** MODULE SUMMARY
***

    Module            ro code
    ------            -------
C:\\Project\\Obj: [1]
    led.o                  64
    main.o                128
    -----------------------
    Total:                192
"""

IAR_MAP_EMPTY = """\
*******************************************************************************
*** PLACEMENT SUMMARY
***

  Section          Kind        Address    Size  Object
  -------          ----        -------    ----  ------

*******************************************************************************
*** MODULE SUMMARY
***
"""


class TestIARMapFileParser(unittest.TestCase):
    """Unit tests for IARMapFileParser."""

    def setUp(self):
        self.parser = IARMapFileParser()

    def test_project_object_parsed(self):
        result = self.parser.parse(IAR_MAP_BASIC)
        self.assertIn(0xe0, result)
        archive, obj = result[0xe0]
        self.assertEqual(archive, '')
        self.assertEqual(obj, 'main.o')

    def test_library_object_parsed(self):
        result = self.parser.parse(IAR_MAP_BASIC)
        self.assertIn(0x12e0, result)
        archive, obj = result[0x12e0]
        self.assertEqual(archive, 'dl7M_tlf.a')
        self.assertEqual(obj, 'sprintf.o')

    def test_runtime_library_parsed(self):
        result = self.parser.parse(IAR_MAP_BASIC)
        self.assertIn(0x1360, result)
        archive, obj = result[0x1360]
        self.assertEqual(archive, 'rt7M_tl.a')
        self.assertEqual(obj, 'ABImemcpy.o')

    def test_bss_section_parsed(self):
        result = self.parser.parse(IAR_MAP_BASIC)
        self.assertIn(0x20000000, result)
        archive, obj = result[0x20000000]
        self.assertEqual(archive, '')
        self.assertEqual(obj, 'main.o')

    def test_rodata_section_parsed(self):
        result = self.parser.parse(IAR_MAP_BASIC)
        self.assertIn(0x13a0, result)
        archive, obj = result[0x13a0]
        self.assertEqual(archive, '')
        self.assertEqual(obj, 'main.o')

    def test_zero_address_skipped(self):
        result = self.parser.parse(IAR_MAP_BASIC)
        # .intvec at address 0 should be skipped
        self.assertNotIn(0x0, result)

    def test_no_libraries(self):
        result = self.parser.parse(IAR_MAP_NO_LIBRARIES)
        self.assertIn(0x100, result)
        archive, obj = result[0x100]
        self.assertEqual(archive, '')
        self.assertEqual(obj, 'main.o')

    def test_empty_placement(self):
        result = self.parser.parse(IAR_MAP_EMPTY)
        self.assertEqual(result, {})

    def test_total_entries(self):
        result = self.parser.parse(IAR_MAP_BASIC)
        # startup at 0 skipped, rest: main.o(.text), uart.o(.text),
        # sprintf.o, ABImemcpy.o, main.o(.rodata), main.o(.bss), uart.o(.bss)
        self.assertEqual(len(result), 7)

    def test_first_occurrence_wins(self):
        """When same address appears twice, first one wins."""
        content = """\
*** PLACEMENT SUMMARY
***

  Section          Kind        Address    Size  Object
  .text            ro code  0x00001000    0x80  first.o [1]
  .text            ro code  0x00001000    0x00  second.o [1]

*** MODULE SUMMARY
***

project: [1]
"""
        result = self.parser.parse(content)
        _, obj = result[0x1000]
        self.assertEqual(obj, 'first.o')

    def test_digit_separator_in_address(self):
        """IAR may use ' as digit separator in addresses (e.g. 0x800'0130)."""
        content = """\
*** PLACEMENT SUMMARY
***

  Section          Kind        Address    Size  Object
  .text            ro code   0x800'0130  0x10c6  xprintffull.o [2]
  .rodata          const     0x800'145e     0x2  xlocale_c.o [2]

*******************************************************************************
*** MODULE SUMMARY
***

dl7M_tlf.a: [2]
"""
        result = self.parser.parse(content)
        self.assertIn(0x8000130, result)
        self.assertEqual(result[0x8000130], ('dl7M_tlf.a', 'xprintffull.o'))
        self.assertIn(0x800145e, result)
        self.assertEqual(result[0x800145e], ('dl7M_tlf.a', 'xlocale_c.o'))


class TestIARModuleSummary(unittest.TestCase):
    """Unit tests for IAR MODULE SUMMARY parsing."""

    def test_library_group_mapping(self):
        parser = IARMapFileParser()
        groups = parser._parse_module_summary(IAR_MAP_BASIC)  # pylint: disable=protected-access
        self.assertEqual(groups['3'], 'dl7M_tlf.a')
        self.assertEqual(groups['5'], 'rt7M_tl.a')

    def test_project_dir_maps_to_empty(self):
        parser = IARMapFileParser()
        groups = parser._parse_module_summary(IAR_MAP_BASIC)  # pylint: disable=protected-access
        self.assertEqual(groups['1'], '')

    def test_command_line_group(self):
        parser = IARMapFileParser()
        groups = parser._parse_module_summary(IAR_MAP_BASIC)  # pylint: disable=protected-access
        # "command line: [2]" doesn't end with .a
        self.assertEqual(groups['2'], '')


class TestDetectMapFormat(unittest.TestCase):
    """Unit tests for format auto-detection."""

    def test_detect_gnu_ld(self):
        self.assertEqual(_detect_map_format(MAP_WITH_ARCHIVES), 'gnu_ld')

    def test_detect_iar_by_placement_summary(self):
        self.assertEqual(_detect_map_format(IAR_MAP_BASIC), 'iar')

    def test_detect_iar_by_linker_header(self):
        content = "# IAR ELF Linker V9.30\n"
        self.assertEqual(_detect_map_format(content), 'iar')

    def test_detect_empty_defaults_to_gnu_ld(self):
        self.assertEqual(_detect_map_format(''), 'gnu_ld')

    def test_from_file_auto_detects_iar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            map_path = Path(tmpdir) / 'test.map'
            map_path.write_text(IAR_MAP_BASIC, encoding='utf-8')
            resolver = MapFileResolver.from_file(str(map_path))
        # Should have parsed the IAR content correctly
        self.assertEqual(
            resolver.resolve(0x12e0),
            ('dl7M_tlf.a', 'sprintf.o')
        )


if __name__ == '__main__':
    unittest.main()
