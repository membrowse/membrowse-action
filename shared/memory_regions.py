#!/usr/bin/env python3

"""
memory_regions.py - Parses linker scripts to extract memory region information

This module handles the parsing of GNU LD linker script MEMORY blocks
to extract memory region definitions including:
- Region names (FLASH, RAM, etc.)
- Start addresses (ORIGIN)
- Sizes (LENGTH)
- Attributes (rx, rw, etc.)
"""

import os
import re
from typing import Dict, List, Any


class LinkerScriptParser:
    """Parses linker scripts to extract memory regions"""
    
    def __init__(self, ld_scripts: List[str]):
        self.ld_scripts = ld_scripts
        self._validate_scripts()
    
    def _validate_scripts(self):
        """Validate that all linker scripts exist"""
        for script in self.ld_scripts:
            if not os.path.exists(script):
                raise FileNotFoundError(f"Linker script not found: {script}")
    
    def parse_memory_regions(self) -> Dict[str, Dict[str, Any]]:
        """Parse memory regions from linker scripts"""
        memory_regions = {}
        
        for script_path in self.ld_scripts:
            regions = self._parse_single_script(script_path)
            memory_regions.update(regions)
        
        return memory_regions
    
    def _parse_single_script(self, script_path: str) -> Dict[str, Dict[str, Any]]:
        """Parse memory regions from a single linker script file"""
        with open(script_path, 'r') as f:
            content = f.read()
        
        # Remove comments and normalize whitespace
        content = self._clean_script_content(content)
        
        # Find MEMORY block
        memory_match = re.search(r'MEMORY\s*{([^}]+)}', content, re.IGNORECASE)
        if not memory_match:
            return {}
        
        memory_content = memory_match.group(1)
        return self._parse_memory_block(memory_content)
    
    def _clean_script_content(self, content: str) -> str:
        """Remove comments and normalize whitespace from linker script content"""
        # Remove C-style comments /* ... */
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        # Remove C++-style comments // ...
        content = re.sub(r'//.*', '', content)
        # Normalize whitespace
        content = re.sub(r'\s+', ' ', content)
        return content
    
    def _parse_memory_block(self, memory_content: str) -> Dict[str, Dict[str, Any]]:
        """Parse individual memory regions from MEMORY block content"""
        memory_regions = {}
        
        # Pattern matches: FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512K
        # Also handles variations like:
        # - FLASH(rx): ORIGIN=0x08000000, LENGTH=512K
        # - RAM (rw) : ORIGIN = 0x20000000 , LENGTH = 128K
        region_pattern = r'(\w+)\s*\(([^)]+)\)\s*:\s*ORIGIN\s*=\s*([^,]+),\s*LENGTH\s*=\s*([^,\s]+)'
        
        for match in re.finditer(region_pattern, memory_content):
            name = match.group(1).strip()
            attributes = match.group(2).strip()
            origin_str = match.group(3).strip()
            length_str = match.group(4).strip()
            
            try:
                origin = self._parse_address(origin_str)
                length = self._parse_size(length_str)
                
                memory_regions[name] = {
                    'type': self._determine_region_type(name, attributes),
                    'attributes': attributes,
                    'start_address': origin,
                    'address': origin,  # Duplicate for schema compatibility
                    'end_address': origin + length - 1,
                    'total_size': length,
                    'used_size': 0,  # Will be filled by section analysis
                    'free_size': length,  # Will be updated after section analysis
                    'utilization_percent': 0.0,
                    'sections': []
                }
            except ValueError as e:
                print(f"Warning: Failed to parse memory region {name}: {e}")
                continue
        
        return memory_regions
    
    def _parse_address(self, addr_str: str) -> int:
        """Parse address string (supports hex and decimal)"""
        addr_str = addr_str.strip()
        
        if addr_str.startswith('0x') or addr_str.startswith('0X'):
            return int(addr_str, 16)
        elif addr_str.startswith('0') and len(addr_str) > 1:
            # Octal notation
            return int(addr_str, 8)
        else:
            return int(addr_str, 10)
    
    def _parse_size(self, size_str: str) -> int:
        """Parse size string (supports K, M, G suffixes)"""
        size_str = size_str.strip().upper()
        
        # Handle size multipliers
        multipliers = {
            'K': 1024,
            'M': 1024 * 1024,
            'G': 1024 * 1024 * 1024,
            'KB': 1024,
            'MB': 1024 * 1024,
            'GB': 1024 * 1024 * 1024
        }
        
        for suffix, multiplier in multipliers.items():
            if size_str.endswith(suffix):
                base_value = size_str[:-len(suffix)]
                return int(base_value) * multiplier
        
        # Handle hex or decimal without suffix
        if size_str.startswith('0X'):
            return int(size_str, 16)
        elif size_str.startswith('0') and len(size_str) > 1:
            return int(size_str, 8)
        else:
            return int(size_str, 10)
    
    def _determine_region_type(self, name: str, attributes: str) -> str:
        """Determine memory region type based on name and attributes"""
        name_lower = name.lower()
        attrs_lower = attributes.lower()
        
        # Check name patterns first
        if any(pattern in name_lower for pattern in ['flash', 'rom', 'code']):
            return 'FLASH'
        elif any(pattern in name_lower for pattern in ['ram', 'sram', 'data', 'heap', 'stack']):
            return 'RAM'
        elif 'eeprom' in name_lower:
            return 'EEPROM'
        elif 'ccm' in name_lower:  # Core Coupled Memory
            return 'CCM'
        elif 'backup' in name_lower:
            return 'BACKUP'
        
        # Check attributes if name is not conclusive
        elif 'x' in attrs_lower and 'w' not in attrs_lower:
            # Execute but not write = ROM/FLASH
            return 'ROM'
        elif 'w' in attrs_lower:
            # Writable = RAM
            return 'RAM'
        elif 'r' in attrs_lower and 'x' not in attrs_lower and 'w' not in attrs_lower:
            # Read-only = ROM
            return 'ROM'
        else:
            return 'UNKNOWN'


def parse_linker_scripts(ld_scripts: List[str]) -> Dict[str, Dict[str, Any]]:
    """Convenience function to parse memory regions from linker scripts
    
    Args:
        ld_scripts: List of paths to linker script files
        
    Returns:
        Dictionary mapping region names to region information
        
    Raises:
        FileNotFoundError: If any linker script file is not found
        ValueError: If parsing fails for critical regions
    """
    parser = LinkerScriptParser(ld_scripts)
    return parser.parse_memory_regions()


def validate_memory_regions(memory_regions: Dict[str, Dict[str, Any]]) -> bool:
    """Validate that parsed memory regions are reasonable
    
    Args:
        memory_regions: Dictionary of memory regions
        
    Returns:
        True if regions appear valid, False otherwise
    """
    if not memory_regions:
        print("Warning: No memory regions found in linker scripts")
        return False
    
    # Check for common embedded memory regions
    region_types = {region['type'] for region in memory_regions.values()}
    
    if 'FLASH' not in region_types and 'ROM' not in region_types:
        print("Warning: No FLASH/ROM regions found - unusual for embedded systems")
    
    if 'RAM' not in region_types:
        print("Warning: No RAM regions found - unusual for embedded systems")
    
    # Check for overlapping regions
    for name1, region1 in memory_regions.items():
        for name2, region2 in memory_regions.items():
            if name1 >= name2:  # Avoid checking same pair twice
                continue
            
            # Check for overlap
            if (region1['start_address'] < region2['end_address'] and 
                region2['start_address'] < region1['end_address']):
                print(f"Warning: Memory regions {name1} and {name2} overlap")
                return False
    
    return True


def get_region_summary(memory_regions: Dict[str, Dict[str, Any]]) -> str:
    """Generate a human-readable summary of memory regions
    
    Args:
        memory_regions: Dictionary of memory regions
        
    Returns:
        Multi-line string describing the memory layout
    """
    if not memory_regions:
        return "No memory regions found"
    
    lines = ["Memory Layout:"]
    
    # Sort regions by start address
    sorted_regions = sorted(
        memory_regions.items(),
        key=lambda x: x[1]['start_address']
    )
    
    for name, region in sorted_regions:
        size_kb = region['total_size'] / 1024
        lines.append(
            f"  {name:12} ({region['type']:8}): "
            f"0x{region['start_address']:08x} - 0x{region['end_address']:08x} "
            f"({size_kb:8.1f} KB) [{region['attributes']}]"
        )
    
    return "\n".join(lines)


if __name__ == '__main__':
    # Simple test/demo when run directly
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python memory_regions.py <linker_script1> [linker_script2] ...")
        sys.exit(1)
    
    try:
        regions = parse_linker_scripts(sys.argv[1:])
        print(get_region_summary(regions))
        
        if validate_memory_regions(regions):
            print("\nMemory layout validation: PASSED")
        else:
            print("\nMemory layout validation: FAILED")
            
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)