#!/usr/bin/env python3

"""
test_architecture_detection.py - Unit tests for ELF-based architecture detection

This test suite verifies that the parser correctly detects architectures from ELF files
and applies appropriate parsing strategies.
"""
# pylint: disable=duplicate-code

import os
import sys
import tempfile
import unittest
from pathlib import Path

from membrowse.linker.elf_info import (
    get_architecture_info, get_linker_parsing_strategy,
    Architecture, Platform, ELFInfo
)
from membrowse.linker.parser import LinkerScriptParser, parse_linker_scripts

# Add shared directory to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent / 'shared'))


class TestELFArchitectureDetection(unittest.TestCase):
    """Test ELF architecture detection functionality"""

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

    def create_test_linker_script(self, content: str) -> Path:
        """Create a temporary linker script file"""
        file_path = self.temp_dir / f"test_{len(self.test_files)}.ld"
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        self.test_files.append(file_path)
        return file_path

    def test_esp32_elf_detection(self):
        """Test ESP32 ELF file detection if available"""
        esp32_elf = (
            '/home/michael/projs/membrowse/micropython/build_logs/'
            '4c55b0879b38b373b44e84552d6754b7842b5b72/esp32/firmware.elf')

        if not os.path.exists(esp32_elf):
            self.skipTest("ESP32 ELF file not available")

        elf_info = get_architecture_info(esp32_elf)
        self.assertIsNotNone(elf_info)
        self.assertEqual(elf_info.architecture, Architecture.XTENSA)
        self.assertEqual(elf_info.platform, Platform.ESP32)
        self.assertTrue(elf_info.is_embedded)
        self.assertEqual(elf_info.bit_width, 32)
        self.assertEqual(elf_info.endianness, "little")

    def test_arm_elf_detection(self):
        """Test ARM ELF file detection if available"""
        arm_elf = ('/home/michael/projs/membrowse/micropython/ports/'
                   'bare-arm/build/firmware.elf')

        if not os.path.exists(arm_elf):
            self.skipTest("ARM ELF file not available")

        elf_info = get_architecture_info(arm_elf)
        self.assertIsNotNone(elf_info)
        self.assertEqual(elf_info.architecture, Architecture.ARM)
        self.assertEqual(elf_info.platform, Platform.STM32)
        self.assertTrue(elf_info.is_embedded)
        self.assertEqual(elf_info.bit_width, 32)
        self.assertEqual(elf_info.endianness, "little")

    def test_x86_elf_detection(self):
        """Test x86-64 ELF file detection"""
        x86_elf = '/bin/ls'

        if not os.path.exists(x86_elf):
            self.skipTest("x86-64 ELF file not available")

        elf_info = get_architecture_info(x86_elf)
        self.assertIsNotNone(elf_info)
        self.assertEqual(elf_info.architecture, Architecture.X86_64)
        self.assertEqual(elf_info.platform, Platform.UNIX)
        self.assertFalse(elf_info.is_embedded)
        self.assertEqual(elf_info.bit_width, 64)
        self.assertEqual(elf_info.endianness, "little")

    def test_parsing_strategy_esp32(self):
        """Test ESP32 parsing strategy generation"""
        elf_info = ELFInfo(
            architecture=Architecture.XTENSA,
            platform=Platform.ESP32,
            bit_width=32,
            endianness="little",
            machine_type=0x5E,
            is_embedded=True
        )

        strategy = get_linker_parsing_strategy(elf_info)
        self.assertIn('memory_block_patterns', strategy)
        self.assertIn('esp_style', strategy['memory_block_patterns'])
        self.assertIn('default_variables', strategy)
        # Default variables removed - parser only uses values from linker
        # scripts
        self.assertEqual(strategy['default_variables'], {})

    def test_parsing_strategy_stm32(self):
        """Test STM32 parsing strategy generation"""
        elf_info = ELFInfo(
            architecture=Architecture.ARM,
            platform=Platform.STM32,
            bit_width=32,
            endianness="little",
            machine_type=0x28,
            is_embedded=True
        )

        strategy = get_linker_parsing_strategy(elf_info)
        self.assertIn('memory_block_patterns', strategy)
        self.assertEqual(strategy['memory_block_patterns'], ['standard'])
        self.assertTrue(strategy['hierarchical_validation'])
        self.assertIn('default_variables', strategy)
        # Default variables removed - parser only uses values from linker
        # scripts
        self.assertEqual(strategy['default_variables'], {})

    def test_linker_parser_with_elf(self):
        """Test LinkerScriptParser with ELF file"""
        # Create a simple test linker script
        content = '''
        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512K
            RAM (rw)   : ORIGIN = 0x20000000, LENGTH = 128K
        }
        '''
        script_path = self.create_test_linker_script(content)

        # Test with ARM ELF if available
        arm_elf = ('/home/michael/projs/membrowse/micropython/ports/'
                   'bare-arm/build/firmware.elf')

        if os.path.exists(arm_elf):
            # Test with ELF file
            parser = LinkerScriptParser([str(script_path)], arm_elf)
            self.assertIsNotNone(parser.elf_info)
            self.assertEqual(parser.elf_info.architecture, Architecture.ARM)
            self.assertEqual(parser.elf_info.platform, Platform.STM32)

            regions = parser.parse_memory_regions()
            self.assertEqual(len(regions), 2)
            self.assertIn('FLASH', regions)
            self.assertIn('RAM', regions)
        else:
            self.skipTest("ARM ELF file not available")

    def test_linker_parser_without_elf(self):
        """Test LinkerScriptParser without ELF file (backward compatibility)"""
        # Create a simple test linker script
        content = '''
        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512K
            RAM (rw)   : ORIGIN = 0x20000000, LENGTH = 128K
        }
        '''
        script_path = self.create_test_linker_script(content)

        # Test without ELF file
        parser = LinkerScriptParser([str(script_path)])
        self.assertIsNone(parser.elf_info)
        self.assertEqual(parser.parsing_strategy, {})

        regions = parser.parse_memory_regions()
        self.assertEqual(len(regions), 2)
        self.assertIn('FLASH', regions)
        self.assertIn('RAM', regions)

    def test_parse_linker_scripts_with_elf(self):
        """Test parse_linker_scripts convenience function with ELF file"""
        # Create a linker script with defined values (no default variables)
        content = '''
        _flash_size = 0x100000;
        _ram_size = 0x20000;

        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = _flash_size
            RAM (rw)   : ORIGIN = 0x20000000, LENGTH = _ram_size
        }
        '''
        script_path = self.create_test_linker_script(content)

        # Test with ARM ELF if available
        arm_elf = ('/home/michael/projs/membrowse/micropython/ports/'
                   'bare-arm/build/firmware.elf')

        if os.path.exists(arm_elf):
            # Should parse variables from linker script
            regions = parse_linker_scripts([str(script_path)], arm_elf)
            self.assertEqual(len(regions), 2)
            self.assertIn('FLASH', regions)
            self.assertIn('RAM', regions)

            # Check that variables from script were used
            self.assertEqual(regions['FLASH']['limit_size'], 0x100000)
            self.assertEqual(regions['RAM']['limit_size'], 0x20000)
        else:
            self.skipTest("ARM ELF file not available")

    def test_invalid_elf_file(self):
        """Test handling of invalid ELF file"""
        # Create a non-ELF file
        non_elf_file = self.temp_dir / "not_an_elf.bin"
        with open(non_elf_file, 'wb') as f:
            f.write(b"This is not an ELF file")
        self.test_files.append(non_elf_file)

        # Should return None for invalid ELF
        elf_info = get_architecture_info(str(non_elf_file))
        self.assertIsNone(elf_info)

        # Parser should handle gracefully
        content = '''
        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512K
        }
        '''
        script_path = self.create_test_linker_script(content)

        parser = LinkerScriptParser([str(script_path)], str(non_elf_file))
        self.assertIsNone(parser.elf_info)

        # Should still parse successfully
        regions = parser.parse_memory_regions()
        self.assertEqual(len(regions), 1)
        self.assertIn('FLASH', regions)

    def test_nonexistent_elf_file(self):
        """Test handling of nonexistent ELF file"""
        nonexistent_elf = "/path/that/does/not/exist.elf"

        # Should return None for nonexistent file
        elf_info = get_architecture_info(nonexistent_elf)
        self.assertIsNone(elf_info)

        # Parser should handle gracefully
        content = '''
        MEMORY
        {
            FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512K
        }
        '''
        script_path = self.create_test_linker_script(content)

        parser = LinkerScriptParser([str(script_path)], nonexistent_elf)
        self.assertIsNone(parser.elf_info)

        # Should still parse successfully
        regions = parser.parse_memory_regions()
        self.assertEqual(len(regions), 1)
        self.assertIn('FLASH', regions)


if __name__ == '__main__':
    print("ELF Architecture Detection Test Suite")
    print("=" * 50)

    # Run the tests
    unittest.main(verbosity=2)
