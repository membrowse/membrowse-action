#!/usr/bin/env python3
"""
Memory mapping utilities for ELF sections to memory regions.

This module handles the mapping of ELF sections to memory regions based on
addresses and types, with optimized binary search algorithms for performance.
"""

import logging
from typing import Dict, List, Optional
from ..core.models import MemoryRegion, MemorySection

logger = logging.getLogger(__name__)


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
                                memory_regions: Dict[str, MemoryRegion]
                                ) -> List[MemorySection]:
        """Map sections to appropriate memory regions based on addresses.

        Sections with distinct LMA (e.g. .data placed via linker AT() — init
        image in flash, runtime copy in RAM) are attributed to both the VMA
        region and the LMA region, each with its respective address. The
        section dict schema is unchanged; duplicates disambiguate by address.

        Args:
            sections: List of ELF sections to map
            memory_regions: Dictionary of memory regions to map to

        Returns:
            List of sections that could not be mapped to any region.
        """
        mapper = MemoryMapper(memory_regions)
        unmapped: List[MemorySection] = []

        for section in sections:
            region = mapper.find_region_by_address(section)
            if region:
                region.sections.append(section.to_region_entry())
            else:
                # If no address-based match, fall back to type-based mapping
                region = MemoryMapper._find_region_by_type(
                    section, memory_regions)
                if region:
                    region.sections.append(section.to_region_entry())
                else:
                    logger.debug(
                        "Section '%s' at 0x%x (size 0x%x) could not be "
                        "mapped to any memory region",
                        section.name, section.address, section.size)
                    unmapped.append(section)

            # Dual attribution: if the section has a distinct LMA, also
            # credit its bytes to the region that holds the load image.
            # Clear section.lma on success so a re-run (e.g. after region
            # inference in the caller) doesn't double-credit.
            if section.lma is not None:
                # pylint: disable-next=protected-access
                lma_region = mapper._find_region_containing(section.lma)
                if lma_region is not None:
                    lma_region.sections.append(
                        section.to_region_entry(address=section.lma))
                    section.lma = None
                else:
                    logger.debug(
                        "Section '%s' LMA 0x%x (size 0x%x) falls outside "
                        "declared regions; flash init image not counted",
                        section.name, section.lma, section.size)

        return unmapped

    def _find_region_containing(self, address: int) -> Optional[MemoryRegion]:
        """Return the smallest declared region containing the given address."""
        matches = [region for start, end, region in self._sorted_regions
                   if start <= address < end]
        if not matches:
            return None
        return min(matches, key=lambda r: r.limit_size)

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
        return self._find_region_containing(section.address)

    @staticmethod
    def _find_region_by_type(section: MemorySection,
                             memory_regions: Dict[str,
                                                  MemoryRegion]) -> Optional[MemoryRegion]:
        """Find memory region based on section type compatibility.

        Args:
            section: ELF section to find region for
            memory_regions: Dictionary of available memory regions

        Returns:
            Compatible MemoryRegion, or None if no compatible region found.
        """
        section_type = section.type

        # Try to find type-specific regions first
        for region in memory_regions.values():
            if MemoryMapper._is_compatible_region(section_type, region.type):
                return region

        # No compatible region found
        return None

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
    def _intervals_cover_range(
            intervals: List[tuple], start: int, end: int) -> bool:
        """Check whether a sorted list of (start, end) intervals fully covers
        [start, end).

        Args:
            intervals: Sorted list of (interval_start, interval_end) tuples.
            start: Start of the range to check.
            end: End of the range to check.

        Returns:
            True if the intervals collectively cover the entire range.
        """
        cursor = start
        for iv_start, iv_end in intervals:
            if iv_start > cursor:
                return False
            cursor = max(cursor, iv_end)
            if cursor >= end:
                return True
        return cursor >= end

    @staticmethod
    def infer_regions_from_segments(
            program_headers: List[Dict],
            existing_regions: Dict[str, MemoryRegion]
    ) -> Dict[str, MemoryRegion]:
        """Infer memory regions from ELF LOAD segments for unmapped sections.

        For each PT_LOAD segment not already contained in an existing region,
        emit a dedicated inferred region. Executable segments (X flag) are
        treated as FLASH/code; writable, non-executable segments as RAM;
        read-only data segments as FLASH. This avoids bounding-boxing across
        spatially distant segments (e.g. flash at 0x0... and an LPRAM region
        at 0x30000000), which would otherwise produce an absurd region
        spanning the entire gap.

        Args:
            program_headers: ELF program headers (list of dicts with type,
                virt_addr, mem_size, flags keys).
            existing_regions: Already-known memory regions from linker scripts.

        Returns:
            Dictionary of newly inferred MemoryRegion objects (may be empty).
            When more than one region of the same type is inferred, names are
            disambiguated with the start address (e.g. "Flash (inferred
            @0x30001fc8)").
        """
        load_segments = [
            ph for ph in program_headers if ph['type'] == 'PT_LOAD'
        ]
        if not load_segments:
            return {}

        existing_intervals = [
            (r.address, r.address + r.limit_size)
            for r in existing_regions.values()
        ]

        flash_orphans: List[Dict] = []
        ram_orphans: List[Dict] = []
        for seg in load_segments:
            seg_start = seg['virt_addr']
            seg_end = seg_start + seg['mem_size']
            if seg_end == seg_start:
                continue
            if any(iv_start <= seg_start and seg_end <= iv_end
                   for iv_start, iv_end in existing_intervals):
                continue
            flags = seg['flags']
            # Executable code → FLASH (covers RX and RWX); writable data → RAM;
            # otherwise (read-only data) → FLASH.
            if 'X' in flags:
                flash_orphans.append(seg)
            elif 'W' in flags:
                ram_orphans.append(seg)
            else:
                flash_orphans.append(seg)

        inferred: Dict[str, MemoryRegion] = {}

        for base_label, segs, region_type in [
            ('Flash (inferred)', flash_orphans, 'FLASH'),
            ('RAM (inferred)', ram_orphans, 'RAM'),
        ]:
            if not segs:
                continue
            # Disambiguate names when more than one orphan of the same type
            # exists, so each gets a stable, unique key.
            disambiguate = len(segs) > 1
            for seg in segs:
                start = seg['virt_addr']
                size = seg['mem_size']
                end = start + size
                if disambiguate:
                    label = f"{base_label[:-1]} @0x{start:x})"
                else:
                    label = base_label
                logger.warning(
                    "Inferred %s region at 0x%x-0x%x (size 0x%x) from ELF "
                    "LOAD segments. For accurate results, provide linker "
                    "script definitions or use --def to supply missing "
                    "symbol values.",
                    label, start, end, size)
                inferred[label] = MemoryRegion(
                    address=start,
                    limit_size=size,
                    type=region_type,
                )

        return inferred

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
