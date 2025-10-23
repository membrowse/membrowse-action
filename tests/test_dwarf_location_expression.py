#!/usr/bin/env python3
"""
Test cases for DWARF location expression parsing.

This module tests the DW_AT_location expression parsing functionality
to ensure global/static variables with location expressions are correctly
handled.
"""
# pylint: disable=protected-access

import unittest
from membrowse.analysis.dwarf import DWARFProcessor


class TestDWARFLocationExpression(unittest.TestCase):
    """Test cases for DWARF location expression parsing"""

    def test_parse_location_expression_dw_op_addr_32bit(self):
        """Test parsing DW_OP_addr with 32-bit address"""
        processor = DWARFProcessor(None, set(), skip_line_program=True)

        # Test case: DW_OP_addr (0x03) with address 0x20000a30
        # Little-endian: [0x03, 0x30, 0x0a, 0x00, 0x20]
        location_value = [3, 48, 10, 0, 32]

        result = processor._parse_location_expression(location_value)

        self.assertIsNotNone(
            result, "Should successfully parse DW_OP_addr expression")
        self.assertEqual(
            result,
            0x20000a30,
            "Should extract correct 32-bit address")

    def test_parse_location_expression_dw_op_addr_64bit(self):
        """Test parsing DW_OP_addr with 64-bit address"""
        processor = DWARFProcessor(None, set(), skip_line_program=True)

        # Test case: DW_OP_addr (0x03) with address 0x400000000000abcd
        # Little-endian: [0x03, 0xcd, 0xab, 0x00, 0x00, 0x00, 0x00, 0x00, 0x40]
        location_value = [3, 0xcd, 0xab, 0x00, 0x00, 0x00, 0x00, 0x00, 0x40]

        result = processor._parse_location_expression(location_value)

        self.assertIsNotNone(
            result, "Should successfully parse 64-bit DW_OP_addr expression")
        self.assertEqual(
            result,
            0x400000000000abcd,
            "Should extract correct 64-bit address")

    def test_parse_location_expression_invalid_opcode(self):
        """Test parsing location expression with non-DW_OP_addr opcode"""
        processor = DWARFProcessor(None, set(), skip_line_program=True)

        # Test case: DW_OP_fbreg (0x91) - not supported
        location_value = [0x91, 0x10]

        result = processor._parse_location_expression(location_value)

        self.assertIsNone(result, "Should return None for unsupported opcodes")

    def test_parse_location_expression_empty(self):
        """Test parsing empty location expression"""
        processor = DWARFProcessor(None, set(), skip_line_program=True)

        location_value = []

        result = processor._parse_location_expression(location_value)

        self.assertIsNone(result, "Should return None for empty expression")

    def test_parse_location_expression_missing_address_bytes(self):
        """Test parsing DW_OP_addr with missing address bytes"""
        processor = DWARFProcessor(None, set(), skip_line_program=True)

        # Test case: DW_OP_addr (0x03) but no address bytes
        location_value = [3]

        result = processor._parse_location_expression(location_value)

        self.assertIsNone(
            result, "Should return None when address bytes are missing")

    def test_parse_location_expression_real_world_addresses(self):
        """Test parsing various real-world address patterns"""
        processor = DWARFProcessor(None, set(), skip_line_program=True)

        test_cases = [
            # (input, expected_output)
            ([3, 0x00, 0x00, 0x00, 0x08], 0x08000000),  # Flash start (STM32)
            ([3, 0x00, 0x00, 0x00, 0x20], 0x20000000),  # RAM start (STM32)
            ([3, 0x00, 0x80, 0x07, 0x40], 0x40078000),  # Peripheral (STM32)
            ([3, 0x00, 0x10, 0x00, 0x00], 0x00001000),  # Low address
            ([3, 0xff, 0xff, 0xff, 0xff], 0xffffffff),  # Max 32-bit
        ]

        for location_value, expected in test_cases:
            with self.subTest(expected=hex(expected)):
                result = processor._parse_location_expression(location_value)
                self.assertEqual(
                    result,
                    expected,
                    f"Should extract {hex(expected)} from {location_value}"
                )

    def test_parse_location_expression_list_container_compatibility(self):
        """Test that parser handles both list and list-like objects"""
        processor = DWARFProcessor(None, set(), skip_line_program=True)

        # Test with regular list
        list_value = [3, 48, 10, 0, 32]
        result_list = processor._parse_location_expression(list_value)

        # Test with tuple (another iterable)
        tuple_value = tuple(list_value)
        result_tuple = processor._parse_location_expression(tuple_value)

        self.assertEqual(
            result_list,
            0x20000a30,
            "Should parse list correctly")
        self.assertEqual(
            result_tuple,
            0x20000a30,
            "Should parse tuple correctly")
        self.assertEqual(
            result_list,
            result_tuple,
            "Both should produce same result")


if __name__ == '__main__':
    unittest.main()
