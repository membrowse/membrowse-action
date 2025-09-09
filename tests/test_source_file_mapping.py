#!/usr/bin/env python3
"""
Unit tests for source file mapping functionality in memory_report.py
Tests the new address-priority mapping structure for handling duplicate symbol names
"""

import unittest
from unittest.mock import MagicMock, patch, mock_open
import sys
from pathlib import Path

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'shared'))

from memory_report import ELFAnalyzer


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
                
        # Check mapping structure
        self.assertIsInstance(analyzer._source_file_mapping, dict)
        self.assertIn('by_address', analyzer._source_file_mapping)
        self.assertIn('by_compound_key', analyzer._source_file_mapping)
        self.assertIsInstance(analyzer._source_file_mapping['by_address'], dict)
        self.assertIsInstance(analyzer._source_file_mapping['by_compound_key'], dict)

    @patch('memory_report.Path.exists')
    @patch('memory_report.os.access')
    def test_source_mapping_storage_with_valid_address(self, mock_access, mock_exists):
        """Test storage of source mapping with valid address - should use CU source file for definitions"""
        mock_exists.return_value = True
        mock_access.return_value = True
        
        with patch('builtins.open', mock_open()):
            with patch('memory_report.ELFFile'):
                analyzer = ELFAnalyzer(self.test_elf_path)
        
        # Mock file entries (for declarations)
        file_entries = {1: 'main.h', 2: 'utils.h'}
        
        # CU source file (for definitions)
        cu_source_file = 'main.c'
        
        # Create mock DIE with valid address (indicates definition)
        mock_die = MagicMock()
        mock_die.attributes = {
            'DW_AT_name': MagicMock(value=b'test_function'),
            'DW_AT_decl_file': MagicMock(value=1),  # Declared in main.h
            'DW_AT_low_pc': MagicMock(value=0x1000)  # Has address = definition
        }
        
        # Process the DIE
        analyzer._process_die_for_source_mapping(mock_die, file_entries, cu_source_file)
        
        # Should use CU source file (definition) not declaration file
        self.assertEqual(analyzer._source_file_mapping['by_address'][0x1000], 'main.c')
        self.assertEqual(analyzer._source_file_mapping['by_compound_key'][('test_function', 0x1000)], 'main.c')

    @patch('memory_report.Path.exists')
    @patch('memory_report.os.access')
    def test_source_mapping_storage_without_address(self, mock_access, mock_exists):
        """Test storage of source mapping without address info - should use declaration file"""
        mock_exists.return_value = True
        mock_access.return_value = True
        
        with patch('builtins.open', mock_open()):
            with patch('memory_report.ELFFile'):
                analyzer = ELFAnalyzer(self.test_elf_path)
        
        file_entries = {1: 'main.h'}
        cu_source_file = 'main.c'
        
        # Create mock DIE without address (likely just declaration)
        mock_die = MagicMock()
        mock_die.attributes = {
            'DW_AT_name': MagicMock(value=b'test_function'),
            'DW_AT_decl_file': MagicMock(value=1)
        }
        
        analyzer._process_die_for_source_mapping(mock_die, file_entries, cu_source_file)
        
        # Without address, should use declaration file not CU source
        self.assertNotIn(0, analyzer._source_file_mapping['by_address'])
        self.assertEqual(analyzer._source_file_mapping['by_compound_key'][('test_function', 0)], 'main.h')

    @patch('memory_report.Path.exists')
    @patch('memory_report.os.access')
    def test_source_mapping_storage_with_invalid_address(self, mock_access, mock_exists):
        """Test storage of source mapping with invalid address (0)"""
        mock_exists.return_value = True
        mock_access.return_value = True
        
        with patch('builtins.open', mock_open()):
            with patch('memory_report.ELFFile'):
                analyzer = ELFAnalyzer(self.test_elf_path)
        
        file_entries = {1: 'main.h'}
        cu_source_file = 'main.c'
        
        # Create mock DIE with address 0 (invalid - treated as declaration)
        mock_die = MagicMock()
        mock_die.attributes = {
            'DW_AT_name': MagicMock(value=b'test_function'),
            'DW_AT_decl_file': MagicMock(value=1),
            'DW_AT_low_pc': MagicMock(value=0)
        }
        
        analyzer._process_die_for_source_mapping(mock_die, file_entries, cu_source_file)
        
        # Check address mapping was not stored (address 0 is invalid)
        self.assertNotIn(0, analyzer._source_file_mapping['by_address'])
        # Should use declaration file since address 0 doesn't indicate a definition
        self.assertEqual(analyzer._source_file_mapping['by_compound_key'][('test_function', 0)], 'main.h')

    @patch('memory_report.Path.exists')
    @patch('memory_report.os.access')
    def test_duplicate_symbol_names_different_addresses(self, mock_access, mock_exists):
        """Test handling of duplicate symbol names with different addresses"""
        mock_exists.return_value = True
        mock_access.return_value = True
        
        with patch('builtins.open', mock_open()):
            with patch('memory_report.ELFFile'):
                analyzer = ELFAnalyzer(self.test_elf_path)
        
        file_entries1 = {1: 'file1.h'}
        file_entries2 = {1: 'file2.h'}
        
        # First symbol: static_function defined in file1.c at address 0x1000
        mock_die1 = MagicMock()
        mock_die1.attributes = {
            'DW_AT_name': MagicMock(value=b'static_function'),
            'DW_AT_decl_file': MagicMock(value=1),  # declared in file1.h
            'DW_AT_low_pc': MagicMock(value=0x1000)
        }
        
        # Second symbol: static_function defined in file2.c at address 0x2000
        mock_die2 = MagicMock()
        mock_die2.attributes = {
            'DW_AT_name': MagicMock(value=b'static_function'),
            'DW_AT_decl_file': MagicMock(value=1),  # declared in file2.h
            'DW_AT_low_pc': MagicMock(value=0x2000)
        }
        
        # Process both DIEs with their respective CU source files
        analyzer._process_die_for_source_mapping(mock_die1, file_entries1, 'file1.c')
        analyzer._process_die_for_source_mapping(mock_die2, file_entries2, 'file2.c')
        
        # Check both address mappings exist with definition files
        self.assertEqual(analyzer._source_file_mapping['by_address'][0x1000], 'file1.c')
        self.assertEqual(analyzer._source_file_mapping['by_address'][0x2000], 'file2.c')
        
        # Check both compound key mappings exist with definition files
        self.assertEqual(analyzer._source_file_mapping['by_compound_key'][('static_function', 0x1000)], 'file1.c')
        self.assertEqual(analyzer._source_file_mapping['by_compound_key'][('static_function', 0x2000)], 'file2.c')

    @patch('memory_report.Path.exists')
    @patch('memory_report.os.access')
    def test_source_file_extraction_address_priority(self, mock_access, mock_exists):
        """Test that address-based lookup has priority over compound key lookup"""
        mock_exists.return_value = True
        mock_access.return_value = True
        
        with patch('builtins.open', mock_open()):
            with patch('memory_report.ELFFile'):
                analyzer = ELFAnalyzer(self.test_elf_path)
        
        # Manually populate mappings to test priority
        analyzer._source_file_mapping['by_address'][0x1000] = 'correct_file.c'
        analyzer._source_file_mapping['by_compound_key'][('test_func', 0x1000)] = 'wrong_file.c'
        
        # Should return from address mapping (priority 1)
        result = analyzer._extract_source_file('test_func', 0x1000)
        self.assertEqual(result, 'correct_file.c')

    @patch('memory_report.Path.exists')
    @patch('memory_report.os.access')
    def test_source_file_extraction_compound_key_fallback(self, mock_access, mock_exists):
        """Test compound key fallback when address mapping doesn't exist"""
        mock_exists.return_value = True
        mock_access.return_value = True
        
        with patch('builtins.open', mock_open()):
            with patch('memory_report.ELFFile'):
                analyzer = ELFAnalyzer(self.test_elf_path)
        
        # Only compound key mapping exists
        analyzer._source_file_mapping['by_compound_key'][('test_func', 0x1000)] = 'fallback_file.c'
        
        # Should return from compound key mapping (priority 2)
        result = analyzer._extract_source_file('test_func', 0x1000)
        self.assertEqual(result, 'fallback_file.c')

    @patch('memory_report.Path.exists')
    @patch('memory_report.os.access')
    def test_source_file_extraction_placeholder_fallback(self, mock_access, mock_exists):
        """Test placeholder fallback for symbols without address info"""
        mock_exists.return_value = True
        mock_access.return_value = True
        
        with patch('builtins.open', mock_open()):
            with patch('memory_report.ELFFile'):
                analyzer = ELFAnalyzer(self.test_elf_path)
        
        # Only placeholder compound key exists
        analyzer._source_file_mapping['by_compound_key'][('test_func', 0)] = 'placeholder_file.c'
        
        # Should return from placeholder compound key mapping (priority 3)
        result = analyzer._extract_source_file('test_func', None)
        self.assertEqual(result, 'placeholder_file.c')

    @patch('memory_report.Path.exists')
    @patch('memory_report.os.access')
    def test_source_file_extraction_invalid_address_handling(self, mock_access, mock_exists):
        """Test that invalid addresses (0, None) are handled correctly"""
        mock_exists.return_value = True
        mock_access.return_value = True
        
        with patch('builtins.open', mock_open()):
            with patch('memory_report.ELFFile'):
                analyzer = ELFAnalyzer(self.test_elf_path)
        
        # Set up mappings
        analyzer._source_file_mapping['by_address'][0] = 'should_not_match.c'
        analyzer._source_file_mapping['by_compound_key'][('test_func', 0)] = 'correct_file.c'
        
        # Test with address 0 - should skip address lookup and use compound key
        result = analyzer._extract_source_file('test_func', 0)
        self.assertEqual(result, 'correct_file.c')
        
        # Test with None address - should use placeholder compound key
        result = analyzer._extract_source_file('test_func', None)
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
        result = analyzer._extract_source_file('unknown_func', 0x1000)
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
        
        # Set up mapping with full path
        analyzer._source_file_mapping['by_address'][0x1000] = '/full/path/to/source.c'
        
        result = analyzer._extract_source_file('test_func', 0x1000)
        self.assertEqual(result, 'source.c')


if __name__ == '__main__':
    unittest.main()