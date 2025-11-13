#!/usr/bin/env python3

"""
test_memory_regions.py - Unit tests for memory_regions.py

This test suite covers:
1. Basic linker script parsing
2. Variable and expression support
3. Complex memory layouts
4. Error handling
5. Real-world linker script examples
"""
# pylint: disable=duplicate-code

import sys
import tempfile
import unittest
from pathlib import Path

from membrowse.linker.parser import parse_linker_scripts, LinkerScriptParser
from tests.test_utils import validate_memory_regions

# Add shared directory to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent / 'shared'))


class TestMemoryRegions(unittest.TestCase):
    """Test cases for memory regions parsing functionality"""

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.test_files = []

    def tearDown(self):
        """Clean up test files"""
        for file_path in self.test_files:
            if file_path.exists():
                file_path.unlink()
        if self.temp_dir.exists():
            self.temp_dir.rmdir()

    def create_test_file(self, content: str, filename: str = None) -> Path:
        """Create a temporary test file with given content"""
        if filename is None:
            filename = f"test_{len(self.test_files)}.ld"

        file_path = self.temp_dir / filename
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

        self.test_files.append(file_path)
        return file_path

    def test_basic_memory_regions(self):
        """Test parsing of basic memory regions"""
        content = '''
        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512K
            RAM (rw)   : ORIGIN = 0x20000000, LENGTH = 128K
        }
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        self.assertEqual(len(regions), 2)

        # Test FLASH region
        self.assertIn('FLASH', regions)
        flash = regions['FLASH']
        self.assertEqual(flash['address'], 0x08000000)
        self.assertEqual(flash['limit_size'], 512 * 1024)
        self.assertEqual(flash['attributes'], 'rx')

        # Test RAM region
        self.assertIn('RAM', regions)
        ram = regions['RAM']
        self.assertEqual(ram['address'], 0x20000000)
        self.assertEqual(ram['limit_size'], 128 * 1024)
        self.assertEqual(ram['attributes'], 'rw')

    def test_different_number_formats(self):
        """Test parsing of different number formats"""
        content = '''
        MEMORY
        {
            HEX_UPPER (rx) : ORIGIN = 0X08000000, LENGTH = 0X80000
            HEX_LOWER (rx) : ORIGIN = 0x10000000, LENGTH = 0x40000
            DECIMAL (rw)   : ORIGIN = 134217728, LENGTH = 65536
            OCTAL (rw)     : ORIGIN = 01000000000, LENGTH = 0200000
        }
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        self.assertEqual(len(regions), 4)

        # Test hex upper case
        self.assertEqual(regions['HEX_UPPER']['address'], 0x08000000)
        self.assertEqual(regions['HEX_UPPER']['limit_size'], 0x80000)

        # Test hex lower case
        self.assertEqual(regions['HEX_LOWER']['address'], 0x10000000)
        self.assertEqual(regions['HEX_LOWER']['limit_size'], 0x40000)

        # Test decimal
        self.assertEqual(regions['DECIMAL']['address'], 134217728)
        self.assertEqual(regions['DECIMAL']['limit_size'], 65536)

        # Test octal
        self.assertEqual(regions['OCTAL']['address'], 0o1000000000)
        self.assertEqual(regions['OCTAL']['limit_size'], 0o200000)

    def test_size_suffixes(self):
        """Test parsing of size suffixes (K, M, G, KB, MB, GB)"""
        content = '''
        MEMORY
        {
            FLASH_K (rx)  : ORIGIN = 0x08000000, LENGTH = 512K
            FLASH_KB (rx) : ORIGIN = 0x08100000, LENGTH = 256KB
            RAM_M (rw)    : ORIGIN = 0x20000000, LENGTH = 1M
            RAM_MB (rw)   : ORIGIN = 0x20200000, LENGTH = 2MB
            BIG_G (rw)    : ORIGIN = 0x40000000, LENGTH = 1G
            BIG_GB (rw)   : ORIGIN = 0x80000000, LENGTH = 2GB
        }
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        self.assertEqual(len(regions), 6)

        # Test K and KB
        self.assertEqual(regions['FLASH_K']['limit_size'], 512 * 1024)
        self.assertEqual(regions['FLASH_KB']['limit_size'], 256 * 1024)

        # Test M and MB
        self.assertEqual(regions['RAM_M']['limit_size'], 1024 * 1024)
        self.assertEqual(regions['RAM_MB']['limit_size'], 2 * 1024 * 1024)

        # Test G and GB
        self.assertEqual(regions['BIG_G']['limit_size'], 1024 * 1024 * 1024)
        self.assertEqual(
            regions['BIG_GB']['limit_size'],
            2 * 1024 * 1024 * 1024)

    def test_whitespace_and_formatting(self):
        """Test parsing with various whitespace and formatting styles"""
        content = '''
        MEMORY
        {
            /* Compact format */
            FLASH(rx):ORIGIN=0x08000000,LENGTH=512K

            /* Spaced format */
            RAM   (  rw  )  :  ORIGIN  =  0x20000000  ,  LENGTH  =  128K

            /* Mixed format */
            SRAM2( rwx ): ORIGIN= 0x20020000 , LENGTH =32K

            // C++ style comment
            CCMRAM (rw) : ORIGIN = 0x10000000, LENGTH = 64K // Another comment
        }
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        self.assertEqual(len(regions), 4)

        # All regions should be parsed correctly despite formatting differences
        expected_regions = {
            'FLASH': (0x08000000, 512 * 1024, 'rx'),
            'RAM': (0x20000000, 128 * 1024, 'rw'),
            'SRAM2': (0x20020000, 32 * 1024, 'rwx'),
            'CCMRAM': (0x10000000, 64 * 1024, 'rw')
        }

        for name, (expected_addr, expected_size,
                   expected_attrs) in expected_regions.items():
            self.assertIn(name, regions)
            self.assertEqual(regions[name]['address'], expected_addr)
            self.assertEqual(regions[name]['limit_size'], expected_size)
            self.assertEqual(regions[name]['attributes'], expected_attrs)

    def test_region_type_detection(self):
        """Test memory region parsing (type detection removed)"""
        content = '''
        MEMORY
        {
            FLASH (rx)     : ORIGIN = 0x08000000, LENGTH = 512K
            ROM (rx)       : ORIGIN = 0x08100000, LENGTH = 256K
            RAM (rw)       : ORIGIN = 0x20000000, LENGTH = 128K
            SRAM (rw)      : ORIGIN = 0x20020000, LENGTH = 32K
            EEPROM (rw)    : ORIGIN = 0x08200000, LENGTH = 4K
            CCM (w)        : ORIGIN = 0x10000000, LENGTH = 64K
            BACKUP (rw)    : ORIGIN = 0x40024000, LENGTH = 4K
            UNKNOWN (x)    : ORIGIN = 0x50000000, LENGTH = 1K
        }
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        # Test that all regions are parsed
        self.assertEqual(len(regions), 8)
        self.assertIn('FLASH', regions)
        self.assertIn('ROM', regions)
        self.assertIn('RAM', regions)
        self.assertIn('SRAM', regions)
        self.assertIn('EEPROM', regions)
        self.assertIn('CCM', regions)
        self.assertIn('BACKUP', regions)
        self.assertIn('UNKNOWN', regions)

    def test_multiple_files(self):
        """Test parsing multiple linker script files"""
        content1 = '''
        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512K
            RAM (rw)   : ORIGIN = 0x20000000, LENGTH = 128K
        }
        '''

        content2 = '''
        MEMORY
        {
            SRAM2 (rw)  : ORIGIN = 0x20020000, LENGTH = 32K
            CCMRAM (rw) : ORIGIN = 0x10000000, LENGTH = 64K
        }
        '''

        file1 = self.create_test_file(content1, "memory1.ld")
        file2 = self.create_test_file(content2, "memory2.ld")

        regions = parse_linker_scripts([str(file1), str(file2)])

        # Should have regions from both files
        self.assertEqual(len(regions), 4)
        self.assertIn('FLASH', regions)
        self.assertIn('RAM', regions)
        self.assertIn('SRAM2', regions)
        self.assertIn('CCMRAM', regions)

    def test_no_memory_block(self):
        """Test files without MEMORY blocks"""
        content = '''
        /* Linker script without MEMORY block */
        ENTRY(_start)

        SECTIONS
        {
            .text : { *(.text) }
            .data : { *(.data) }
        }
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        # Should return empty dictionary
        self.assertEqual(len(regions), 0)

    def test_invalid_syntax(self):
        """Test handling of invalid syntax"""
        # pylint: disable=import-outside-toplevel
        from membrowse.linker.parser import RegionParsingError

        content = '''
        MEMORY
        {
            FLASH (rx) : ORIGIN = INVALID_ADDR, LENGTH = 512K
            RAM (rw)   : ORIGIN = 0x20000000, LENGTH = INVALID_SIZE
            BROKEN     : MISSING_PARTS
        }
        '''

        file_path = self.create_test_file(content)

        # Should raise RegionParsingError for unresolvable regions
        with self.assertRaises(RegionParsingError) as context:
            parse_linker_scripts([str(file_path)])

        # Verify the error message mentions the failed regions
        self.assertIn(
            "Could not resolve memory regions", str(
                context.exception))

    def test_case_insensitive_memory_keyword(self):
        """Test case-insensitive MEMORY keyword"""
        content = '''
        memory
        {
            FLASH (rx) : origin = 0x08000000, length = 512K
            RAM (rw)   : ORIGIN = 0x20000000, LENGTH = 128K
        }
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        # Should parse both regions despite case differences
        self.assertEqual(len(regions), 2)
        self.assertIn('FLASH', regions)
        self.assertIn('RAM', regions)

    def test_complex_real_world_example(self):
        """Test with a complex real-world linker script example"""
        content = '''
        /* STM32F4xx memory layout */
        MEMORY
        {
          /* Flash memory */
          FLASH (rx)      : ORIGIN = 0x08000000, LENGTH = 1024K

          /* Main RAM */
          RAM (xrw)       : ORIGIN = 0x20000000, LENGTH = 112K

          /* Core Coupled Memory */
          CCMRAM (rw)     : ORIGIN = 0x10000000, LENGTH = 64K

          /* Additional SRAM */
          SRAM2 (rw)      : ORIGIN = 0x2001C000, LENGTH = 16K

          /* Backup SRAM */
          BACKUP_SRAM(rw) : ORIGIN = 0x40024000, LENGTH = 4K

          /* Option bytes */
          OTP (r)         : ORIGIN = 0x1FFF7800, LENGTH = 528
        }

        /* Some other linker script content */
        ENTRY(Reset_Handler)

        SECTIONS
        {
            .isr_vector : { . = ALIGN(4); } > FLASH
        }
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        self.assertEqual(len(regions), 6)

        # Verify specific regions
        self.assertEqual(regions['FLASH']['address'], 0x08000000)
        self.assertEqual(regions['FLASH']['limit_size'], 1024 * 1024)

        self.assertEqual(regions['RAM']['address'], 0x20000000)
        self.assertEqual(regions['RAM']['limit_size'], 112 * 1024)

        self.assertIn('CCMRAM', regions)
        self.assertIn('BACKUP_SRAM', regions)

    def test_validation_function(self):
        """Test the validate_memory_regions function"""
        # Valid regions
        valid_regions = {
            'FLASH': {
                'type': 'FLASH',
                'address': 0x08000000,
                'end_address': 0x0807FFFF,
                'limit_size': 512 * 1024
            },
            'RAM': {
                'type': 'RAM',
                'address': 0x20000000,
                'end_address': 0x2001FFFF,
                'limit_size': 128 * 1024
            }
        }

        self.assertTrue(validate_memory_regions(valid_regions))

        # Empty regions
        self.assertFalse(validate_memory_regions({}))

        # Overlapping regions
        overlapping_regions = {
            'FLASH1': {
                'type': 'FLASH',
                'address': 0x08000000,
                'end_address': 0x0807FFFF,
                'limit_size': 512 * 1024
            },
            'FLASH2': {
                'type': 'FLASH',
                'address': 0x08040000,  # Overlaps with FLASH1
                'end_address': 0x080BFFFF,
                'limit_size': 512 * 1024
            }
        }

        self.assertFalse(validate_memory_regions(overlapping_regions))

    def test_summary_generation(self):
        """Test manual summary generation from regions dict"""
        regions = {
            'FLASH': {
                'type': 'FLASH',
                'address': 0x08000000,
                'end_address': 0x0807FFFF,
                'limit_size': 512 * 1024,
                'attributes': 'rx'
            },
            'RAM': {
                'type': 'RAM',
                'address': 0x20000000,
                'end_address': 0x2001FFFF,
                'limit_size': 128 * 1024,
                'attributes': 'rw'
            }
        }

        # Generate summary manually from dict
        summary_lines = []
        for name, region in regions.items():
            size_kb = region["limit_size"] / 1024
            line = (
                f"{name:12}: "
                f"0x{region['address']:08x} - 0x{region['end_address']:08x} "
                f"({size_kb:8.1f} KB)")
            summary_lines.append(line)

        summary = "\n".join(summary_lines)

        self.assertIn('FLASH', summary)
        self.assertIn('RAM', summary)
        self.assertIn('0x08000000', summary)
        self.assertIn('0x20000000', summary)
        self.assertIn('512.0 KB', summary)
        self.assertIn('128.0 KB', summary)

    def test_file_not_found(self):
        """Test handling of non-existent files"""
        with self.assertRaises(FileNotFoundError):
            parse_linker_scripts(['/non/existent/file.ld'])

    def test_address_parsing_edge_cases(self):
        """Test edge cases in address parsing"""
        # pylint: disable=import-outside-toplevel
        from membrowse.linker.parser import ExpressionEvaluator, MemoryRegionBuilder

        evaluator = ExpressionEvaluator()
        builder = MemoryRegionBuilder(evaluator)

        # pylint: disable=protected-access
        # Test various address formats
        self.assertEqual(builder._parse_address('0x1000'), 0x1000)
        self.assertEqual(builder._parse_address('0X2000'), 0x2000)
        self.assertEqual(builder._parse_address('4096'), 4096)
        self.assertEqual(builder._parse_address('010000'), 0o10000)  # Octal

        # Test with whitespace
        self.assertEqual(builder._parse_address('  0x1000  '), 0x1000)

    def test_size_parsing_edge_cases(self):
        """Test edge cases in size parsing"""
        # pylint: disable=import-outside-toplevel
        from membrowse.linker.parser import ExpressionEvaluator, MemoryRegionBuilder

        evaluator = ExpressionEvaluator()
        builder = MemoryRegionBuilder(evaluator)

        # pylint: disable=protected-access
        # Test various size formats
        self.assertEqual(builder._parse_size('1024'), 1024)
        self.assertEqual(builder._parse_size('1K'), 1024)
        self.assertEqual(builder._parse_size('1KB'), 1024)
        self.assertEqual(builder._parse_size('2M'), 2 * 1024 * 1024)
        self.assertEqual(builder._parse_size('1G'), 1024 * 1024 * 1024)

        # Test hex sizes
        self.assertEqual(builder._parse_size('0x1000'), 0x1000)
        self.assertEqual(builder._parse_size('0X2000'), 0x2000)

        # Test with whitespace
        self.assertEqual(builder._parse_size('  512K  '), 512 * 1024)


class TestAdvancedLinkerFeatures(unittest.TestCase):
    """Test cases for advanced linker script features that are NOT currently supported"""

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.test_files = []

    def tearDown(self):
        """Clean up test files"""
        for file_path in self.test_files:
            if file_path.exists():
                file_path.unlink()
        if self.temp_dir.exists():
            self.temp_dir.rmdir()

    def create_test_file(self, content: str, filename: str = None) -> Path:
        """Create a temporary test file with given content"""
        if filename is None:
            filename = f"test_{len(self.test_files)}.ld"

        file_path = self.temp_dir / filename
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

        self.test_files.append(file_path)
        return file_path

    def test_variables_now_supported(self):
        """Test that variables are now supported"""
        content = '''
        _flash_start = 0x08000000;
        _flash_size = 512K;

        MEMORY
        {
            FLASH (rx) : ORIGIN = _flash_start, LENGTH = _flash_size
            RAM (rw)   : ORIGIN = 0x20000000, LENGTH = 128K
        }
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        # Variables should now be supported
        self.assertEqual(len(regions), 2)
        self.assertIn('FLASH', regions)
        self.assertIn('RAM', regions)

        # Check that variables were resolved correctly
        self.assertEqual(regions['FLASH']['address'], 0x08000000)
        self.assertEqual(regions['FLASH']['limit_size'], 512 * 1024)
        self.assertEqual(regions['RAM']['address'], 0x20000000)
        self.assertEqual(regions['RAM']['limit_size'], 128 * 1024)

    def test_expressions_now_supported(self):
        """Test that basic arithmetic expressions are now supported"""
        content = '''
        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512 * 1024
            RAM (rw)   : ORIGIN = 0x20000000 + 0x1000, LENGTH = 128K
            SRAM2 (rw) : ORIGIN = 0x20000000 + 128 * 1024, LENGTH = 32K
        }
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        # Expressions should now be supported
        self.assertEqual(len(regions), 3)
        self.assertIn('FLASH', regions)
        self.assertIn('RAM', regions)
        self.assertIn('SRAM2', regions)

        # Check that expressions were evaluated correctly
        self.assertEqual(regions['FLASH']['address'], 0x08000000)
        self.assertEqual(regions['FLASH']['limit_size'], 512 * 1024)
        self.assertEqual(regions['RAM']['address'], 0x20000000 + 0x1000)
        self.assertEqual(regions['SRAM2']['address'], 0x20000000 + 128 * 1024)

    def test_complex_variables_and_expressions(self):
        """Test complex combinations of variables and expressions"""
        content = '''
        /* Base addresses */
        _flash_base = 0x08000000;
        _ram_base = 0x20000000;

        /* Sizes */
        _flash_size = 1024 * 1024;  /* 1MB */
        _ram_size = 256K;

        /* Calculated addresses */
        _sram2_base = _ram_base + _ram_size;

        MEMORY
        {
            FLASH (rx) : ORIGIN = _flash_base, LENGTH = _flash_size
            RAM (rw)   : ORIGIN = _ram_base, LENGTH = _ram_size
            SRAM2 (rw) : ORIGIN = _sram2_base, LENGTH = 64K
        }
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        self.assertEqual(len(regions), 3)

        # Check calculated values
        self.assertEqual(regions['FLASH']['address'], 0x08000000)
        self.assertEqual(regions['FLASH']['limit_size'], 1024 * 1024)
        self.assertEqual(regions['RAM']['address'], 0x20000000)
        self.assertEqual(regions['RAM']['limit_size'], 256 * 1024)
        self.assertEqual(regions['SRAM2']['address'], 0x20000000 + 256 * 1024)
        self.assertEqual(regions['SRAM2']['limit_size'], 64 * 1024)


class TestUserVariablesIntegration(unittest.TestCase):
    """Integration tests for user-defined variables (--def feature)"""

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.test_files = []

    def tearDown(self):
        """Clean up test files"""
        for file_path in self.test_files:
            if file_path.exists():
                file_path.unlink()
        if self.temp_dir.exists():
            self.temp_dir.rmdir()

    def create_test_file(self, content: str, filename: str = None) -> Path:
        """Create a temporary test file with given content"""
        if filename is None:
            filename = f"test_{len(self.test_files)}.ld"

        file_path = self.temp_dir / filename
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

        self.test_files.append(file_path)
        return file_path

    def test_makefile_scenario_with_user_variables(self):
        """Test real-world scenario: Makefile passing variables to linker"""
        # Simulates a Makefile that defines memory sizes and passes them
        # to the linker via -defsym or similar mechanism
        content = '''
        /* Linker script that expects external variables */
        MEMORY
        {
            BOOTLOADER (rx) : ORIGIN = 0x00000000, LENGTH = BOOTLOADER_SIZE
            APPLICATION (rx) : ORIGIN = BOOTLOADER_SIZE, LENGTH = APP_SIZE
            RAM (rwx)        : ORIGIN = 0x20000000, LENGTH = RAM_SIZE
        }
        '''

        file_path = self.create_test_file(content)

        # User variables simulate Makefile definitions:
        # make BOOTLOADER_SIZE=32K APP_SIZE=480K RAM_SIZE=128K
        user_vars = {
            'BOOTLOADER_SIZE': '32K',
            'APP_SIZE': '480K',
            'RAM_SIZE': '128K'
        }

        parser = LinkerScriptParser([str(file_path)], user_variables=user_vars)
        regions = parser.parse_memory_regions()

        self.assertEqual(len(regions), 3)
        self.assertEqual(regions['BOOTLOADER']['address'], 0x00000000)
        self.assertEqual(regions['BOOTLOADER']['limit_size'], 32 * 1024)
        self.assertEqual(regions['APPLICATION']['address'], 32 * 1024)
        self.assertEqual(regions['APPLICATION']['limit_size'], 480 * 1024)
        self.assertEqual(regions['RAM']['address'], 0x20000000)
        self.assertEqual(regions['RAM']['limit_size'], 128 * 1024)

    def test_esp_idf_scenario(self):
        """Test ESP-IDF scenario with partition table variables"""
        # ESP-IDF often uses variables for partition boundaries
        content = '''
        /* ESP32 partition-aware linker script */
        MEMORY
        {
            irom_seg (RX) : ORIGIN = IROM_START, LENGTH = IROM_SIZE
            drom_seg (R)  : ORIGIN = DROM_START, LENGTH = DROM_SIZE
            iram_seg (RWX): ORIGIN = 0x40080000, LENGTH = IRAM_SIZE
            dram_seg (RW) : ORIGIN = 0x3FFB0000, LENGTH = DRAM_SIZE
        }
        '''

        file_path = self.create_test_file(content)

        # Variables from partition table
        user_vars = {
            'IROM_START': '0x400D0000',
            'IROM_SIZE': '3M',
            'DROM_START': '0x3F400000',
            'DROM_SIZE': '4M',
            'IRAM_SIZE': '128K',
            'DRAM_SIZE': '176K'
        }

        parser = LinkerScriptParser([str(file_path)], user_variables=user_vars)
        regions = parser.parse_memory_regions()

        self.assertEqual(regions['irom_seg']['address'], 0x400D0000)
        self.assertEqual(regions['irom_seg']['limit_size'], 3 * 1024 * 1024)
        self.assertEqual(regions['drom_seg']['address'], 0x3F400000)
        self.assertEqual(regions['drom_seg']['limit_size'], 4 * 1024 * 1024)

    def test_multi_variant_build(self):
        """Test multi-variant builds with different memory configurations"""
        # Single linker script used for multiple board variants
        content = '''
        /* Generic linker script for multiple board variants */
        MEMORY
        {
            FLASH (rx) : ORIGIN = FLASH_ORIGIN, LENGTH = FLASH_LENGTH
            RAM (rwx)  : ORIGIN = RAM_ORIGIN, LENGTH = RAM_LENGTH
        }
        '''

        file_path = self.create_test_file(content)

        # Test "small" variant
        small_vars = {
            'FLASH_ORIGIN': '0x08000000',
            'FLASH_LENGTH': '256K',
            'RAM_ORIGIN': '0x20000000',
            'RAM_LENGTH': '64K'
        }

        parser_small = LinkerScriptParser([str(file_path)], user_variables=small_vars)
        regions_small = parser_small.parse_memory_regions()

        self.assertEqual(regions_small['FLASH']['limit_size'], 256 * 1024)
        self.assertEqual(regions_small['RAM']['limit_size'], 64 * 1024)

        # Test "large" variant
        large_vars = {
            'FLASH_ORIGIN': '0x08000000',
            'FLASH_LENGTH': '2M',
            'RAM_ORIGIN': '0x20000000',
            'RAM_LENGTH': '512K'
        }

        parser_large = LinkerScriptParser([str(file_path)], user_variables=large_vars)
        regions_large = parser_large.parse_memory_regions()

        self.assertEqual(regions_large['FLASH']['limit_size'], 2 * 1024 * 1024)
        self.assertEqual(regions_large['RAM']['limit_size'], 512 * 1024)

    def test_user_vars_with_script_expressions(self):
        """Test user variables combined with script expressions"""
        content = '''
        /* Calculated memory layout using user-provided base values */
        _boot_size = 64K;
        _reserved = 16K;

        MEMORY
        {
            BOOT (rx)  : ORIGIN = FLASH_BASE, LENGTH = _boot_size
            APP (rx)   : ORIGIN = FLASH_BASE + _boot_size,
                         LENGTH = FLASH_TOTAL - _boot_size - _reserved
            RESERVE(r) : ORIGIN = FLASH_BASE + FLASH_TOTAL - _reserved,
                         LENGTH = _reserved
            RAM (rwx)  : ORIGIN = RAM_BASE, LENGTH = RAM_TOTAL
        }
        '''

        file_path = self.create_test_file(content)

        user_vars = {
            'FLASH_BASE': '0x08000000',
            'FLASH_TOTAL': '1M',
            'RAM_BASE': '0x20000000',
            'RAM_TOTAL': '256K'
        }

        parser = LinkerScriptParser([str(file_path)], user_variables=user_vars)
        regions = parser.parse_memory_regions()

        # Verify calculated values
        flash_base = 0x08000000
        flash_total = 1024 * 1024
        boot_size = 64 * 1024
        reserved = 16 * 1024

        self.assertEqual(regions['BOOT']['address'], flash_base)
        self.assertEqual(regions['BOOT']['limit_size'], boot_size)
        self.assertEqual(regions['APP']['address'], flash_base + boot_size)
        self.assertEqual(regions['APP']['limit_size'], flash_total - boot_size - reserved)
        self.assertEqual(regions['RESERVE']['address'], flash_base + flash_total - reserved)
        self.assertEqual(regions['RESERVE']['limit_size'], reserved)

    def test_conditional_with_user_variables(self):
        """Test DEFINED() conditional with user variables"""
        content = '''
        /* Linker script with conditional defaults */
        __flash_size = DEFINED(__flash_size) ? __flash_size : 512K;
        __ram_size = DEFINED(__ram_size) ? __ram_size : 128K;

        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = __flash_size
            RAM (rwx)  : ORIGIN = 0x20000000, LENGTH = __ram_size
        }
        '''

        file_path = self.create_test_file(content)

        # Provide custom values via user variables
        user_vars = {
            '__flash_size': '2M',
            '__ram_size': '256K'
        }

        parser = LinkerScriptParser([str(file_path)], user_variables=user_vars)
        regions = parser.parse_memory_regions()

        # User values should override defaults
        self.assertEqual(regions['FLASH']['limit_size'], 2 * 1024 * 1024)
        self.assertEqual(regions['RAM']['limit_size'], 256 * 1024)


if __name__ == '__main__':
    print("Memory Regions Test Suite")
    print("=" * 40)

    # Run the tests
    unittest.main(verbosity=2)
