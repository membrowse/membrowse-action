#!/usr/bin/env python3
"""
Unit tests for source file mapping functionality in memory_report.py
Tests the new address-priority mapping structure for handling duplicate symbol names
"""

from memory_report import ELFAnalyzer
import unittest
from unittest.mock import MagicMock, patch, mock_open
import sys
from pathlib import Path

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'shared'))


class TestSourceFileMapping(unittest.TestCase):
    """Test source file mapping with focus on duplicate symbol handling"""

    def setUp(self):
        """Set up test fixtures"""
        self.test_elf_path = "/test/firmware.elf"

    @patch('memory_report.Path.exists')
    @patch('memory_report.os.access')
    def test_mapping_initialization(self, mock_access, mock_exists):
        """Test that mapping structure is initialized correctly"""
        mock_exists.return_value = True
        mock_access.return_value = True

        with patch('builtins.open', mock_open()):
            with patch('memory_report.ELFFile'):
                analyzer = ELFAnalyzer(self.test_elf_path)

        # Check DWARF data structure exists
        self.assertIsInstance(analyzer._dwarf_data, dict)
        self.assertIn('address_to_file', analyzer._dwarf_data)
        self.assertIn('symbol_to_file', analyzer._dwarf_data)
        self.assertIsInstance(
            analyzer._dwarf_data['address_to_file'], dict)
        self.assertIsInstance(
            analyzer._dwarf_data['symbol_to_file'], dict)



    @patch('memory_report.Path.exists')
    @patch('memory_report.os.access')
    def test_source_file_extraction_address_priority(
            self, mock_access, mock_exists):
        """Test that address-based lookup has priority over compound key lookup"""
        mock_exists.return_value = True
        mock_access.return_value = True

        with patch('builtins.open', mock_open()):
            with patch('memory_report.ELFFile'):
                analyzer = ELFAnalyzer(self.test_elf_path)

        # Initialize DWARF data structure
        analyzer._dwarf_data = {
            'address_to_file': {},
            'symbol_to_file': {},
            'symbol_to_cu_file': {},
            'address_to_cu_file': {},
            'cu_file_list': [],
            'system_headers': set(),
        }
        
        # Manually populate mappings to test priority
        analyzer._dwarf_data['address_to_file'][0x1000] = 'correct_file.c'
        analyzer._dwarf_data['symbol_to_file'][('test_func', 0x1000)] = 'wrong_file.c'

        # Should return from address mapping (priority 1)
        result = analyzer._extract_source_file('test_func', 'FUNC', 0x1000)
        self.assertEqual(result, 'correct_file.c')

    @patch('memory_report.Path.exists')
    @patch('memory_report.os.access')
    def test_source_file_extraction_compound_key_fallback(
            self, mock_access, mock_exists):
        """Test compound key fallback when address mapping doesn't exist"""
        mock_exists.return_value = True
        mock_access.return_value = True

        with patch('builtins.open', mock_open()):
            with patch('memory_report.ELFFile'):
                analyzer = ELFAnalyzer(self.test_elf_path)

        # Initialize DWARF data structure
        analyzer._dwarf_data = {
            'address_to_file': {},
            'symbol_to_file': {},
            'symbol_to_cu_file': {},
            'address_to_cu_file': {},
            'cu_file_list': [],
            'system_headers': set(),
        }
        
        # Only compound key mapping exists
        analyzer._dwarf_data['symbol_to_file'][('test_func', 0x1000)] = 'fallback_file.c'

        # Should return from compound key mapping (priority 2)
        result = analyzer._extract_source_file('test_func', 'FUNC', 0x1000)
        self.assertEqual(result, 'fallback_file.c')

    @patch('memory_report.Path.exists')
    @patch('memory_report.os.access')
    def test_source_file_extraction_placeholder_fallback(
            self, mock_access, mock_exists):
        """Test placeholder fallback for symbols without address info"""
        mock_exists.return_value = True
        mock_access.return_value = True

        with patch('builtins.open', mock_open()):
            with patch('memory_report.ELFFile'):
                analyzer = ELFAnalyzer(self.test_elf_path)

        # Initialize DWARF data structure
        analyzer._dwarf_data = {
            'address_to_file': {},
            'symbol_to_file': {},
            'symbol_to_cu_file': {},
            'address_to_cu_file': {},
            'cu_file_list': [],
            'system_headers': set(),
        }
        
        # Only placeholder compound key exists
        analyzer._dwarf_data['symbol_to_file'][('test_func', 0)] = 'placeholder_file.c'

        # Should return from placeholder compound key mapping (priority 3)
        result = analyzer._extract_source_file('test_func', 'FUNC', None)
        self.assertEqual(result, 'placeholder_file.c')

    @patch('memory_report.Path.exists')
    @patch('memory_report.os.access')
    def test_source_file_extraction_invalid_address_handling(
            self, mock_access, mock_exists):
        """Test that invalid addresses (0, None) are handled correctly"""
        mock_exists.return_value = True
        mock_access.return_value = True

        with patch('builtins.open', mock_open()):
            with patch('memory_report.ELFFile'):
                analyzer = ELFAnalyzer(self.test_elf_path)

        # Initialize DWARF data structure
        analyzer._dwarf_data = {
            'address_to_file': {},
            'symbol_to_file': {},
            'symbol_to_cu_file': {},
            'address_to_cu_file': {},
            'cu_file_list': [],
            'system_headers': set(),
        }
        
        # Set up mappings
        analyzer._dwarf_data['address_to_file'][0] = 'should_not_match.c'
        analyzer._dwarf_data['symbol_to_file'][('test_func', 0)] = 'correct_file.c'

        # Test with address 0 - should skip address lookup and use compound key
        result = analyzer._extract_source_file('test_func', 'FUNC', 0)
        self.assertEqual(result, 'correct_file.c')

        # Test with None address - should use placeholder compound key
        result = analyzer._extract_source_file('test_func', 'FUNC', None)
        self.assertEqual(result, 'correct_file.c')

    @patch('memory_report.Path.exists')
    @patch('memory_report.os.access')
    def test_source_file_extraction_no_match(self, mock_access, mock_exists):
        """Test behavior when no source file mapping is found"""
        mock_exists.return_value = True
        mock_access.return_value = True

        with patch('builtins.open', mock_open()):
            with patch('memory_report.ELFFile'):
                analyzer = ELFAnalyzer(self.test_elf_path)

        # No mappings exist
        result = analyzer._extract_source_file('unknown_func', 'FUNC', 0x1000)
        self.assertEqual(result, '')

    @patch('memory_report.Path.exists')
    @patch('memory_report.os.access')
    def test_basename_extraction(self, mock_access, mock_exists):
        """Test that only basename is returned, not full path"""
        mock_exists.return_value = True
        mock_access.return_value = True

        with patch('builtins.open', mock_open()):
            with patch('memory_report.ELFFile'):
                analyzer = ELFAnalyzer(self.test_elf_path)

        # Initialize DWARF data structure
        analyzer._dwarf_data = {
            'address_to_file': {},
            'symbol_to_file': {},
            'symbol_to_cu_file': {},
            'address_to_cu_file': {},
            'cu_file_list': [],
            'system_headers': set(),
        }
        
        # Set up mapping with full path
        analyzer._dwarf_data['address_to_file'][0x1000] = '/full/path/to/source.c'

        result = analyzer._extract_source_file('test_func', 'FUNC', 0x1000)
        self.assertEqual(result, 'source.c')


if __name__ == '__main__':
    unittest.main()
