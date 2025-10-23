#!/usr/bin/env python3
"""
Unit tests for memory mapper logic, especially overlapping region handling.
"""

import unittest
from membrowse.analysis.mapper import MemoryMapper
from membrowse.core.models import MemoryRegion, MemorySection


class TestMemoryMapper(unittest.TestCase):
    """Test MemoryMapper class with focus on overlapping regions"""

    def test_non_overlapping_regions(self):
        """Test section mapping with non-overlapping regions"""
        # Create non-overlapping regions
        regions = {
            'FLASH': MemoryRegion(
                address=0x08000000,
                limit_size=0x100000,
                type='FLASH'),
            'RAM': MemoryRegion(
                address=0x20000000,
                limit_size=0x20000,
                type='RAM'),
        }

        mapper = MemoryMapper(regions)

        # Test section in FLASH
        flash_section = MemorySection(
            name='.text',
            address=0x08020000,
            size=0x1000,
            type='code'
        )
        region = mapper.find_region_by_address(flash_section)
        self.assertIsNotNone(region)
        self.assertEqual(region.address, 0x08000000)
        self.assertEqual(region.type, 'FLASH')

        # Test section in RAM
        ram_section = MemorySection(
            name='.data',
            address=0x20000000,
            size=0x100,
            type='data'
        )
        region = mapper.find_region_by_address(ram_section)
        self.assertIsNotNone(region)
        self.assertEqual(region.address, 0x20000000)
        self.assertEqual(region.type, 'RAM')

    def test_overlapping_regions_prefers_smallest(self):
        """Test that mapper prefers smaller (more specific) region when overlapping"""
        # Create overlapping regions (STM32-style hierarchy)
        regions = {
            'FLASH': MemoryRegion(
                address=0x08000000,
                limit_size=0x100000,  # 1MB parent
                type='FLASH'
            ),
            'FLASH_START': MemoryRegion(
                address=0x08000000,
                limit_size=0x4000,    # 16KB child
                type='FLASH'
            ),
        }

        mapper = MemoryMapper(regions)

        # Section at 0x08000000 should map to FLASH_START (smaller/more
        # specific)
        section = MemorySection(
            name='.isr_vector',
            address=0x08000000,
            size=0x188,
            type='code'
        )
        region = mapper.find_region_by_address(section)
        self.assertIsNotNone(region)
        self.assertEqual(region.address, 0x08000000)
        # Should be FLASH_START, not FLASH
        self.assertEqual(region.limit_size, 0x4000)

    def test_three_level_hierarchy(self):
        """Test three-level region hierarchy (grandparent/parent/child)"""
        regions = {
            'FLASH': MemoryRegion(
                address=0x08000000,
                limit_size=0x100000,  # 1MB grandparent
                type='FLASH'
            ),
            'FLASH_START': MemoryRegion(
                address=0x08000000,
                limit_size=0x4000,    # 16KB parent
                type='FLASH'
            ),
            'FLASH_SECTOR0': MemoryRegion(
                address=0x08000000,
                limit_size=0x1000,    # 4KB child (most specific)
                type='FLASH'
            ),
        }

        mapper = MemoryMapper(regions)

        # Section should map to smallest (FLASH_SECTOR0)
        section = MemorySection(
            name='.isr_vector',
            address=0x08000000,
            size=0x100,
            type='code'
        )
        region = mapper.find_region_by_address(section)
        self.assertIsNotNone(region)
        self.assertEqual(region.limit_size, 0x1000)  # Should be FLASH_SECTOR0

    def test_section_in_parent_but_not_child(self):
        """Test section that's in parent region but outside child regions"""
        regions = {
            'FLASH': MemoryRegion(
                address=0x08000000,
                limit_size=0x100000,
                type='FLASH'
            ),
            'FLASH_START': MemoryRegion(
                address=0x08000000,
                limit_size=0x4000,
                type='FLASH'
            ),
            'FLASH_TEXT': MemoryRegion(
                address=0x08020000,
                limit_size=0xE0000,
                type='FLASH'
            ),
        }

        mapper = MemoryMapper(regions)

        # Section at 0x08010000 is only in FLASH (not in any child)
        section = MemorySection(
            name='.data',
            address=0x08010000,
            size=0x100,
            type='data'
        )
        region = mapper.find_region_by_address(section)
        self.assertIsNotNone(region)
        self.assertEqual(region.address, 0x08000000)
        self.assertEqual(
            region.limit_size,
            0x100000)  # Should be FLASH (parent)

    def test_section_at_boundary(self):
        """Test sections at region boundaries"""
        regions = {
            'FLASH_START': MemoryRegion(
                address=0x08000000,
                limit_size=0x4000,
                type='FLASH'
            ),
            'FLASH_TEXT': MemoryRegion(
                address=0x08004000,
                limit_size=0x1C000,
                type='FLASH'
            ),
        }

        mapper = MemoryMapper(regions)

        # Section at start of FLASH_TEXT (end of FLASH_START range)
        section = MemorySection(
            name='.text',
            address=0x08004000,
            size=0x100,
            type='code'
        )
        region = mapper.find_region_by_address(section)
        self.assertIsNotNone(region)
        self.assertEqual(region.address, 0x08004000)  # Should be FLASH_TEXT

    def test_zero_address_section(self):
        """Test that sections with zero address are skipped"""
        regions = {
            'FLASH': MemoryRegion(
                address=0x08000000,
                limit_size=0x100000,
                type='FLASH'),
        }

        mapper = MemoryMapper(regions)

        # Debug section with zero address
        section = MemorySection(
            name='.debug_info',
            address=0x00000000,
            size=0x1000,
            type='debug'
        )
        region = mapper.find_region_by_address(section)
        self.assertIsNone(region)  # Should return None for zero address

    def test_section_not_in_any_region(self):
        """Test section that doesn't fit in any region"""
        regions = {
            'FLASH': MemoryRegion(
                address=0x08000000,
                limit_size=0x100000,
                type='FLASH'),
            'RAM': MemoryRegion(
                address=0x20000000,
                limit_size=0x20000,
                type='RAM'),
        }

        mapper = MemoryMapper(regions)

        # Section at address outside all regions
        section = MemorySection(
            name='.external',
            address=0x60000000,
            size=0x100,
            type='data'
        )
        region = mapper.find_region_by_address(section)
        self.assertIsNone(region)  # Should return None

    def test_esp32_non_contiguous_flash(self):
        """Test ESP32-style non-contiguous flash regions"""
        regions = {
            'iram0_2_seg': MemoryRegion(
                address=0x400D0020,
                limit_size=0x32FFE0,
                type='RAM'  # Actually flash-mapped, but marked as RAM by parser
            ),
            'drom0_0_seg': MemoryRegion(
                address=0x3F400020,
                limit_size=0x3FFFE0,
                type='FLASH'
            ),
        }

        mapper = MemoryMapper(regions)

        # Section in instruction flash
        flash_text_section = MemorySection(
            name='.flash.text',
            address=0x400D0020,
            size=0x10000,
            type='code'
        )
        region = mapper.find_region_by_address(flash_text_section)
        self.assertIsNotNone(region)
        self.assertEqual(region.address, 0x400D0020)  # Should be iram0_2_seg

        # Section in data flash
        flash_rodata_section = MemorySection(
            name='.flash.rodata',
            address=0x3F400020,
            size=0x1000,
            type='rodata'
        )
        region = mapper.find_region_by_address(flash_rodata_section)
        self.assertIsNotNone(region)
        self.assertEqual(region.address, 0x3F400020)  # Should be drom0_0_seg

    def test_map_sections_to_regions_integration(self):
        """Integration test for map_sections_to_regions with overlapping regions"""
        regions = {
            'FLASH': MemoryRegion(
                address=0x08000000,
                limit_size=0x100000,
                type='FLASH'
            ),
            'FLASH_START': MemoryRegion(
                address=0x08000000,
                limit_size=0x4000,
                type='FLASH'
            ),
            'FLASH_TEXT': MemoryRegion(
                address=0x08020000,
                limit_size=0xE0000,
                type='FLASH'
            ),
            'RAM': MemoryRegion(
                address=0x20000000,
                limit_size=0x20000,
                type='RAM'
            ),
        }

        sections = [
            MemorySection(
                name='.isr_vector',
                address=0x08000000,
                size=0x188,
                type='code'),
            MemorySection(
                name='.text',
                address=0x08020000,
                size=0x10000,
                type='code'),
            MemorySection(
                name='.data',
                address=0x20000000,
                size=0x100,
                type='data'),
        ]

        # Map sections to regions
        MemoryMapper.map_sections_to_regions(sections, regions)

        # Verify sections are in correct regions
        self.assertEqual(len(regions['FLASH_START'].sections), 1)
        self.assertEqual(
            regions['FLASH_START'].sections[0]['name'],
            '.isr_vector')

        self.assertEqual(len(regions['FLASH_TEXT'].sections), 1)
        self.assertEqual(regions['FLASH_TEXT'].sections[0]['name'], '.text')

        self.assertEqual(len(regions['RAM'].sections), 1)
        self.assertEqual(regions['RAM'].sections[0]['name'], '.data')

        # Parent FLASH should have no sections (they all mapped to children)
        self.assertEqual(len(regions['FLASH'].sections), 0)


if __name__ == '__main__':
    unittest.main()
