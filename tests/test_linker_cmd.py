#!/usr/bin/env python3

"""
test_linker_cmd.py - Tests for parsing linker.cmd (Zephyr x86-64 linker script)

This test validates parsing of a real-world Zephyr RTOS linker script
with complex expressions and nested parentheses.
"""

import unittest
from pathlib import Path

from membrowse.linker.parser import parse_linker_scripts


class TestLinkerCmdParsing(unittest.TestCase):
    """Test cases for parsing the Zephyr x86-64 linker.cmd file"""

    @classmethod
    def setUpClass(cls):
        """Load the linker script once for all tests"""
        cls.fixture_path = Path(__file__).parent / "fixtures" / "linkers" / "linker.cmd"
        cls.regions = parse_linker_scripts([str(cls.fixture_path)])

    def test_parses_two_memory_regions(self):
        """Test that both RAM and LOCORE regions are parsed"""
        self.assertEqual(len(self.regions), 2)
        self.assertIn('RAM', self.regions)
        self.assertIn('LOCORE', self.regions)

    def test_ram_region_address(self):
        """Test RAM region origin: ((0) + 0x100000) = 0x100000"""
        ram = self.regions['RAM']
        expected_address = 0 + 0x100000  # 1MB
        self.assertEqual(ram['address'], expected_address)

    def test_ram_region_size(self):
        """Test RAM region length: ((2147483648) - 0x100000) = 2GB - 1MB"""
        ram = self.regions['RAM']
        expected_size = 2147483648 - 0x100000  # 2GB - 1MB = 2146435072 bytes
        self.assertEqual(ram['limit_size'], expected_size)

    def test_ram_region_attributes(self):
        """Test RAM region has wx attributes"""
        ram = self.regions['RAM']
        self.assertEqual(ram['attributes'], 'wx')

    def test_locore_region_address(self):
        """Test LOCORE region origin: 0x1000"""
        locore = self.regions['LOCORE']
        expected_address = 0x1000
        self.assertEqual(locore['address'], expected_address)

    def test_locore_region_size(self):
        """Test LOCORE region length: (0x10000 - 0x1000) = 60KB"""
        locore = self.regions['LOCORE']
        expected_size = 0x10000 - 0x1000  # 61440 bytes (60KB)
        self.assertEqual(locore['limit_size'], expected_size)

    def test_locore_region_attributes(self):
        """Test LOCORE region has wx attributes"""
        locore = self.regions['LOCORE']
        self.assertEqual(locore['attributes'], 'wx')

    def test_end_addresses_computed(self):
        """Test that end addresses are correctly computed"""
        ram = self.regions['RAM']
        locore = self.regions['LOCORE']

        # end_address = address + limit_size - 1
        expected_ram_end = ram['address'] + ram['limit_size'] - 1
        expected_locore_end = locore['address'] + locore['limit_size'] - 1

        self.assertEqual(ram['end_address'], expected_ram_end)
        self.assertEqual(locore['end_address'], expected_locore_end)

    def test_nested_parentheses_in_expressions(self):
        """Test that nested parentheses in expressions are handled correctly"""
        # RAM ORIGIN = ((0) + 0x100000) - nested parens around 0
        # RAM LENGTH = ((2147483648) - 0x100000) - nested parens around decimal
        ram = self.regions['RAM']

        # Verify the expression was evaluated, not just parsed as literal
        self.assertIsInstance(ram['address'], int)
        self.assertIsInstance(ram['limit_size'], int)
        self.assertGreater(ram['limit_size'], 0)

    def test_regions_do_not_overlap(self):
        """Test that RAM and LOCORE regions don't overlap"""
        ram = self.regions['RAM']
        locore = self.regions['LOCORE']

        # LOCORE: 0x1000 to 0xFFFF
        # RAM: 0x100000 to ~0x80000000
        locore_end = locore['address'] + locore['limit_size']
        ram_start = ram['address']

        self.assertLess(locore_end, ram_start,
                        "LOCORE should end before RAM starts")


class TestLinkerCmdMemorySizes(unittest.TestCase):
    """Test specific memory size calculations for linker.cmd"""

    @classmethod
    def setUpClass(cls):
        """Load the linker script once for all tests"""
        cls.fixture_path = Path(__file__).parent / "fixtures" / "linkers" / "linker.cmd"
        cls.regions = parse_linker_scripts([str(cls.fixture_path)])

    def test_ram_is_approximately_2gb(self):
        """Test RAM region is approximately 2GB (minus 1MB)"""
        ram = self.regions['RAM']
        two_gb = 2 * 1024 * 1024 * 1024
        one_mb = 1024 * 1024

        self.assertEqual(ram['limit_size'], two_gb - one_mb)

    def test_locore_is_60kb(self):
        """Test LOCORE region is 60KB"""
        locore = self.regions['LOCORE']
        expected_kb = 60 * 1024  # 0x10000 - 0x1000 = 0xF000 = 61440 = 60KB

        self.assertEqual(locore['limit_size'], expected_kb)

    def test_total_memory_size(self):
        """Test total defined memory size"""
        total = sum(r['limit_size'] for r in self.regions.values())

        # RAM (~2GB - 1MB) + LOCORE (60KB)
        expected_total = (2147483648 - 0x100000) + (0x10000 - 0x1000)
        self.assertEqual(total, expected_total)


if __name__ == '__main__':
    unittest.main(verbosity=2)
