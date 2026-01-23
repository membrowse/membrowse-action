#!/usr/bin/env python3
"""
Default memory region generation when linker scripts are not available.

This module provides functionality to create sensible default memory regions
("Code" and "Data") from ELF section information when no linker scripts
are provided.
"""

from typing import Dict, Any, List
from ..core.models import MemorySection, MemoryRegion
from .sections import SECTION_TYPE_CODE, SECTION_TYPE_DATA, SECTION_TYPE_RODATA

# Default region names
DEFAULT_CODE_REGION = "Code"
DEFAULT_DATA_REGION = "Data"


def create_default_memory_regions(
    sections: List[MemorySection]
) -> Dict[str, Dict[str, Any]]:
    """
    Create default "Code" and "Data" memory regions from ELF sections.

    When linker scripts are not available, this function generates default
    memory regions based on ELF section flags:
    - Code: Contains executable sections (code) and read-only sections (rodata)
    - Data: Contains writable sections (data)

    Args:
        sections: List of MemorySection objects from ELF analysis

    Returns:
        Dictionary with region definitions in LinkerScriptParser format:
        {
            "Code": {
                "address": <min_address_of_code_sections>,
                "limit_size": 0,
                "end_address": <min_address_of_code_sections - 1>,
                "attributes": "rx"
            },
            "Data": {
                "address": <min_address_of_data_sections>,
                "limit_size": 0,
                "end_address": <min_address_of_data_sections - 1>,
                "attributes": "rw"
            }
        }

    Note:
        - limit_size is 0 (no limit defined without linker script)
        - address is the minimum address of contained sections
        - Sections with address 0 are ignored when calculating minimum address
        - Only regions with matching sections are created
    """
    code_sections = []
    data_sections = []

    for section in sections:
        # Skip sections at address 0 (typically debug/metadata)
        if section.address == 0:
            continue

        # Classify: executable (code) and read-only (rodata) -> Code region
        # Writable (data) -> Data region
        if section.type in (SECTION_TYPE_CODE, SECTION_TYPE_RODATA):
            code_sections.append(section)
        elif section.type == SECTION_TYPE_DATA:
            data_sections.append(section)

    regions = {}

    # Create Code region if we have code/rodata sections
    if code_sections:
        min_addr = min(s.address for s in code_sections)
        regions[DEFAULT_CODE_REGION] = {
            "address": min_addr,
            "limit_size": 0,
            "end_address": min_addr - 1,  # Will be recalculated, but needed for format
            "attributes": "rx"
        }

    # Create Data region if we have writable sections
    if data_sections:
        min_addr = min(s.address for s in data_sections)
        regions[DEFAULT_DATA_REGION] = {
            "address": min_addr,
            "limit_size": 0,
            "end_address": min_addr - 1,  # Will be recalculated, but needed for format
            "attributes": "rw"
        }

    return regions


def map_sections_to_default_regions(
    sections: List[MemorySection],
    memory_regions: Dict[str, MemoryRegion]
) -> None:
    """
    Map sections to default memory regions based on section type.

    Unlike MemoryMapper.map_sections_to_regions which uses address-based mapping,
    this function maps sections by their type classification:
    - code/rodata sections -> "Code" region
    - data sections -> "Data" region

    This is necessary for default regions where limit_size=0, making
    address-based range matching impossible.

    Args:
        sections: List of MemorySection objects to map
        memory_regions: Dictionary of MemoryRegion objects with "Code" and/or "Data" keys

    Note:
        Modifies memory_regions in-place by appending sections to region.sections
    """
    for section in sections:
        # Skip sections at address 0 (typically debug/metadata)
        if section.address == 0:
            continue

        # Map by section type
        if section.type in (SECTION_TYPE_CODE, SECTION_TYPE_RODATA) \
                and DEFAULT_CODE_REGION in memory_regions:
            memory_regions[DEFAULT_CODE_REGION].sections.append(section.__dict__)
        elif section.type == SECTION_TYPE_DATA and DEFAULT_DATA_REGION in memory_regions:
            memory_regions[DEFAULT_DATA_REGION].sections.append(section.__dict__)
