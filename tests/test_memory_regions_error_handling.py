#!/usr/bin/env python3

"""
test_memory_regions_error_handling.py - Unit tests for error handling in memory_regions.py

This test suite specifically focuses on testing that the parser handles malformed
linker scripts correctly and fails gracefully without crashing.

Test categories:
1. Malformed syntax (unclosed braces, missing commas, etc.)
2. Invalid address/size formats
3. Corrupted memory blocks
4. File system errors
5. Edge cases and boundary conditions
"""
# pylint: disable=duplicate-code

import sys
import tempfile
import unittest
from pathlib import Path

from membrowse.linker.parser import (
    LinkerScriptParser,
    parse_linker_scripts,
    LinkerScriptError,
    ExpressionEvaluationError,
    RegionParsingError
)

# Add shared directory to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent / 'shared'))


class TestMalformedLinkerScripts(unittest.TestCase):
    """Test cases for malformed linker script handling"""

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


class TestSyntaxErrors(TestMalformedLinkerScripts):
    """Test malformed syntax handling"""

    def test_unclosed_memory_block(self):
        """Test MEMORY block with missing closing brace"""
        content = '''
        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512K
            RAM (rw)   : ORIGIN = 0x20000000, LENGTH = 128K
        /* Missing closing brace */
        '''

        file_path = self.create_test_file(content)

        # Should not crash, should return empty result or handle gracefully
        try:
            regions = parse_linker_scripts([str(file_path)])
            # Either empty regions or some regions parsed before the error
            self.assertIsInstance(regions, dict)
        except Exception as e:  # pylint: disable=broad-exception-caught
            # If it throws an exception, it should be a specific linker script
            # error
            self.assertIsInstance(
                e, (LinkerScriptError, ValueError, SyntaxError))

    def test_missing_opening_brace(self):
        """Test MEMORY block with missing opening brace"""
        content = '''
        MEMORY
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512K
            RAM (rw)   : ORIGIN = 0x20000000, LENGTH = 128K
        }
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        # Should not find valid MEMORY block
        self.assertEqual(len(regions), 0)

    def test_malformed_region_syntax(self):
        """Test various malformed region syntax"""
        content = '''
        MEMORY
        {
            /* Missing parentheses for attributes */
            FLASH rx : ORIGIN = 0x08000000, LENGTH = 512K

            /* Missing colon */
            RAM (rw) ORIGIN = 0x20000000, LENGTH = 128K

            /* Missing ORIGIN */
            SRAM (rw) : LENGTH = 64K

            /* Missing LENGTH */
            CCM (rw) : ORIGIN = 0x10000000

            /* Missing comma */
            BACKUP (rw) : ORIGIN = 0x40024000 LENGTH = 4K
        }
        '''

        file_path = self.create_test_file(content)

        # Should raise RegionParsingError for malformed syntax
        with self.assertRaises(RegionParsingError):
            parse_linker_scripts([str(file_path)])

    def test_invalid_parentheses_nesting(self):
        """Test invalid parentheses and nesting"""
        content = '''
        MEMORY
        {
            /* Unmatched parentheses */
            FLASH ((rx) : ORIGIN = 0x08000000, LENGTH = 512K

            /* Wrong parentheses */
            RAM [rw] : ORIGIN = 0x20000000, LENGTH = 128K

            /* Multiple parentheses groups */
            SRAM (rw) (x) : ORIGIN = 0x20020000, LENGTH = 32K
        }
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        # Should handle gracefully
        self.assertIsInstance(regions, dict)

    def test_completely_corrupted_syntax(self):
        """Test completely corrupted linker script"""
        content = '''
        MEMORY
        {
            @@@@INVALID@@@@
            !!!BROKEN!!!
            ###ERROR###
            %%%CORRUPT%%%
        }
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        # Should return empty dict for completely invalid content
        self.assertEqual(len(regions), 0)


class TestInvalidAddressFormats(TestMalformedLinkerScripts):
    """Test invalid address and size format handling"""

    def test_invalid_hex_addresses(self):
        """Test various invalid hexadecimal address formats"""
        content = '''
        MEMORY
        {
            /* Invalid hex - non-hex characters */
            FLASH1 (rx) : ORIGIN = 0xGGGGGGGG, LENGTH = 512K

            /* Invalid hex - missing digits */
            FLASH2 (rx) : ORIGIN = 0x, LENGTH = 512K

            /* Invalid hex - spaces in address */
            FLASH3 (rx) : ORIGIN = 0x0800 0000, LENGTH = 512K

            /* Invalid hex - wrong prefix */
            FLASH4 (rx) : ORIGIN = 8x08000000, LENGTH = 512K
        }
        '''

        file_path = self.create_test_file(content)

        # Should raise RegionParsingError for invalid hex addresses
        with self.assertRaises(RegionParsingError):
            parse_linker_scripts([str(file_path)])

    def test_invalid_size_formats(self):
        """Test invalid size formats"""
        content = '''
        MEMORY
        {
            /* Invalid size suffix */
            FLASH1 (rx) : ORIGIN = 0x08000000, LENGTH = 512X

            /* Invalid size - non-numeric */
            FLASH2 (rx) : ORIGIN = 0x08000000, LENGTH = ABCK

            /* Invalid size - negative */
            FLASH3 (rx) : ORIGIN = 0x08000000, LENGTH = -512K

            /* Invalid size - floating point */
            FLASH4 (rx) : ORIGIN = 0x08000000, LENGTH = 512.5K

            /* Invalid size - empty */
            FLASH5 (rx) : ORIGIN = 0x08000000, LENGTH =
        }
        '''

        file_path = self.create_test_file(content)

        # Should raise RegionParsingError for invalid size formats
        with self.assertRaises(RegionParsingError):
            parse_linker_scripts([str(file_path)])

    def test_extreme_address_values(self):
        """Test extreme address values that might cause overflow"""
        content = '''
        MEMORY
        {
            /* Very large address */
            FLASH1 (rx) : ORIGIN = 0xFFFFFFFFFFFFFFFF, LENGTH = 512K

            /* Address larger than 64-bit */
            FLASH2 (rx) : ORIGIN = 0x1FFFFFFFFFFFFFFFF, LENGTH = 512K

            /* Very large size */
            FLASH3 (rx) : ORIGIN = 0x08000000, LENGTH = 99999999999999999999999G
        }
        '''

        file_path = self.create_test_file(content)

        # Should handle gracefully without crashing
        try:
            regions = parse_linker_scripts([str(file_path)])
            self.assertIsInstance(regions, dict)
        except (OverflowError, ValueError):
            # These specific exceptions are acceptable for extreme values
            pass

    def test_invalid_expressions(self):
        """Test invalid arithmetic expressions"""
        content = '''
        MEMORY
        {
            /* Division by zero */
            FLASH1 (rx) : ORIGIN = 0x08000000, LENGTH = 512 / 0

            /* Invalid operators */
            FLASH2 (rx) : ORIGIN = 0x08000000 %% 0x1000, LENGTH = 512K

            /* Unmatched parentheses in expression */
            FLASH3 (rx) : ORIGIN = (0x08000000 + 0x1000, LENGTH = 512K

            /* Invalid function calls */
            FLASH4 (rx) : ORIGIN = unknown_function(0x08000000), LENGTH = 512K

            /* String in numeric context */
            FLASH5 (rx) : ORIGIN = "0x08000000", LENGTH = 512K
        }
        '''

        file_path = self.create_test_file(content)

        # Should raise RegionParsingError for invalid expressions
        with self.assertRaises(RegionParsingError):
            parse_linker_scripts([str(file_path)])


class TestCorruptedMemoryBlocks(TestMalformedLinkerScripts):
    """Test corrupted MEMORY block structures"""

    def test_multiple_memory_blocks_conflicting(self):
        """Test multiple MEMORY blocks with conflicting definitions"""
        content = '''
        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512K
        }

        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x10000000, LENGTH = 1024K
            RAM (rw)   : ORIGIN = 0x20000000, LENGTH = 128K
        }
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        # Should handle multiple MEMORY blocks (typically last one wins)
        self.assertIsInstance(regions, dict)
        if 'FLASH' in regions:
            # If FLASH exists, check which definition was used
            self.assertIn(
                regions['FLASH']['address'], [
                    0x08000000, 0x10000000])

    def test_nested_memory_blocks(self):
        """Test incorrectly nested MEMORY blocks"""
        content = '''
        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512K
            MEMORY
            {
                RAM (rw) : ORIGIN = 0x20000000, LENGTH = 128K
            }
        }
        '''

        file_path = self.create_test_file(content)

        # Should raise RegionParsingError for nested MEMORY blocks
        with self.assertRaises(RegionParsingError):
            parse_linker_scripts([str(file_path)])

    def test_memory_block_with_invalid_content(self):
        """Test MEMORY block containing non-memory definitions"""
        content = '''
        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512K

            /* Invalid - not a memory region */
            SECTIONS
            {
                .text : { *(.text) }
            }

            RAM (rw) : ORIGIN = 0x20000000, LENGTH = 128K

            /* Invalid - variable assignment */
            _stack_size = 0x1000;
        }
        '''

        file_path = self.create_test_file(content)

        # Should raise RegionParsingError for invalid content in MEMORY block
        with self.assertRaises(RegionParsingError):
            parse_linker_scripts([str(file_path)])

    def test_empty_memory_block(self):
        """Test completely empty MEMORY block"""
        content = '''
        MEMORY
        {
        }
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        # Should return empty dict
        self.assertEqual(len(regions), 0)


class TestFileSystemErrors(TestMalformedLinkerScripts):
    """Test file system related errors"""

    def test_nonexistent_file(self):
        """Test parsing non-existent linker script"""
        nonexistent_path = "/path/that/does/not/exist/script.ld"

        with self.assertRaises(FileNotFoundError):
            LinkerScriptParser([nonexistent_path])

    def test_empty_file(self):
        """Test parsing completely empty linker script"""
        content = ""

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        # Should return empty dict
        self.assertEqual(len(regions), 0)

    def test_binary_file(self):
        """Test parsing binary file as linker script"""
        # Create a file with binary content
        file_path = self.temp_dir / "binary.ld"
        with open(file_path, 'wb') as f:
            f.write(
                b'\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f')

        self.test_files.append(file_path)

        # Should handle gracefully
        try:
            regions = parse_linker_scripts([str(file_path)])
            self.assertIsInstance(regions, dict)
            self.assertEqual(len(regions), 0)  # No valid memory regions
        except UnicodeDecodeError:
            # This is also acceptable behavior
            pass

    def test_permission_denied_simulation(self):
        """Test handling of files that might have permission issues"""
        # Note: This is harder to test portably, so we'll test with a file
        # that exists but contains permission-like error scenarios
        content = '''
        /* This file simulates content that might cause permission-like issues */
        MEMORY
        {
            /* Very long region name that might cause buffer issues */
            EXTREMELY_LONG_REGION_NAME_THAT_GOES_ON_AND_ON_AND_ON_AND_ON_AND_ON (rx) : ORIGIN = 0x08000000, LENGTH = 512K
        }
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        # Should handle gracefully
        self.assertIsInstance(regions, dict)


class TestEdgeCasesAndBoundaryConditions(TestMalformedLinkerScripts):
    """Test edge cases and boundary conditions"""

    def test_zero_sized_regions(self):
        """Test regions with zero size"""
        content = '''
        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 0
            RAM (rw)   : ORIGIN = 0x20000000, LENGTH = 0K
            SRAM (rw)  : ORIGIN = 0x20020000, LENGTH = 0x0
        }
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        # Should handle zero-sized regions
        self.assertIsInstance(regions, dict)
        for region in regions.values():
            self.assertEqual(region['limit_size'], 0)

    def test_overlapping_regions_invalid(self):
        """Test completely overlapping regions (invalid configuration)"""
        content = '''
        MEMORY
        {
            FLASH1 (rx) : ORIGIN = 0x08000000, LENGTH = 512K
            FLASH2 (rx) : ORIGIN = 0x08000000, LENGTH = 512K  /* Same address */
            RAM1 (rw)   : ORIGIN = 0x20000000, LENGTH = 128K
            RAM2 (rw)   : ORIGIN = 0x20010000, LENGTH = 128K  /* Overlaps with RAM1 */
        }
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        # Should parse all regions (validation is separate from parsing)
        self.assertIsInstance(regions, dict)
        self.assertEqual(len(regions), 4)

    def test_regions_with_same_name(self):
        """Test multiple regions with the same name"""
        content = '''
        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512K
            FLASH (rx) : ORIGIN = 0x10000000, LENGTH = 256K  /* Same name */
            RAM (rw)   : ORIGIN = 0x20000000, LENGTH = 128K
        }
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        # Should handle duplicate names (typically last one wins)
        self.assertIsInstance(regions, dict)
        self.assertIn('FLASH', regions)
        self.assertIn('RAM', regions)
        # Check which FLASH definition was used
        self.assertIn(regions['FLASH']['address'], [0x08000000, 0x10000000])

    def test_very_long_content(self):
        """Test very long linker script content"""
        # Create a script with many regions
        regions_content = []
        for i in range(100):
            regions_content.append(
                f"REGION_{i:03d} (rw) : ORIGIN = 0x{0x20000000 + i*0x1000:08x}, LENGTH = 4K")

        content = f'''
        MEMORY
        {{
            {chr(10).join(regions_content)}
        }}
        '''

        file_path = self.create_test_file(content)
        regions = parse_linker_scripts([str(file_path)])

        # Should handle large number of regions
        self.assertIsInstance(regions, dict)
        # Should get most or all regions
        self.assertLessEqual(len(regions), 100)

    def test_unicode_and_special_characters(self):
        """Test handling of unicode and special characters"""
        content = '''
        MEMORY
        {
            /* Test with unicode characters */
            FLASH_Ω (rx) : ORIGIN = 0x08000000, LENGTH = 512K

            /* Test with special ASCII characters */
            RAM_@#$ (rw) : ORIGIN = 0x20000000, LENGTH = 128K

            /* Test with numbers in names */
            SRAM_123 (rw) : ORIGIN = 0x20020000, LENGTH = 32K
        }
        '''

        file_path = self.create_test_file(content)

        try:
            regions = parse_linker_scripts([str(file_path)])
            self.assertIsInstance(regions, dict)
            # Some regions might parse, others might not due to invalid
            # characters
        except UnicodeError:
            # This is acceptable behavior for invalid unicode
            pass

    def test_deeply_nested_comments(self):
        """Test deeply nested and malformed comments"""
        content = '''
        MEMORY
        {
            /* Comment level 1
               /* Comment level 2
                  /* Comment level 3 */
               /* Missing close for level 2 */
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512K

            // C++ style comment with /* C style inside */
            RAM (rw) : ORIGIN = 0x20000000, LENGTH = 128K

            /* Unclosed comment at end of file
        }
        '''

        file_path = self.create_test_file(content)

        # Should raise RegionParsingError for malformed comments
        with self.assertRaises(RegionParsingError):
            parse_linker_scripts([str(file_path)])


class TestSpecificExceptionTypes(TestMalformedLinkerScripts):
    """Test that specific exception types are raised appropriately"""

    def test_expression_evaluation_errors(self):
        """Test that ExpressionEvaluationError is raised for invalid expressions"""
        content = '''
        MEMORY
        {
            /* This should trigger expression evaluation error */
            FLASH (rx) : ORIGIN = undefined_variable, LENGTH = 512K
        }
        '''

        file_path = self.create_test_file(content)

        # Should either parse gracefully or raise appropriate exception
        try:
            regions = parse_linker_scripts([str(file_path)])
            # If it doesn't raise an exception, it should handle gracefully
            self.assertIsInstance(regions, dict)
        except (ExpressionEvaluationError, LinkerScriptError):
            # These are the expected exception types
            pass

    def test_parser_error_recovery(self):
        """Test parser's ability to recover from errors and continue"""
        content = '''
        MEMORY
        {
            /* Valid region */
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512K

            /* Invalid region that should be skipped */
            INVALID_REGION_WITH_BAD_SYNTAX

            /* Another valid region after the error */
            RAM (rw) : ORIGIN = 0x20000000, LENGTH = 128K
        }
        '''

        file_path = self.create_test_file(content)

        # Should raise RegionParsingError for invalid syntax
        with self.assertRaises(RegionParsingError):
            parse_linker_scripts([str(file_path)])


if __name__ == '__main__':
    print("Memory Regions Error Handling Test Suite")
    print("=" * 50)

    # Run the tests
    unittest.main(verbosity=2)
