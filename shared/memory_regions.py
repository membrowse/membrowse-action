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
        self.variables = {}  # Store defined variables
        self._validate_scripts()
    
    def _validate_scripts(self):
        """Validate that all linker scripts exist"""
        for script in self.ld_scripts:
            if not os.path.exists(script):
                raise FileNotFoundError(f"Linker script not found: {script}")
    
    def parse_memory_regions(self) -> Dict[str, Dict[str, Any]]:
        """Parse memory regions from linker scripts"""
        memory_regions = {}
        
        # First pass: extract variables from all scripts
        for script_path in self.ld_scripts:
            self._extract_variables(script_path)
        
        # Second pass: parse memory regions using variables
        for script_path in self.ld_scripts:
            regions = self._parse_single_script(script_path)
            memory_regions.update(regions)
        
        return memory_regions
    
    def _extract_variables(self, script_path: str) -> None:
        """Extract variable definitions from a linker script"""
        with open(script_path, 'r') as f:
            content = f.read()
        
        # Remove comments
        content = self._clean_script_content(content)
        
        # Find variable assignments: var_name = value;
        var_pattern = r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;]+);'
        
        for match in re.finditer(var_pattern, content):
            var_name = match.group(1).strip()
            var_value = match.group(2).strip()
            
            try:
                # Try to evaluate the variable value
                evaluated_value = self._evaluate_expression(var_value, set())
                self.variables[var_name] = evaluated_value
            except Exception:
                # If evaluation fails, store as string for potential later resolution
                self.variables[var_name] = var_value
    
    def _parse_single_script(self, script_path: str) -> Dict[str, Dict[str, Any]]:
        """Parse memory regions from a single linker script file"""
        with open(script_path, 'r') as f:
            content = f.read()
        
        # Remove comments and normalize whitespace
        content = self._clean_script_content(content)
        
        # Find MEMORY block (case insensitive)
        memory_match = re.search(r'MEMORY\s*\{([^}]+)\}', content, re.IGNORECASE)
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
        # - FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512 * 1024
        # Case insensitive for ORIGIN and LENGTH keywords
        # Use non-greedy matching to stop at word boundaries or end of block
        region_pattern = r'(\w+)\s*\(([^)]+)\)\s*:\s*(?:ORIGIN|origin)\s*=\s*([^,]+),\s*(?:LENGTH|length)\s*=\s*([^,}]+?)(?=\s+\w+\s*\(|$|\s*})'
        
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
        """Parse address string (supports hex, decimal, variables, and expressions)"""
        addr_str = addr_str.strip()
        
        # Try to evaluate as expression first (handles variables and arithmetic)
        try:
            return self._evaluate_expression(addr_str, set())
        except Exception:
            # Fallback to simple parsing
            if addr_str.startswith('0x') or addr_str.startswith('0X'):
                return int(addr_str, 16)
            elif addr_str.startswith('0') and len(addr_str) > 1:
                # Octal notation
                return int(addr_str, 8)
            else:
                return int(addr_str, 10)
    
    def _parse_size(self, size_str: str) -> int:
        """Parse size string (supports K, M, G suffixes, variables, and expressions)"""
        size_str = size_str.strip()
        
        # First, try to evaluate as expression (handles variables and arithmetic)
        # This handles complex expressions like "512 * 1024" or variable references
        try:
            return self._evaluate_expression(size_str, set())
        except Exception:
            pass
        
        # If expression evaluation fails, try size suffixes
        size_str_upper = size_str.upper()
        
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
            if size_str_upper.endswith(suffix):
                base_value = size_str[:-len(suffix)]
                try:
                    # Try to evaluate the base value (may contain variables/expressions)
                    base_int = self._evaluate_expression(base_value, set())
                    return base_int * multiplier
                except Exception:
                    # Fallback to simple parsing
                    return int(base_value) * multiplier
        
        # Fallback to simple parsing
        if size_str_upper.startswith('0X'):
            return int(size_str, 16)
        elif size_str.startswith('0') and len(size_str) > 1:
            return int(size_str, 8)
        else:
            return int(size_str, 10)
    
    def _determine_region_type(self, name: str, attributes: str) -> str:
        """Determine memory region type based on name and attributes"""
        name_lower = name.lower()
        attrs_lower = attributes.lower()
        
        # Check name patterns first (more specific patterns first)
        if 'eeprom' in name_lower:
            return 'EEPROM'
        elif 'ccmram' in name_lower or 'ccm' in name_lower:  # Core Coupled Memory
            return 'CCM'
        elif 'backup' in name_lower:
            return 'BACKUP'
        elif any(pattern in name_lower for pattern in ['flash', 'rom', 'code']):
            return 'FLASH'
        elif any(pattern in name_lower for pattern in ['ram', 'sram', 'data', 'heap', 'stack']):
            return 'RAM'
        
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
    
    def _evaluate_expression(self, expr: str, resolving_vars: set = None) -> int:
        """Evaluate a linker script expression (supports variables and basic arithmetic)"""
        expr = expr.strip()
        
        # Initialize set to track variables being resolved (cycle detection)
        if resolving_vars is None:
            resolving_vars = set()
        
        # Replace variables with their values
        for var_name, var_value in self.variables.items():
            if var_name in expr:  # Only process variables that are actually in the expression
                if isinstance(var_value, (int, float)):
                    expr = expr.replace(var_name, str(var_value))
                elif isinstance(var_value, str) and var_name not in resolving_vars:
                    # Try to recursively evaluate string variables with cycle detection
                    try:
                        resolving_vars.add(var_name)
                        resolved_value = self._evaluate_expression(var_value, resolving_vars)
                        resolving_vars.remove(var_name)
                        self.variables[var_name] = resolved_value  # Cache the resolved value
                        expr = expr.replace(var_name, str(resolved_value))
                    except Exception:
                        if var_name in resolving_vars:
                            resolving_vars.remove(var_name)
                        pass  # Skip unresolvable variables
        
        # Handle size suffixes before arithmetic evaluation
        expr = self._resolve_size_suffixes(expr)
        
        # Handle simple arithmetic expressions
        # Security note: Using eval() with a restricted environment
        # Only allow basic arithmetic operations and hex/decimal literals
        
        # Replace hex literals for eval
        expr = re.sub(r'0[xX]([0-9a-fA-F]+)', lambda m: str(int(m.group(1), 16)), expr)
        
        # Only allow safe characters for evaluation
        if re.match(r'^[0-9+\-*/() \t]+$', expr):
            try:
                # Safe evaluation with restricted builtins
                return int(eval(expr, {"__builtins__": {}}, {}))
            except Exception:
                pass
        
        # Try to parse as single number
        if expr.startswith('0x') or expr.startswith('0X'):
            return int(expr, 16)
        elif expr.startswith('0') and len(expr) > 1:
            return int(expr, 8)
        else:
            return int(expr, 10)
    
    def _resolve_size_suffixes(self, expr: str) -> str:
        """Resolve size suffixes (K, M, G) in expressions"""
        # Handle size multipliers in expressions
        multipliers = {
            'K': 1024,
            'M': 1024 * 1024,
            'G': 1024 * 1024 * 1024,
            'KB': 1024,
            'MB': 1024 * 1024,
            'GB': 1024 * 1024 * 1024
        }
        
        # Pattern to match numbers with suffixes: 256K, 1M, etc.
        pattern = r'(\d+)\s*([KMG]B?)\b'
        
        def replace_suffix(match):
            number = int(match.group(1))
            suffix = match.group(2).upper()
            return str(number * multipliers[suffix])
        
        return re.sub(pattern, replace_suffix, expr, flags=re.IGNORECASE)


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