#!/usr/bin/env python3
"""
Test utilities for linker script parsing tests.

This module contains helper functions used by multiple test files.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


def validate_memory_regions(memory_regions: Dict[str, Dict[str, Any]]) -> bool:
    """Validate that parsed memory regions are reasonable

    Args:
        memory_regions: Dictionary of memory regions

    Returns:
        True if regions appear valid, False otherwise
    """
    if not memory_regions:
        logger.warning("No memory regions found in linker scripts")
        return False

    # Check for overlapping regions with intelligent hierarchical detection
    overlaps_found = False

    for name1, region1 in memory_regions.items():
        for name2, region2 in memory_regions.items():
            if name1 >= name2:  # Avoid checking same pair twice
                continue

            # Check for overlap
            if (
                region1["address"] < region2["end_address"]
                and region2["address"] < region1["end_address"]
            ):

                # Check if this is a valid hierarchical relationship
                if _is_hierarchical_overlap(name1, region1, name2, region2):
                    # This is a valid parent-child relationship, not an error
                    continue
                logger.warning(
                    "Memory regions %s and %s overlap", name1, name2)
                overlaps_found = True

    return not overlaps_found


def _is_hierarchical_overlap(  # pylint: disable=too-many-locals,too-many-return-statements
    name1: str, region1: Dict[str, Any], name2: str, region2: Dict[str, Any]
) -> bool:
    """Check if two overlapping regions have a valid hierarchical relationship

    Args:
        name1, region1: First region
        name2, region2: Second region

    Returns:
        True if this is a valid hierarchical overlap (parent contains child)
    """
    # Determine which region is larger (potential parent)
    if region1["limit_size"] > region2["limit_size"]:
        parent_name, parent_region = name1, region1
        child_name, child_region = name2, region2
    else:
        parent_name, parent_region = name2, region2
        child_name, child_region = name1, region1

    # Check if child is fully contained within parent
    child_fully_contained = (
        child_region["address"] >= parent_region["address"]
        and child_region["end_address"] <= parent_region["end_address"]
    )

    # Allow for slight overhang due to linker script calculation errors
    # Check if child starts within parent and doesn't extend too far beyond
    max_overhang_bytes = (
        64 * 1024
    )  # 64KB allowance for linker script calculation errors
    child_mostly_contained = (
        child_region["address"] >= parent_region["address"]
        and child_region["address"] <= parent_region["end_address"]
        and child_region["end_address"]
        <= parent_region["end_address"] + max_overhang_bytes
    )

    if not child_fully_contained and not child_mostly_contained:
        return False

    # Check for common hierarchical patterns in embedded systems
    parent_lower = parent_name.lower()
    child_lower = child_name.lower()

    # Pattern 1: FLASH parent with FLASH_* children
    if parent_lower == "flash" and child_lower.startswith("flash_"):
        return True

    # Pattern 2: RAM parent with RAM_* children
    if parent_lower == "ram" and child_lower.startswith("ram_"):
        return True

    # Pattern 3: ROM parent with ROM_* children
    if parent_lower == "rom" and child_lower.startswith("rom_"):
        return True

    # Pattern 4: Same base name with different suffixes (e.g., FLASH and
    # FLASH_APP)
    if child_lower.startswith(parent_lower):
        return True

    # Pattern 4b: Parent name with suffix contains child name with suffix
    # (e.g., FLASH_APP contains FLASH_FS, FLASH_TEXT)
    if parent_lower.startswith("flash_") and child_lower.startswith("flash_"):
        return True

    # Pattern 5: Generic parent-child relationship based on size and containment
    # If the child is significantly smaller and has a similar name prefix
    size_ratio = child_region["limit_size"] / parent_region["limit_size"]
    if size_ratio < 0.9:  # Child is less than 90% of parent size
        # Check if names suggest hierarchical relationship
        parent_parts = parent_lower.split("_")
        child_parts = child_lower.split("_")

        # Child name starts with parent name (e.g., FLASH -> FLASH_START)
        if len(child_parts) > len(
                parent_parts) and child_parts[0] == parent_parts[0]:
            return True

    return False
