#!/usr/bin/env python3
"""
Unit tests for default memory region generation without linker scripts.
"""

import unittest
from membrowse.analysis.defaults import (
    create_default_memory_regions,
    map_sections_to_default_regions,
    DEFAULT_CODE_REGION,
    DEFAULT_DATA_REGION,
)
from membrowse.analysis.sections import (
    SECTION_TYPE_CODE,
    SECTION_TYPE_DATA,
    SECTION_TYPE_RODATA,
    SECTION_TYPE_UNKNOWN,
)
from membrowse.analysis.mapper import MemoryMapper
from membrowse.core.models import MemorySection, MemoryRegion


class TestCreateDefaultMemoryRegions(unittest.TestCase):
    """Test create_default_memory_regions function"""

    def test_code_and_data_sections(self):
        """Test with both code and data sections"""
        sections = [
            MemorySection(name=".text", address=0x08000000, size=1024, type=SECTION_TYPE_CODE),
            MemorySection(name=".rodata", address=0x08000400, size=512, type=SECTION_TYPE_RODATA),
            MemorySection(name=".data", address=0x20000000, size=256, type=SECTION_TYPE_DATA),
        ]

        regions = create_default_memory_regions(sections)

        # Check Code region
        self.assertIn(DEFAULT_CODE_REGION, regions)
        self.assertEqual(regions[DEFAULT_CODE_REGION]["address"], 0x08000000)
        self.assertEqual(regions[DEFAULT_CODE_REGION]["limit_size"], 0)
        self.assertEqual(regions[DEFAULT_CODE_REGION]["attributes"], "rx")

        # Check Data region
        self.assertIn(DEFAULT_DATA_REGION, regions)
        self.assertEqual(regions[DEFAULT_DATA_REGION]["address"], 0x20000000)
        self.assertEqual(regions[DEFAULT_DATA_REGION]["limit_size"], 0)
        self.assertEqual(regions[DEFAULT_DATA_REGION]["attributes"], "rw")

    def test_code_only(self):
        """Test with only code sections (no data)"""
        sections = [
            MemorySection(name=".text", address=0x08000000, size=1024, type=SECTION_TYPE_CODE),
            MemorySection(name=".rodata", address=0x08001000, size=512, type=SECTION_TYPE_RODATA),
        ]

        regions = create_default_memory_regions(sections)

        self.assertIn(DEFAULT_CODE_REGION, regions)
        self.assertNotIn(DEFAULT_DATA_REGION, regions)
        self.assertEqual(regions[DEFAULT_CODE_REGION]["address"], 0x08000000)

    def test_data_only(self):
        """Test with only data sections (no code)"""
        sections = [
            MemorySection(name=".data", address=0x20000000, size=256, type=SECTION_TYPE_DATA),
            MemorySection(name=".bss", address=0x20000100, size=128, type=SECTION_TYPE_DATA),
        ]

        regions = create_default_memory_regions(sections)

        self.assertNotIn(DEFAULT_CODE_REGION, regions)
        self.assertIn(DEFAULT_DATA_REGION, regions)
        self.assertEqual(regions[DEFAULT_DATA_REGION]["address"], 0x20000000)

    def test_empty_sections(self):
        """Test with no sections"""
        sections = []

        regions = create_default_memory_regions(sections)

        self.assertEqual(regions, {})

    def test_skips_zero_address_sections(self):
        """Test that sections with address 0 are ignored"""
        sections = [
            MemorySection(name=".debug_info", address=0, size=1000, type=SECTION_TYPE_CODE),
            MemorySection(name=".text", address=0x08000000, size=1024, type=SECTION_TYPE_CODE),
            MemorySection(name=".data", address=0, size=500, type=SECTION_TYPE_DATA),
        ]

        regions = create_default_memory_regions(sections)

        # Only non-zero address sections should be considered
        self.assertIn(DEFAULT_CODE_REGION, regions)
        self.assertEqual(regions[DEFAULT_CODE_REGION]["address"], 0x08000000)
        # No Data region since only data section has address 0
        self.assertNotIn(DEFAULT_DATA_REGION, regions)

    def test_minimum_address_is_used(self):
        """Test that minimum address is used when multiple sections exist"""
        sections = [
            MemorySection(name=".rodata", address=0x08002000, size=512, type=SECTION_TYPE_RODATA),
            MemorySection(name=".text", address=0x08000000, size=1024, type=SECTION_TYPE_CODE),
            MemorySection(name=".text2", address=0x08001000, size=1024, type=SECTION_TYPE_CODE),
        ]

        regions = create_default_memory_regions(sections)

        # Minimum address should be used
        self.assertEqual(regions[DEFAULT_CODE_REGION]["address"], 0x08000000)

    def test_rodata_goes_to_code_region(self):
        """Test that rodata sections are classified as Code"""
        sections = [
            MemorySection(name=".rodata", address=0x08000000, size=512, type=SECTION_TYPE_RODATA),
        ]

        regions = create_default_memory_regions(sections)

        self.assertIn(DEFAULT_CODE_REGION, regions)
        self.assertNotIn(DEFAULT_DATA_REGION, regions)

    def test_unknown_type_ignored(self):
        """Test that unknown section types are ignored"""
        sections = [
            MemorySection(name=".text", address=0x08000000, size=1024, type=SECTION_TYPE_CODE),
            MemorySection(name=".mystery", address=0x30000000, size=100, type=SECTION_TYPE_UNKNOWN),
        ]

        regions = create_default_memory_regions(sections)

        # Only Code should be created, unknown type is ignored
        self.assertIn(DEFAULT_CODE_REGION, regions)
        self.assertEqual(len(regions), 1)


class TestDefaultRegionsIntegration(unittest.TestCase):
    """Integration tests for default regions with mapping"""

    def test_default_regions_work_with_type_mapping(self):
        """Test that default regions can be mapped by section type"""
        sections = [
            MemorySection(name=".text", address=0x08000000, size=1024, type=SECTION_TYPE_CODE),
            MemorySection(name=".rodata", address=0x08000400, size=512, type=SECTION_TYPE_RODATA),
            MemorySection(name=".data", address=0x20000000, size=256, type=SECTION_TYPE_DATA),
        ]

        # Create default regions
        default_regions_data = create_default_memory_regions(sections)

        # Convert to MemoryRegion objects
        memory_regions = {}
        for name, data in default_regions_data.items():
            memory_regions[name] = MemoryRegion(
                address=data['address'],
                limit_size=data['limit_size'],
                type=data.get('attributes', 'UNKNOWN')
            )

        # Map sections to regions by type (for default regions)
        map_sections_to_default_regions(sections, memory_regions)
        MemoryMapper.calculate_utilization(memory_regions)

        # Verify sections are mapped correctly
        self.assertEqual(len(memory_regions[DEFAULT_CODE_REGION].sections), 2)
        self.assertEqual(len(memory_regions[DEFAULT_DATA_REGION].sections), 1)

        # Verify used_size is calculated (limit_size=0 means utilization_percent=0)
        self.assertEqual(memory_regions[DEFAULT_CODE_REGION].used_size, 1024 + 512)
        self.assertEqual(memory_regions[DEFAULT_DATA_REGION].used_size, 256)

        # With limit_size=0, utilization should be 0%
        self.assertEqual(memory_regions[DEFAULT_CODE_REGION].utilization_percent, 0.0)
        self.assertEqual(memory_regions[DEFAULT_DATA_REGION].utilization_percent, 0.0)

    def test_map_sections_skips_zero_address(self):
        """Test that map_sections_to_default_regions skips zero-address sections"""
        sections = [
            MemorySection(name=".text", address=0x08000000, size=1024, type=SECTION_TYPE_CODE),
            MemorySection(name=".debug", address=0, size=5000, type=SECTION_TYPE_CODE),
        ]

        # Create default regions
        default_regions_data = create_default_memory_regions(sections)

        # Convert to MemoryRegion objects
        memory_regions = {}
        for name, data in default_regions_data.items():
            memory_regions[name] = MemoryRegion(
                address=data['address'],
                limit_size=data['limit_size'],
                type=data.get('attributes', 'UNKNOWN')
            )

        # Map sections to regions
        map_sections_to_default_regions(sections, memory_regions)

        # Only the non-zero address section should be mapped
        self.assertEqual(len(memory_regions[DEFAULT_CODE_REGION].sections), 1)
        self.assertEqual(
            memory_regions[DEFAULT_CODE_REGION].sections[0]["name"], ".text"
        )


if __name__ == '__main__':
    unittest.main()
