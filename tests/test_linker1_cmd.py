#!/usr/bin/env python3

"""
test_linker1_cmd.py - Tests for parsing linker1.cmd (Zephyr RISC-V linker script)

This test validates parsing of a real-world Zephyr RTOS linker script
for RISC-V architecture with bitshift operators and K suffix.
"""

import unittest
from pathlib import Path

from membrowse.linker.parser import parse_linker_scripts


class TestLinker1CmdParsing(unittest.TestCase):
    """Test cases for parsing the Zephyr RISC-V linker1.cmd file"""

    @classmethod
    def setUpClass(cls):
        """Load the linker script once for all tests"""
        cls.fixture_path = Path(__file__).parent / "fixtures" / "linkers" / "linker1.cmd"
        cls.regions = parse_linker_scripts([str(cls.fixture_path)])

    def test_parses_three_memory_regions(self):
        """Test that ROM, RAM, and IDT_LIST regions are parsed"""
        self.assertEqual(len(self.regions), 3)
        self.assertIn('ROM', self.regions)
        self.assertIn('RAM', self.regions)
        self.assertIn('IDT_LIST', self.regions)

    def test_rom_region_address(self):
        """Test ROM region origin: ((536936448) + 0x0) = 536936448 (0x20010000)"""
        rom = self.regions['ROM']
        expected_address = 536936448 + 0x0  # 0x20010000
        self.assertEqual(rom['address'], expected_address)

    def test_rom_region_size(self):
        """Test ROM region length: ((3934464) - 0x0) = 3934464 bytes (~3.75MB)"""
        rom = self.regions['ROM']
        expected_size = 3934464 - 0x0
        self.assertEqual(rom['limit_size'], expected_size)

    def test_rom_region_attributes(self):
        """Test ROM region has rx attributes"""
        rom = self.regions['ROM']
        self.assertEqual(rom['attributes'], 'rx')

    def test_ram_region_address(self):
        """Test RAM region origin: 0x80000000"""
        ram = self.regions['RAM']
        expected_address = 0x80000000
        self.assertEqual(ram['address'], expected_address)

    def test_ram_region_size_with_bitshift(self):
        """Test RAM region length: ((16) << 10) = 16 * 1024 = 16KB"""
        ram = self.regions['RAM']
        expected_size = 16 << 10  # 16384 bytes = 16KB
        self.assertEqual(ram['limit_size'], expected_size)

    def test_ram_region_attributes(self):
        """Test RAM region has rwx attributes"""
        ram = self.regions['RAM']
        self.assertEqual(ram['attributes'], 'rwx')

    def test_idt_list_region_address(self):
        """Test IDT_LIST region origin: 0xFFFFF000"""
        idt_list = self.regions['IDT_LIST']
        expected_address = 0xFFFFF000
        self.assertEqual(idt_list['address'], expected_address)

    def test_idt_list_region_size_with_k_suffix(self):
        """Test IDT_LIST region length: 4K = 4096 bytes"""
        idt_list = self.regions['IDT_LIST']
        expected_size = 4 * 1024  # 4096 bytes
        self.assertEqual(idt_list['limit_size'], expected_size)

    def test_idt_list_region_attributes(self):
        """Test IDT_LIST region has wx attributes"""
        idt_list = self.regions['IDT_LIST']
        self.assertEqual(idt_list['attributes'], 'wx')

    def test_end_addresses_computed(self):
        """Test that end addresses are correctly computed"""
        for name, region in self.regions.items():
            expected_end = region['address'] + region['limit_size'] - 1
            self.assertEqual(
                region['end_address'], expected_end,
                f"{name} end_address mismatch"
            )

    def test_bitshift_operator_parsing(self):
        """Test that left shift operator << is correctly parsed"""
        ram = self.regions['RAM']
        # ((16) << 10) should equal 16384
        self.assertEqual(ram['limit_size'], 16384)
        self.assertEqual(ram['limit_size'], 16 * 1024)

    def test_nested_parentheses_with_decimal(self):
        """Test nested parentheses with large decimal numbers"""
        rom = self.regions['ROM']
        # Verify the expression ((536936448) + 0x0) was evaluated correctly
        self.assertEqual(rom['address'], 536936448)
        # 536936448 in hex is 0x20010000
        self.assertEqual(rom['address'], 0x20010000)


class TestLinker1CmdMemorySizes(unittest.TestCase):
    """Test specific memory size calculations for linker1.cmd"""

    @classmethod
    def setUpClass(cls):
        """Load the linker script once for all tests"""
        cls.fixture_path = Path(__file__).parent / "fixtures" / "linkers" / "linker1.cmd"
        cls.regions = parse_linker_scripts([str(cls.fixture_path)])

    def test_rom_is_approximately_3_75mb(self):
        """Test ROM region is approximately 3.75MB"""
        rom = self.regions['ROM']
        # 3934464 bytes = ~3.75MB
        expected_bytes = 3934464
        self.assertEqual(rom['limit_size'], expected_bytes)
        # Verify it's close to 3.75MB
        mb_size = rom['limit_size'] / (1024 * 1024)
        self.assertAlmostEqual(mb_size, 3.75, places=1)

    def test_ram_is_16kb(self):
        """Test RAM region is 16KB"""
        ram = self.regions['RAM']
        expected_kb = 16 * 1024
        self.assertEqual(ram['limit_size'], expected_kb)

    def test_idt_list_is_4kb(self):
        """Test IDT_LIST region is 4KB"""
        idt_list = self.regions['IDT_LIST']
        expected_kb = 4 * 1024
        self.assertEqual(idt_list['limit_size'], expected_kb)

    def test_total_memory_size(self):
        """Test total defined memory size"""
        total = sum(r['limit_size'] for r in self.regions.values())

        # ROM (~3.75MB) + RAM (16KB) + IDT_LIST (4KB)
        expected_total = 3934464 + (16 * 1024) + (4 * 1024)
        self.assertEqual(total, expected_total)

    def test_memory_addresses_are_distinct(self):
        """Test that all memory regions have distinct address ranges"""
        regions_list = list(self.regions.values())

        for i, r1 in enumerate(regions_list):
            for r2 in regions_list[i + 1:]:
                r1_start = r1['address']
                r1_end = r1['end_address']
                r2_start = r2['address']
                r2_end = r2['end_address']

                # Check no overlap: r1 ends before r2 starts OR r2 ends before r1 starts
                no_overlap = (r1_end < r2_start) or (r2_end < r1_start)
                self.assertTrue(
                    no_overlap,
                    f"Regions overlap: {r1_start:#x}-{r1_end:#x} and {r2_start:#x}-{r2_end:#x}"
                )


if __name__ == '__main__':
    unittest.main(verbosity=2)
