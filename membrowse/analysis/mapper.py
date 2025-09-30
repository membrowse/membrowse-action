#!/usr/bin/env python3
"""
Memory mapping utilities for ELF sections to memory regions.

This module handles the mapping of ELF sections to memory regions based on
addresses and types, with optimized binary search algorithms for performance.
"""

from typing import Dict, List, Optional
from ..core.models import MemoryRegion, MemorySection


class MemoryMapper:
    """Maps ELF sections to memory regions with optimized address lookups"""

    def __init__(self, memory_regions: Dict[str, MemoryRegion]):
        """Initialize with sorted region list for efficient address lookups."""
        self.regions = memory_regions
        # Create sorted list of regions by start address for binary search
        self._sorted_regions = []
        for region in memory_regions.values():
            self._sorted_regions.append(
                (region.address, region.address + region.limit_size, region))
        self._sorted_regions.sort(key=lambda x: x[0])  # Sort by start address

    @staticmethod
    def map_sections_to_regions(sections: List[MemorySection],
                                memory_regions: Dict[str, MemoryRegion]) -> None:
        """Map sections to appropriate memory regions based on addresses.

        Args:
            sections: List of ELF sections to map
            memory_regions: Dictionary of memory regions to map to
        """
        mapper = MemoryMapper(memory_regions)

        for section in sections:
            region = mapper.find_region_by_address(section)
            if region:
                region.sections.append(section.__dict__)
            else:
                # If no address-based match, fall back to type-based mapping
                region = MemoryMapper._find_region_by_type(
                    section, memory_regions)
                if region:
                    region.sections.append(section.__dict__)

    def find_region_by_address(
            self,
            section: MemorySection) -> Optional[MemoryRegion]:
        """Find the most specific memory region containing the section address.

        When multiple regions overlap (e.g., FLASH parent and FLASH_START child),
        this returns the smallest region that contains the address, ensuring
        sections map to the most specific region available.

        Args:
            section: ELF section to find region for

        Returns:
            MemoryRegion that contains the section address (smallest if multiple),
            or None if not found
        """
        # Skip sections with zero address (debug/metadata sections)
        if section.address == 0:
            return None

        # Find all regions that contain this address
        matching_regions = []
        for start_addr, end_addr, region in self._sorted_regions:
            if start_addr <= section.address < end_addr:
                matching_regions.append(region)

        if not matching_regions:
            return None

        # Return the most specific (smallest) region
        return min(matching_regions, key=lambda r: r.limit_size)

    @staticmethod
    def _find_region_by_type(section: MemorySection,
                             memory_regions: Dict[str,
                                                  MemoryRegion]) -> Optional[MemoryRegion]:
        """Find memory region based on section type compatibility.

        Args:
            section: ELF section to find region for
            memory_regions: Dictionary of available memory regions

        Returns:
            Compatible MemoryRegion or first available region as fallback
        """
        section_type = section.type

        # Try to find type-specific regions first
        for region in memory_regions.values():
            if MemoryMapper._is_compatible_region(section_type, region.type):
                return region

        # Fall back to first available region
        return next(iter(memory_regions.values())) if memory_regions else None

    @staticmethod
    def _is_compatible_region(section_type: str, region_type: str) -> bool:
        """Check if section type is compatible with region type.

        Args:
            section_type: Type of ELF section ('text', 'data', 'bss', etc.)
            region_type: Type of memory region ('FLASH', 'RAM', 'ROM', etc.)

        Returns:
            True if section type is compatible with region type
        """
        compatibility_map = {
            'text': ['FLASH', 'ROM'],
            'rodata': ['FLASH', 'ROM'],
            'data': ['RAM'],
            'bss': ['RAM']
        }
        return region_type in compatibility_map.get(section_type, [])

    @staticmethod
    def calculate_utilization(memory_regions: Dict[str, MemoryRegion]) -> None:
        """Calculate memory utilization for each region.

        Updates each region's used_size, free_size, and utilization_percent fields.

        Args:
            memory_regions: Dictionary of memory regions to calculate utilization for
        """
        for region in memory_regions.values():
            region.used_size = sum(section['size']
                                   for section in region.sections)
            region.free_size = region.limit_size - region.used_size
            region.utilization_percent = (
                (region.used_size / region.limit_size * 100)
                if region.limit_size > 0 else 0.0
            )
