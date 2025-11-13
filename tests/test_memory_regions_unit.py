#!/usr/bin/env python3

"""
test_memory_regions_unit.py - Unit tests for memory_regions.py

This module contains focused unit tests for the LinkerScriptParser class,
testing specific functionality with controlled linker script examples
based on real MicroPython linker scripts.
"""
# pylint: disable=too-many-lines

import os
import sys
import tempfile
import unittest
from pathlib import Path

from membrowse.linker.parser import RegionParsingError, LinkerScriptParser, parse_linker_scripts
from tests.test_utils import validate_memory_regions

# Add shared directory to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent / 'shared'))


class TestLinkerScriptParser(unittest.TestCase):
    """Unit tests for LinkerScriptParser class"""

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_files = []

    def tearDown(self):
        """Clean up temporary files"""
        for temp_file in self.temp_files:
            try:
                os.unlink(temp_file)
            except OSError:
                pass
        try:
            os.rmdir(self.temp_dir)
        except OSError:
            pass

    def create_temp_linker_script(self, content: str) -> str:
        """Create a temporary linker script file with given content"""
        temp_file = os.path.join(
            self.temp_dir,
            f"test_{len(self.temp_files)}.ld")
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(content)
        self.temp_files.append(temp_file)
        return temp_file

    def test_simple_stm32_memory_regions(self):
        """Test basic STM32-style memory regions (bare-arm example)"""
        script_content = """
        /* GNU linker script for STM32F405 */

        MEMORY
        {
            FLASH (rx)      : ORIGIN = 0x08000000, LENGTH = 0x100000 /* entire flash, 1 MiB */
            RAM (xrw)       : ORIGIN = 0x20000000, LENGTH = 0x020000 /* 128 KiB */
        }

        _estack = ORIGIN(RAM) + LENGTH(RAM);
        """

        script_path = self.create_temp_linker_script(script_content)
        parser = LinkerScriptParser([script_path])
        regions = parser.parse_memory_regions()

        self.assertEqual(len(regions), 2)

        # Check FLASH region
        self.assertIn('FLASH', regions)
        flash = regions['FLASH']
        self.assertEqual(flash['address'], 0x08000000)
        self.assertEqual(flash['limit_size'], 1048576)  # 1 MiB
        self.assertEqual(flash['attributes'], 'rx')

        # Check RAM region
        self.assertIn('RAM', regions)
        ram = regions['RAM']
        self.assertEqual(ram['address'], 0x20000000)
        self.assertEqual(ram['limit_size'], 131072)  # 128 KiB
        self.assertEqual(ram['attributes'], 'xrw')

    def test_qemu_risc_v_origin_length_functions(self):
        """Test QEMU RISC-V style ORIGIN() and LENGTH() functions"""
        script_content = """
        /*
         * QEMU RISC-V Virtual Machine Memory Layout
         */
        MEMORY
        {
            ROM   (xr)  : ORIGIN = 0x80000000,                LENGTH = 4M
            RAM   (xrw) : ORIGIN = ORIGIN(ROM) + LENGTH(ROM), LENGTH = 2M
            STACK (rw)  : ORIGIN = ORIGIN(RAM) + LENGTH(RAM), LENGTH = 64K
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        parser = LinkerScriptParser([script_path])
        regions = parser.parse_memory_regions()

        self.assertEqual(len(regions), 3)

        # Check ROM region
        self.assertIn('ROM', regions)
        rom = regions['ROM']
        self.assertEqual(rom['address'], 0x80000000)
        self.assertEqual(rom['limit_size'], 4 * 1024 * 1024)  # 4M

        # Check RAM region (should be ROM base + ROM size)
        self.assertIn('RAM', regions)
        ram = regions['RAM']
        self.assertEqual(
            ram['address'],
            0x80000000 +
            4 *
            1024 *
            1024)  # 0x80400000
        self.assertEqual(ram['limit_size'], 2 * 1024 * 1024)  # 2M

        # Check STACK region (should be RAM base + RAM size)
        self.assertIn('STACK', regions)
        stack = regions['STACK']
        self.assertEqual(
            stack['address'],
            0x80000000 +
            6 *
            1024 *
            1024)  # 0x80600000
        self.assertEqual(stack['limit_size'], 64 * 1024)  # 64K

    def test_samd_variable_resolution(self):
        """Test SAMD-style variable resolution with _codesize"""
        script_content = """
        /*
            GNU linker script for SAMD51
        */

        /*
        _codesize is defined in mpconfigmcu.mk or mpconfigboard.mk as
        MICROPY_HW_CODESIZE and is set in Makefile
        */

        _flashsize = 512K;  /* The physical flash size */
        _bootloader = 16K;  /* Must match the ORIGIN value of FLASH */
        _codesize = 64K;    /* Set by build system */

        /* Specify the memory areas */
        MEMORY
        {
            FLASH (rx)  : ORIGIN = 0x00004000, LENGTH = _codesize
            RAM (xrw)   : ORIGIN = 0x20000000, LENGTH = 192K
        }

        /* Top end of the stack, with room for double-tap variable */
        _estack = ORIGIN(RAM) + LENGTH(RAM) - 8;
        _sstack = _estack - 16K;
        """

        script_path = self.create_temp_linker_script(script_content)
        parser = LinkerScriptParser([script_path])
        regions = parser.parse_memory_regions()

        self.assertEqual(len(regions), 2)

        # Check FLASH region (should use _codesize variable)
        self.assertIn('FLASH', regions)
        flash = regions['FLASH']
        self.assertEqual(flash['address'], 0x00004000)
        self.assertEqual(flash['limit_size'], 64 * 1024)  # 64K from _codesize

        # Check RAM region
        self.assertIn('RAM', regions)
        ram = regions['RAM']
        self.assertEqual(ram['address'], 0x20000000)
        self.assertEqual(ram['limit_size'], 192 * 1024)  # 192K

    def test_stm32_hierarchical_memory_regions(self):
        """Test STM32-style hierarchical memory regions"""
        script_content = """
        /*
            GNU linker script for STM32F405 with hierarchical regions
        */

        /* Specify the memory areas */
        MEMORY
        {
            FLASH (rx)      : ORIGIN = 0x08000000, LENGTH = 1024K /* entire flash */
            FLASH_START (rx): ORIGIN = 0x08000000, LENGTH = 16K /* sector 0 */
            FLASH_FS (rx)   : ORIGIN = 0x08004000, LENGTH = 112K /* sectors 1,2,3,4 are for filesystem */
            FLASH_TEXT (rx) : ORIGIN = 0x08020000, LENGTH = 896K /* sectors 5,6,7,8,9,10,11 */
            CCMRAM (xrw)    : ORIGIN = 0x10000000, LENGTH = 64K
            RAM (xrw)       : ORIGIN = 0x20000000, LENGTH = 128K
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        parser = LinkerScriptParser([script_path])
        regions = parser.parse_memory_regions()

        self.assertEqual(len(regions), 6)

        # Check main FLASH region
        self.assertIn('FLASH', regions)
        flash = regions['FLASH']
        self.assertEqual(flash['address'], 0x08000000)
        self.assertEqual(flash['limit_size'], 1024 * 1024)

        # Check FLASH_START sub-region
        self.assertIn('FLASH_START', regions)
        flash_start = regions['FLASH_START']
        self.assertEqual(flash_start['address'], 0x08000000)
        self.assertEqual(flash_start['limit_size'], 16 * 1024)

        # Check FLASH_FS sub-region
        self.assertIn('FLASH_FS', regions)
        flash_fs = regions['FLASH_FS']
        self.assertEqual(flash_fs['address'], 0x08004000)
        self.assertEqual(flash_fs['limit_size'], 112 * 1024)

        # Check FLASH_TEXT sub-region
        self.assertIn('FLASH_TEXT', regions)
        flash_text = regions['FLASH_TEXT']
        self.assertEqual(flash_text['address'], 0x08020000)
        self.assertEqual(flash_text['limit_size'], 896 * 1024)

        # Check CCMRAM region
        self.assertIn('CCMRAM', regions)
        ccmram = regions['CCMRAM']
        self.assertEqual(ccmram['address'], 0x10000000)
        self.assertEqual(ccmram['limit_size'], 64 * 1024)

        # Check RAM region
        self.assertIn('RAM', regions)
        ram = regions['RAM']
        self.assertEqual(ram['address'], 0x20000000)
        self.assertEqual(ram['limit_size'], 128 * 1024)

    def test_mimxrt_complex_expressions(self):
        """Test MIMXRT-style complex memory layout with expressions"""
        script_content = """
        /* Memory configuration for MIMXRT1062 */
        flash_start         = 0x60000000;
        flash_size          = 0x800000;  /* 8MB */
        flash_end           = flash_start + flash_size;
        flash_config_start  = flash_start;
        flash_config_size   = 0x00001000;
        ivt_start           = flash_start + 0x00001000;
        ivt_size            = 0x00001000;
        interrupts_start    = flash_start + 0x0000C000;
        interrupts_size     = 0x00000400;
        text_start          = flash_start + 0x0000C400;
        vfs_start           = flash_start + 0x00100000;
        text_size           = vfs_start - text_start;
        vfs_size            = flash_end - vfs_start;
        itcm_start          = 0x00000000;
        itcm_size           = 0x00020000;
        dtcm_start          = 0x20000000;
        dtcm_size           = 0x00020000;
        ocrm_start          = 0x20200000;
        ocrm_size           = 0x000C0000;

        /* Specify the memory areas */
        MEMORY
        {
          m_flash_config (RX) : ORIGIN = flash_config_start,    LENGTH = flash_config_size
          m_ivt          (RX) : ORIGIN = ivt_start,             LENGTH = ivt_size
          m_interrupts   (RX) : ORIGIN = interrupts_start,      LENGTH = interrupts_size
          m_text         (RX) : ORIGIN = text_start,            LENGTH = text_size
          m_vfs          (RX) : ORIGIN = vfs_start,             LENGTH = vfs_size
          m_isr          (RX) : ORIGIN = itcm_start,            LENGTH = 0x400
          m_itcm         (RX) : ORIGIN = itcm_start + 0x400,    LENGTH = itcm_size - 0x400
          m_dtcm         (RW) : ORIGIN = dtcm_start,            LENGTH = dtcm_size
          m_ocrm         (RW) : ORIGIN = ocrm_start,            LENGTH = ocrm_size
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        parser = LinkerScriptParser([script_path])
        regions = parser.parse_memory_regions()

        self.assertEqual(len(regions), 9)

        # Check flash config region
        self.assertIn('m_flash_config', regions)
        flash_config = regions['m_flash_config']
        self.assertEqual(flash_config['address'], 0x60000000)
        self.assertEqual(flash_config['limit_size'], 0x1000)

        # Check IVT region
        self.assertIn('m_ivt', regions)
        ivt = regions['m_ivt']
        self.assertEqual(ivt['address'], 0x60001000)
        self.assertEqual(ivt['limit_size'], 0x1000)

        # Check interrupts region
        self.assertIn('m_interrupts', regions)
        interrupts = regions['m_interrupts']
        self.assertEqual(interrupts['address'], 0x6000C000)
        self.assertEqual(interrupts['limit_size'], 0x400)

        # Check text region (calculated from expression)
        self.assertIn('m_text', regions)
        text = regions['m_text']
        self.assertEqual(text['address'], 0x6000C400)
        expected_text_size = 0x60100000 - 0x6000C400  # vfs_start - text_start
        self.assertEqual(text['limit_size'], expected_text_size)

        # Check VFS region (calculated from expression)
        self.assertIn('m_vfs', regions)
        vfs = regions['m_vfs']
        self.assertEqual(vfs['address'], 0x60100000)
        expected_vfs_size = 0x60800000 - 0x60100000  # flash_end - vfs_start
        self.assertEqual(vfs['limit_size'], expected_vfs_size)

        # Check DTCM region
        self.assertIn('m_dtcm', regions)
        dtcm = regions['m_dtcm']
        self.assertEqual(dtcm['address'], 0x20000000)
        self.assertEqual(dtcm['limit_size'], 0x20000)

        # Check OCRM region
        self.assertIn('m_ocrm', regions)
        ocrm = regions['m_ocrm']
        self.assertEqual(ocrm['address'], 0x20200000)
        self.assertEqual(ocrm['limit_size'], 0xC0000)

    def test_esp8266_alternative_syntax(self):
        """Test ESP8266-style alternative syntax without attributes in parentheses"""
        script_content = """
        MEMORY
        {
          dram0_0_seg : org = 0x3ffe8000, len = 80K
          iram1_0_seg : org = 0x40100000, len = 32K
          irom0_0_seg : org = 0x40210000, len = 1024K
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        parser = LinkerScriptParser([script_path])
        regions = parser.parse_memory_regions()

        self.assertEqual(len(regions), 3)

        # Check dram0_0_seg region
        self.assertIn('dram0_0_seg', regions)
        dram = regions['dram0_0_seg']
        self.assertEqual(dram['address'], 0x3ffe8000)
        self.assertEqual(dram['limit_size'], 80 * 1024)

        # Check iram1_0_seg region
        self.assertIn('iram1_0_seg', regions)
        iram = regions['iram1_0_seg']
        self.assertEqual(iram['address'], 0x40100000)
        self.assertEqual(iram['limit_size'], 32 * 1024)

        # Check irom0_0_seg region
        self.assertIn('irom0_0_seg', regions)
        irom = regions['irom0_0_seg']
        self.assertEqual(irom['address'], 0x40210000)
        self.assertEqual(irom['limit_size'], 1024 * 1024)

    def test_preprocessor_handling(self):
        """Test handling of preprocessor directives"""
        script_content = """
        /* Test preprocessor handling */
        _flash_size = 512K;
        _ram_size = 128K;

        // This is a C++ style comment
        /* This is a C style comment */

        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = _flash_size
            RAM (xrw)  : ORIGIN = 0x20000000, LENGTH = _ram_size
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        parser = LinkerScriptParser([script_path])
        regions = parser.parse_memory_regions()

        self.assertEqual(len(regions), 2)

        # Check that regions were parsed despite preprocessor directives
        self.assertIn('FLASH', regions)
        self.assertIn('RAM', regions)

        flash = regions['FLASH']
        self.assertEqual(flash['address'], 0x08000000)
        self.assertEqual(
            flash['limit_size'],
            512 * 1024)  # _flash_size resolved

        ram = regions['RAM']
        self.assertEqual(ram['address'], 0x20000000)
        self.assertEqual(ram['limit_size'], 128 * 1024)  # _ram_size resolved

    def test_conditional_expressions(self):
        """Test conditional expressions with DEFINED() function"""
        script_content = """
        reserved_size = 0x1000;
        flash_start = 0x60000000;
        flash_size = 0x800000;

        flash_end = DEFINED(reserved_size) ? ((flash_start) + (flash_size - reserved_size)) : ((flash_start) + (flash_size));

        MEMORY
        {
            FLASH (rx) : ORIGIN = flash_start, LENGTH = flash_end - flash_start
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        parser = LinkerScriptParser([script_path])
        regions = parser.parse_memory_regions()

        self.assertEqual(len(regions), 1)

        self.assertIn('FLASH', regions)
        flash = regions['FLASH']
        self.assertEqual(flash['address'], 0x60000000)
        # Should use the DEFINED(reserved_size) ? true_value : false_value
        # expression
        expected_length = 0x800000 - 0x1000  # flash_size - reserved_size
        self.assertEqual(flash['limit_size'], expected_length)

    def test_size_suffixes(self):
        """Test various size suffix formats (K, M, G, KB, MB, GB)"""
        script_content = """
        MEMORY
        {
            FLASH1 (rx) : ORIGIN = 0x08000000, LENGTH = 1024K
            FLASH2 (rx) : ORIGIN = 0x08100000, LENGTH = 1M
            FLASH3 (rx) : ORIGIN = 0x08200000, LENGTH = 512KB
            FLASH4 (rx) : ORIGIN = 0x08300000, LENGTH = 2MB
            RAM1 (xrw)  : ORIGIN = 0x20000000, LENGTH = 128K
            RAM2 (xrw)  : ORIGIN = 0x20020000, LENGTH = 256KB
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        parser = LinkerScriptParser([script_path])
        regions = parser.parse_memory_regions()

        self.assertEqual(len(regions), 6)

        # Test K suffix
        flash1 = regions['FLASH1']
        self.assertEqual(flash1['limit_size'], 1024 * 1024)

        # Test M suffix
        flash2 = regions['FLASH2']
        self.assertEqual(flash2['limit_size'], 1024 * 1024)

        # Test KB suffix
        flash3 = regions['FLASH3']
        self.assertEqual(flash3['limit_size'], 512 * 1024)

        # Test MB suffix
        flash4 = regions['FLASH4']
        self.assertEqual(flash4['limit_size'], 2 * 1024 * 1024)

        # Test K on RAM
        ram1 = regions['RAM1']
        self.assertEqual(ram1['limit_size'], 128 * 1024)

        # Test KB on RAM
        ram2 = regions['RAM2']
        self.assertEqual(ram2['limit_size'], 256 * 1024)

    def test_hex_and_decimal_formats(self):
        """Test various numeric formats (hex, decimal, octal)"""
        script_content = """
        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 0x100000
            RAM1 (xrw) : ORIGIN = 0x20000000, LENGTH = 131072
            RAM2 (xrw) : ORIGIN = 0X30000000, LENGTH = 0X20000
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        parser = LinkerScriptParser([script_path])
        regions = parser.parse_memory_regions()

        self.assertEqual(len(regions), 3)

        # Test lowercase hex
        flash = regions['FLASH']
        self.assertEqual(flash['address'], 0x08000000)
        self.assertEqual(flash['limit_size'], 0x100000)

        # Test decimal
        ram1 = regions['RAM1']
        self.assertEqual(ram1['address'], 0x20000000)
        self.assertEqual(ram1['limit_size'], 131072)

        # Test uppercase hex
        ram2 = regions['RAM2']
        self.assertEqual(ram2['address'], 0x30000000)
        self.assertEqual(ram2['limit_size'], 0x20000)

    def test_region_type_detection(self):
        """Test memory region type detection based on names and attributes"""
        script_content = """
        MEMORY
        {
            FLASH (rx)     : ORIGIN = 0x08000000, LENGTH = 1M
            BOOTROM (rx)   : ORIGIN = 0x10000000, LENGTH = 512K
            EEPROM (r)     : ORIGIN = 0x08100000, LENGTH = 4K
            RAM (xrw)      : ORIGIN = 0x20000000, LENGTH = 128K
            SRAM (rw)      : ORIGIN = 0x20020000, LENGTH = 64K
            CCMRAM (xrw)   : ORIGIN = 0x10000000, LENGTH = 64K
            BACKUP (rw)    : ORIGIN = 0x40000000, LENGTH = 4K
            UNKNOWN (abc)  : ORIGIN = 0x50000000, LENGTH = 1K
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        parser = LinkerScriptParser([script_path])
        regions = parser.parse_memory_regions()

        self.assertEqual(len(regions), 8)

        # Test FLASH type detection

        # Test BOOTROM type detection (gets categorized as FLASH due to 'rom'
        # pattern)

        # Test EEPROM type detection

        # Test RAM type detection

        # Test SRAM type detection (should be categorized as RAM)

        # Test CCMRAM type detection (Core Coupled Memory)

        # Test BACKUP type detection

        # Test unknown type detection

    def test_parse_linker_scripts_convenience_function(self):
        """Test the parse_linker_scripts convenience function"""
        script_content = """
        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 1M
            RAM (xrw)  : ORIGIN = 0x20000000, LENGTH = 128K
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        regions = parse_linker_scripts([script_path])

        self.assertEqual(len(regions), 2)
        self.assertIn('FLASH', regions)
        self.assertIn('RAM', regions)

    def test_validation_function(self):
        """Test the validate_memory_regions function"""
        # Test with valid regions
        regions = {
            'FLASH': {
                'type': 'FLASH',
                'address': 0x08000000,
                'end_address': 0x080FFFFF,
                'limit_size': 1048576
            },
            'RAM': {
                'type': 'RAM',
                'address': 0x20000000,
                'end_address': 0x2001FFFF,
                'limit_size': 131072
            }
        }

        # Should be valid (has both FLASH and RAM)
        self.assertTrue(validate_memory_regions(regions))

        # Test with empty regions
        self.assertFalse(validate_memory_regions({}))

        # Test with only FLASH (should warn but not fail validation)
        flash_only = {'FLASH': regions['FLASH']}
        self.assertTrue(validate_memory_regions(flash_only))

    def test_multi_script_parsing(self):
        """Test parsing multiple linker scripts together"""
        # Create first script with basic memory layout
        script1_content = """
        flash_start = 0x60000000;
        flash_size = 0x800000;

        MEMORY
        {
            FLASH (rx) : ORIGIN = flash_start, LENGTH = flash_size
        }
        """

        # Create second script that uses variables from first
        script2_content = """
        dtcm_start = 0x20000000;
        dtcm_size = 0x20000;

        MEMORY
        {
            DTCM (rw) : ORIGIN = dtcm_start, LENGTH = dtcm_size
        }
        """

        script1_path = self.create_temp_linker_script(script1_content)
        script2_path = self.create_temp_linker_script(script2_content)

        parser = LinkerScriptParser([script1_path, script2_path])
        regions = parser.parse_memory_regions()

        self.assertEqual(len(regions), 2)

        # Check FLASH from first script
        self.assertIn('FLASH', regions)
        flash = regions['FLASH']
        self.assertEqual(flash['address'], 0x60000000)
        self.assertEqual(flash['limit_size'], 0x800000)

        # Check DTCM from second script
        self.assertIn('DTCM', regions)
        dtcm = regions['DTCM']
        self.assertEqual(dtcm['address'], 0x20000000)
        self.assertEqual(dtcm['limit_size'], 0x20000)

    def test_error_handling(self):
        """Test error handling for invalid inputs"""
        # Test with non-existent file
        with self.assertRaises(FileNotFoundError):
            LinkerScriptParser(['/non/existent/file.ld'])

        # Test with invalid memory region syntax
        invalid_script = """
        MEMORY
        {
            INVALID : ORIGIN = invalid_value, LENGTH = bad_length
        }
        """

        script_path = self.create_temp_linker_script(invalid_script)
        parser = LinkerScriptParser([script_path])

        # Should raise RegionParsingError for invalid syntax
        with self.assertRaises(RegionParsingError):
            parser.parse_memory_regions()


class TestRealWorldScriptPatterns(unittest.TestCase):
    """Test patterns found in real MicroPython linker scripts"""

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_files = []

    def tearDown(self):
        """Clean up temporary files"""
        for temp_file in self.temp_files:
            try:
                os.unlink(temp_file)
            except OSError:
                pass
        try:
            os.rmdir(self.temp_dir)
        except OSError:
            pass

    def create_temp_linker_script(self, content: str) -> str:
        """Create a temporary linker script file with given content"""
        temp_file = os.path.join(
            self.temp_dir,
            f"test_{len(self.temp_files)}.ld")
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(content)
        self.temp_files.append(temp_file)
        return temp_file

    def test_nrf_softdevice_pattern(self):
        """Test Nordic nRF SoftDevice memory layout pattern"""
        script_content = """
        /* nRF52 with SoftDevice S140 */
        _sd_size = 0x26000;
        _sd_ram = 0x1FA8;
        _fs_size = 64K;

        MEMORY
        {
          FLASH (rx) : ORIGIN = 0x00000000 + _sd_size, LENGTH = 1024K - _sd_size - _fs_size
          RAM (rwx)  : ORIGIN = 0x20000000 + _sd_ram,  LENGTH = 256K - _sd_ram
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        parser = LinkerScriptParser([script_path])
        regions = parser.parse_memory_regions()

        self.assertEqual(len(regions), 2)

        # Check FLASH region (offset by SoftDevice size)
        flash = regions['FLASH']
        expected_flash_origin = 0x00000000 + 0x26000
        expected_flash_length = 1024 * 1024 - 0x26000 - 64 * 1024
        self.assertEqual(flash['address'], expected_flash_origin)
        self.assertEqual(flash['limit_size'], expected_flash_length)

        # Check RAM region (offset by SoftDevice RAM)
        ram = regions['RAM']
        expected_ram_origin = 0x20000000 + 0x1FA8
        expected_ram_length = 256 * 1024 - 0x1FA8
        self.assertEqual(ram['address'], expected_ram_origin)
        self.assertEqual(ram['limit_size'], expected_ram_length)

    def test_parenthesized_expressions(self):
        """Test complex parenthesized expressions in memory definitions"""
        script_content = """
        vfs_start = 0x60100000;
        vfs_size = 0x700000;
        reserved_size = 0x1000;

        MEMORY
        {
            VFS (rx)      : ORIGIN = vfs_start, LENGTH = vfs_size
            RESERVED (rx) : ORIGIN = (vfs_start + vfs_size), LENGTH = reserved_size
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        parser = LinkerScriptParser([script_path])
        regions = parser.parse_memory_regions()

        self.assertEqual(len(regions), 2)

        # Check VFS region
        vfs = regions['VFS']
        self.assertEqual(vfs['address'], 0x60100000)
        self.assertEqual(vfs['limit_size'], 0x700000)

        # Check RESERVED region (should evaluate parenthesized expression)
        reserved = regions['RESERVED']
        expected_origin = 0x60100000 + 0x700000  # vfs_start + vfs_size
        self.assertEqual(reserved['address'], expected_origin)
        self.assertEqual(reserved['limit_size'], 0x1000)


class TestUserVariables(unittest.TestCase):
    """Test user-provided variable support via user_variables parameter"""

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_files = []

    def tearDown(self):
        """Clean up temporary files"""
        for temp_file in self.temp_files:
            try:
                os.unlink(temp_file)
            except OSError:
                pass
        try:
            os.rmdir(self.temp_dir)
        except OSError:
            pass

    def create_temp_linker_script(self, content: str) -> str:
        """Create a temporary linker script file with given content"""
        temp_file = os.path.join(
            self.temp_dir,
            f"test_{len(self.temp_files)}.ld")
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(content)
        self.temp_files.append(temp_file)
        return temp_file

    def test_user_variable_basic(self):
        """Test basic user variable substitution"""
        script_content = """
        MEMORY
        {
            FLASH (rx) : ORIGIN = flash_start, LENGTH = flash_size
            RAM (rwx)  : ORIGIN = ram_start, LENGTH = ram_size
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        user_vars = {
            'flash_start': '0x08000000',
            'flash_size': '512K',
            'ram_start': '0x20000000',
            'ram_size': '128K'
        }
        parser = LinkerScriptParser([script_path], user_variables=user_vars)
        regions = parser.parse_memory_regions()

        self.assertEqual(len(regions), 2)
        self.assertEqual(regions['FLASH']['address'], 0x08000000)
        self.assertEqual(regions['FLASH']['limit_size'], 512 * 1024)
        self.assertEqual(regions['RAM']['address'], 0x20000000)
        self.assertEqual(regions['RAM']['limit_size'], 128 * 1024)

    def test_user_variable_override_architecture_defaults(self):
        """Test that user variables override architecture defaults"""
        # This test simulates architecture defaults being overridden
        script_content = """
        MEMORY
        {
            FLASH (rx) : ORIGIN = _flash_origin, LENGTH = _flash_size
        }
        """

        script_path = self.create_temp_linker_script(script_content)

        # User provides custom values
        user_vars = {
            '_flash_origin': '0x10000000',  # Custom start address
            '_flash_size': '2M'             # Custom size
        }

        parser = LinkerScriptParser([script_path], user_variables=user_vars)
        regions = parser.parse_memory_regions()

        self.assertEqual(regions['FLASH']['address'], 0x10000000)
        self.assertEqual(regions['FLASH']['limit_size'], 2 * 1024 * 1024)

    def test_user_variable_in_expressions(self):
        """Test user variables in arithmetic expressions"""
        script_content = """
        MEMORY
        {
            FLASH (rx)  : ORIGIN = base_addr, LENGTH = total_size - reserved_size
            RAM (rwx)   : ORIGIN = base_addr + total_size, LENGTH = ram_size
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        user_vars = {
            'base_addr': '0x08000000',
            'total_size': '1M',
            'reserved_size': '64K',
            'ram_size': '256K'
        }
        parser = LinkerScriptParser([script_path], user_variables=user_vars)
        regions = parser.parse_memory_regions()

        expected_flash_size = (1024 * 1024) - (64 * 1024)  # 1M - 64K
        self.assertEqual(regions['FLASH']['address'], 0x08000000)
        self.assertEqual(regions['FLASH']['limit_size'], expected_flash_size)
        self.assertEqual(regions['RAM']['address'], 0x08000000 + (1024 * 1024))
        self.assertEqual(regions['RAM']['limit_size'], 256 * 1024)

    def test_user_variable_with_hex_values(self):
        """Test user variables with hexadecimal values"""
        script_content = """
        MEMORY
        {
            FLASH (rx) : ORIGIN = flash_base, LENGTH = flash_len
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        user_vars = {
            'flash_base': '0x08000000',
            'flash_len': '0x80000'  # 512KB in hex
        }
        parser = LinkerScriptParser([script_path], user_variables=user_vars)
        regions = parser.parse_memory_regions()

        self.assertEqual(regions['FLASH']['address'], 0x08000000)
        self.assertEqual(regions['FLASH']['limit_size'], 0x80000)

    def test_user_variable_with_size_suffixes(self):
        """Test user variables with K/M/G size suffixes"""
        script_content = """
        MEMORY
        {
            FLASH_1M (rx) : ORIGIN = 0x08000000, LENGTH = size_1m
            FLASH_4K (rx) : ORIGIN = 0x09000000, LENGTH = size_4k
            FLASH_2G (rx) : ORIGIN = 0x10000000, LENGTH = size_2g
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        user_vars = {
            'size_1m': '1M',
            'size_4k': '4K',
            'size_2g': '2G'
        }
        parser = LinkerScriptParser([script_path], user_variables=user_vars)
        regions = parser.parse_memory_regions()

        self.assertEqual(regions['FLASH_1M']['limit_size'], 1024 * 1024)
        self.assertEqual(regions['FLASH_4K']['limit_size'], 4 * 1024)
        self.assertEqual(regions['FLASH_2G']['limit_size'], 2 * 1024 * 1024 * 1024)

    def test_user_variable_script_override(self):
        """Test that script-defined variables override user variables"""
        script_content = """
        flash_size = 1M;

        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = flash_size
        }
        """

        script_path = self.create_temp_linker_script(script_content)

        # User provides different value, but script should win
        user_vars = {
            'flash_size': '512K'  # This should be overridden by script
        }

        parser = LinkerScriptParser([script_path], user_variables=user_vars)
        regions = parser.parse_memory_regions()

        # Script defines flash_size = 1M, so it should override user's 512K
        self.assertEqual(regions['FLASH']['limit_size'], 1024 * 1024)

    def test_user_variable_only_no_script_vars(self):
        """Test using only user variables without any script-defined variables"""
        script_content = """
        MEMORY
        {
            BOOTLOADER (rx) : ORIGIN = boot_start, LENGTH = boot_len
            APP (rx)        : ORIGIN = app_start, LENGTH = app_len
            RAM (rwx)       : ORIGIN = ram_start, LENGTH = ram_len
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        user_vars = {
            'boot_start': '0x00000000',
            'boot_len': '32K',
            'app_start': '0x00008000',
            'app_len': '480K',
            'ram_start': '0x20000000',
            'ram_len': '64K'
        }
        parser = LinkerScriptParser([script_path], user_variables=user_vars)
        regions = parser.parse_memory_regions()

        self.assertEqual(len(regions), 3)
        self.assertEqual(regions['BOOTLOADER']['address'], 0x00000000)
        self.assertEqual(regions['BOOTLOADER']['limit_size'], 32 * 1024)
        self.assertEqual(regions['APP']['address'], 0x00008000)
        self.assertEqual(regions['APP']['limit_size'], 480 * 1024)
        self.assertEqual(regions['RAM']['address'], 0x20000000)
        self.assertEqual(regions['RAM']['limit_size'], 64 * 1024)

    def test_user_variable_with_numeric_values(self):
        """Test user variables with plain numeric values (no hex prefix)"""
        script_content = """
        MEMORY
        {
            FLASH (rx) : ORIGIN = origin_addr, LENGTH = length_bytes
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        user_vars = {
            'origin_addr': '134217728',  # 0x08000000 in decimal
            'length_bytes': '524288'     # 512K in decimal
        }
        parser = LinkerScriptParser([script_path], user_variables=user_vars)
        regions = parser.parse_memory_regions()

        self.assertEqual(regions['FLASH']['address'], 134217728)
        self.assertEqual(regions['FLASH']['limit_size'], 524288)

    def test_user_variable_empty_dict(self):
        """Test that empty user_variables dict works correctly"""
        script_content = """
        _flash_size = 512K;

        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = _flash_size
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        parser = LinkerScriptParser([script_path], user_variables={})
        regions = parser.parse_memory_regions()

        self.assertEqual(regions['FLASH']['limit_size'], 512 * 1024)

    def test_user_variable_none(self):
        """Test that None user_variables works correctly"""
        script_content = """
        _ram_size = 128K;

        MEMORY
        {
            RAM (rwx) : ORIGIN = 0x20000000, LENGTH = _ram_size
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        parser = LinkerScriptParser([script_path], user_variables=None)
        regions = parser.parse_memory_regions()

        self.assertEqual(regions['RAM']['limit_size'], 128 * 1024)

    def test_user_variable_micropython_scenario(self):
        """Test real-world MicroPython scenario with configurable flash size"""
        # This simulates MicroPython's build system where flash size is
        # configurable via make variables
        script_content = """
        /* MicroPython linker script */
        __micropy_flash_size__ = DEFINED(__micropy_flash_size__) ? __micropy_flash_size__ : 2M;

        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x00000000, LENGTH = __micropy_flash_size__
        }
        """

        script_path = self.create_temp_linker_script(script_content)

        # Test with 4M configuration
        user_vars = {
            '__micropy_flash_size__': '4M'
        }
        parser = LinkerScriptParser([script_path], user_variables=user_vars)
        regions = parser.parse_memory_regions()

        self.assertEqual(regions['FLASH']['limit_size'], 4 * 1024 * 1024)

    def test_user_variable_complex_expression(self):
        """Test user variables in complex expressions with parentheses"""
        script_content = """
        MEMORY
        {
            APP (rx) : ORIGIN = base + (offset * 2), LENGTH = (total - reserved) / 2
        }
        """

        script_path = self.create_temp_linker_script(script_content)
        user_vars = {
            'base': '0x08000000',
            'offset': '0x4000',
            'total': '1M',
            'reserved': '64K'
        }
        parser = LinkerScriptParser([script_path], user_variables=user_vars)
        regions = parser.parse_memory_regions()

        expected_origin = 0x08000000 + (0x4000 * 2)
        expected_length = ((1024 * 1024) - (64 * 1024)) // 2
        self.assertEqual(regions['APP']['address'], expected_origin)
        self.assertEqual(regions['APP']['limit_size'], expected_length)


if __name__ == '__main__':
    # Configure test output
    import logging
    logging.basicConfig(level=logging.WARNING)  # Reduce noise during tests

    # Run all tests
    unittest.main(verbosity=2)
