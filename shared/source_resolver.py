#!/usr/bin/env python3
"""
Source file resolution for symbols using DWARF debug information.

This module handles the complex logic of mapping symbols to their source files
using DWARF debug information, with optimizations for performance and accuracy.
"""

import os
import bisect
from typing import Dict, List, Optional, Any


class SourceFileResolver:
    """Handles source file resolution logic for symbols using DWARF debug information"""

    def __init__(self, dwarf_data: Dict[str, Any], system_header_cache: Dict[str, bool]):
        """Initialize with DWARF data dictionaries and system header cache."""
        self.dwarf_data = dwarf_data
        self.system_header_cache = system_header_cache

    def extract_source_file(self, symbol_name: str, symbol_type: str, symbol_address: int = None) -> str:
        """Extract source file using pre-built DWARF dictionaries.

        This method uses fast dictionary lookups instead of parsing DWARF data.
        The dictionaries are populated once during initialization for maximum performance.

        Args:
            symbol_name: Name of the symbol
            symbol_type: Type of the symbol (FUNC, OBJECT, etc.)
            symbol_address: Address of the symbol (optional)

        Returns:
            Basename of the source file, or empty string if not found
        """
        # Use dictionary-based lookups for maximum performance
        if not self.dwarf_data:
            return ""  # No DWARF data available

        # Priority 1: Direct symbol lookup from DWARF dictionaries (DIE-based, most reliable)
        symbol_key = (symbol_name, symbol_address or 0)
        if symbol_key in self.dwarf_data['symbol_to_file']:
            source_file = self.dwarf_data['symbol_to_file'][symbol_key]
            source_file_basename = os.path.basename(source_file)

            # For FUNC symbols, if DIE points to .c file, trust it over line program
            # This handles cases with inlined functions from headers
            if symbol_type == 'FUNC' and source_file_basename.endswith('.c'):
                return source_file_basename

            # For .h files, check if we should prefer the CU source file
            if (source_file_basename.endswith('.h') and symbol_address is not None
                    and symbol_address > 0):
                if symbol_address in self.dwarf_data['address_to_cu_file']:
                    cu_source_file = self.dwarf_data['address_to_cu_file'][symbol_address]
                    if cu_source_file and cu_source_file.endswith('.c'):
                        return os.path.basename(cu_source_file)

            return source_file_basename

        # Priority 2: Address-based lookup for FUNC symbols (fallback)
        if symbol_address is not None and symbol_address > 0 and symbol_type == 'FUNC':
            return self._resolve_by_address(symbol_address)

        # Priority 3: Fallback lookups for OBJECT symbols and edge cases
        return self._resolve_fallback(symbol_name, symbol_address)

    def _resolve_by_address(self, symbol_address: int) -> str:
        """Resolve source file by symbol address."""
        # Exact address lookup
        if symbol_address in self.dwarf_data['address_to_file']:
            source_file = self.dwarf_data['address_to_file'][symbol_address]
            source_file_basename = os.path.basename(source_file)

            # Prefer .c files over .h files when available
            if (source_file_basename.endswith('.h')
                    and symbol_address in self.dwarf_data['address_to_cu_file']):
                cu_source_file = self.dwarf_data['address_to_cu_file'][symbol_address]
                if cu_source_file and cu_source_file.endswith('.c'):
                    return os.path.basename(cu_source_file)

            return source_file_basename

        # Proximity search using optimized algorithm
        nearby_addr = self._find_nearby_address(symbol_address)
        if nearby_addr is not None:
            source_file = self.dwarf_data['address_to_file'][nearby_addr]
            source_file_basename = os.path.basename(source_file)

            # Apply .h/.c preference logic
            if (source_file_basename.endswith('.h')
                    and nearby_addr in self.dwarf_data['address_to_cu_file']):
                cu_source_file = self.dwarf_data['address_to_cu_file'][nearby_addr]
                if cu_source_file and cu_source_file.endswith('.c'):
                    return os.path.basename(cu_source_file)

            return source_file_basename

        return ""

    def _resolve_fallback(self, symbol_name: str, symbol_address: int) -> str:
        """Fallback resolution methods for edge cases."""
        # Try address-based CU mapping
        if symbol_address is not None and symbol_address > 0:
            if symbol_address in self.dwarf_data['address_to_cu_file']:
                source_file = self.dwarf_data['address_to_cu_file'][symbol_address]
                return os.path.basename(source_file)

        # Try symbol with address=0 fallback
        fallback_key = (symbol_name, 0)
        if fallback_key in self.dwarf_data['symbol_to_file']:
            source_file = self.dwarf_data['symbol_to_file'][fallback_key]
            return os.path.basename(source_file)

        # No source file information found
        return ""

    def _find_nearby_address(self, target_address: int, max_distance: int = 100) -> Optional[int]:
        """Find nearby address using dictionary-based search."""
        if not self.dwarf_data['address_to_file']:
            return None

        # Create sorted list from dictionary keys for efficient search
        if not hasattr(self, '_sorted_addresses'):
            addresses = self.dwarf_data['address_to_file'].keys()
            self._sorted_addresses = sorted(addresses)

        # Binary search to find closest address
        idx = bisect.bisect_left(self._sorted_addresses, target_address)

        candidates = []

        # Check address at or after target
        if idx < len(self._sorted_addresses):
            addr = self._sorted_addresses[idx]
            distance = abs(addr - target_address)
            if distance <= max_distance:
                candidates.append((distance, addr))

        # Check address before target
        if idx > 0:
            addr = self._sorted_addresses[idx - 1]
            distance = abs(addr - target_address)
            if distance <= max_distance:
                candidates.append((distance, addr))

        # Return closest address
        if candidates:
            candidates.sort()  # Sort by distance
            return candidates[0][1]  # Return address with minimum distance

        return None