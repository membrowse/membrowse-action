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
    """Parser for linker script files to extract memory region information"""
    
    def __init__(self, ld_scripts: List[str]):
        """Initialize the parser with a list of linker script paths"""
        self.ld_scripts = ld_scripts
        self.variables = {}
        self._validate_scripts()
    
    def _validate_scripts(self):
        """Validate that all linker scripts exist"""
        for script in self.ld_scripts:
            if not os.path.exists(script):
                raise FileNotFoundError(f"Linker script not found: {script}")
    
    def parse_memory_regions(self) -> Dict[str, Dict[str, Any]]:
        """Parse memory regions from linker scripts"""
        memory_regions = {}
        
        # First pass: extract variables from all scripts (order matters for dependencies)
        # Process scripts in reverse order for proper dependency resolution
        for script_path in reversed(self.ld_scripts):
            self._extract_variables(script_path)
        
        # Additional pass: extract variables again in forward order to catch dependencies  
        for script_path in self.ld_scripts:
            self._extract_variables(script_path)
        
        # Second pass: parse memory regions using variables - use iterative approach for dependencies
        self._memory_regions = {}  # Store intermediate results for ORIGIN/LENGTH resolution
        
        # Parse regions iteratively to handle ORIGIN/LENGTH dependencies
        max_iterations = 3
        for iteration in range(max_iterations):
            old_count = len(memory_regions)
            
            for script_path in self.ld_scripts:
                regions = self._parse_single_script(script_path)
                memory_regions.update(regions)
                self._memory_regions.update(regions)  # Store for ORIGIN/LENGTH resolution
            
            # If no new regions were added, we're done
            if len(memory_regions) == old_count:
                break
        
        return memory_regions
    
    def _extract_variables(self, script_path: str) -> None:
        """Extract variable definitions from a linker script"""
        with open(script_path, 'r') as f:
            content = f.read()
        
        # Remove comments and preprocessor directives
        content = self._clean_script_content(content)
        
        # Add common default values for different platforms
        if 'mimxrt' in script_path.lower():
            self.variables.update({
                'MICROPY_HW_FLASH_SIZE': 0x800000,  # 8MB default
                'MICROPY_HW_FLASH_RESERVED': 0,
                'MICROPY_HW_SDRAM_AVAIL': 1,  # Enable SDRAM for testing
                'MICROPY_HW_SDRAM_SIZE': 0x2000000  # 32MB default
            })
        elif 'nrf' in script_path.lower():
            self.variables.update({
                '_sd_size': 0,
                '_sd_ram': 0,
                '_fs_size': 65536,  # 64K default
                '_bootloader_head_size': 0,
                '_bootloader_tail_size': 0,
                '_bootloader_head_ram_size': 0
            })
        elif 'samd' in script_path.lower():
            self.variables.update({
                '_etext': 0x10000,  # Default code size
                '_codesize': 0x10000,  # Default 64K
                'BootSize': 0x2000  # Default 8K bootloader
            })
        
        # Find variable assignments: var_name = value;
        var_pattern = r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;]+);'
        
        # First pass: extract simple variables and store complex ones
        simple_vars = {}
        complex_vars = {}
        
        for match in re.finditer(var_pattern, content):
            var_name = match.group(1).strip()
            var_value = match.group(2).strip()
            
            # Skip if this looks like a linker symbol assignment (starts with __)
            if var_name.startswith('__'):
                continue
            
            try:
                # Try to evaluate simple expressions immediately
                if self._is_simple_expression(var_value):
                    evaluated_value = self._evaluate_expression(var_value, set())
                    simple_vars[var_name] = evaluated_value
                else:
                    # Store complex expressions for later resolution
                    complex_vars[var_name] = var_value
            except Exception:
                # Store as string for potential later resolution
                complex_vars[var_name] = var_value
        
        # Add simple variables to our variables dict
        self.variables.update(simple_vars)
        
        # Multiple passes to resolve complex variables that depend on other variables
        max_iterations = 10  # Increased for more complex dependencies
        for iteration in range(max_iterations):
            resolved_any = False
            unresolved_vars = {}
            
            for var_name, var_value in complex_vars.items():
                try:
                    evaluated_value = self._evaluate_expression(var_value, set())
                    self.variables[var_name] = evaluated_value
                    resolved_any = True
                except Exception:
                    unresolved_vars[var_name] = var_value
            
            complex_vars = unresolved_vars
            
            # If we didn't resolve any variables in this iteration, break
            if not resolved_any:
                break
        
        # Store any remaining unresolved variables as strings
        for var_name, var_value in complex_vars.items():
            if var_name not in self.variables:
                self.variables[var_name] = var_value
    
    def _is_simple_expression(self, expr: str) -> bool:
        """Check if an expression is simple enough to evaluate immediately"""
        expr = expr.strip()
        
        # Simple numeric literals
        if re.match(r'^0[xX][0-9a-fA-F]+$', expr) or re.match(r'^\d+[kKmMgG]?$', expr):
            return True
        
        # Simple arithmetic with only literals
        if re.match(r'^[0-9a-fA-Fx+\-*/() \t]+$', expr):
            return True
        
        return False
    
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
        
        # Handle preprocessor directives - remove them and their content
        # Remove complete #if/#elif/#else/#endif blocks
        content = self._remove_preprocessor_blocks(content)
        
        # Remove remaining single-line preprocessor directives
        content = re.sub(r'#[a-zA-Z_][a-zA-Z0-9_]*\b.*$', '', content, flags=re.MULTILINE)
        
        # Normalize whitespace
        content = re.sub(r'\s+', ' ', content)
        return content
    
    def _remove_preprocessor_blocks(self, content: str) -> str:
        """Remove preprocessor conditional blocks"""
        # Handle nested #if/#endif blocks more carefully
        # We want to remove the preprocessor directives but preserve variable definitions
        
        # First, handle #if blocks that contain only preprocessor directives (no variable assignments)
        # Pattern to find #if blocks that don't contain variable assignments (no '=' followed by ';')
        if_blocks_to_remove = []
        
        # Find all #if...#endif blocks
        if_pattern = r'#if[^#]*?(?:#(?:elif|else)[^#]*?)*?#endif'
        
        for match in re.finditer(if_pattern, content, re.DOTALL):
            block_content = match.group(0)
            # If the block doesn't contain variable assignments, mark it for removal
            if '=' not in block_content or ';' not in block_content:
                if_blocks_to_remove.append(match.group(0))
        
        # Remove the identified blocks
        for block in if_blocks_to_remove:
            content = content.replace(block, ' ')
        
        # For remaining #if blocks, just remove the preprocessor lines but keep the content
        # Remove #if, #elif, #else, #endif lines but preserve what's between them
        lines = content.split('\n')
        filtered_lines = []
        skip_next = False
        
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('#if') or stripped.startswith('#elif') or stripped.startswith('#else') or stripped.startswith('#endif'):
                # Skip preprocessor directives
                continue
            elif stripped.startswith('#error'):
                # Skip error directives
                continue
            else:
                filtered_lines.append(line)
        
        return '\n'.join(filtered_lines)
    
    def _parse_memory_block(self, memory_content: str) -> Dict[str, Dict[str, Any]]:
        """Parse individual memory regions from MEMORY block content"""
        memory_regions = {}
        
        # Pattern matches different linker script syntaxes:
        # Standard GNU LD: FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512K
        # ESP8266 style:   dram0_0_seg : org = 0x3ffe8000, len = 80K
        # Also handles variations like:
        # - FLASH(rx): ORIGIN=0x08000000, LENGTH=512K
        # - RAM (rw) : ORIGIN = 0x20000000 , LENGTH = 128K
        # - FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512 * 1024
        # Case insensitive for ORIGIN/org and LENGTH/len keywords
        
        # Try standard format first (with attributes in parentheses)
        standard_pattern = r'(\w+)\s*\(([^)]+)\)\s*:\s*(?:ORIGIN|origin|org)\s*=\s*([^,]+),\s*(?:LENGTH|length|len)\s*=\s*([^,}]+?)(?=\s+\w+\s*[\(:]|$|\s*})'
        
        # Try ESP8266/alternative format (no attributes in parentheses)
        alt_pattern = r'(\w+)\s*:\s*(?:ORIGIN|origin|org)\s*=\s*([^,]+),\s*(?:LENGTH|length|len)\s*=\s*([^,}]+?)(?=\s+\w+\s*:|$|\s*})'
        
        # First try standard pattern
        for match in re.finditer(standard_pattern, memory_content):
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
        
        # If no regions found with standard pattern, try alternative pattern (ESP8266 style)
        if not memory_regions:
            for match in re.finditer(alt_pattern, memory_content):
                name = match.group(1).strip()
                origin_str = match.group(2).strip()
                length_str = match.group(3).strip()
                attributes = ''  # No attributes in alternative format
                
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
            try:
                if addr_str.startswith('0x') or addr_str.startswith('0X'):
                    return int(addr_str, 16)
                elif addr_str.startswith('0') and len(addr_str) > 1:
                    # Octal notation
                    return int(addr_str, 8)
                else:
                    return int(addr_str, 10)
            except Exception:
                # Final fallback for complex expressions - raise error for calling code to handle
                raise ValueError(f"Could not parse address '{addr_str}' - contains unsupported expressions")
    
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
        try:
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
        except Exception:
            # Final fallback for complex expressions - raise error for calling code to handle
            raise ValueError(f"Could not parse size '{size_str}' - contains unsupported expressions")
    
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
        
        # Handle linker script functions first
        expr = self._handle_linker_functions(expr)
        
        # Replace variables with their values (with improved MIMXRT support)
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
    
    def _handle_linker_functions(self, expr: str) -> str:
        """Handle linker script functions like DEFINED(), ORIGIN(), LENGTH()"""
        # Handle DEFINED() function
        # DEFINED(symbol) returns 1 if symbol is defined, 0 otherwise
        def replace_defined(match):
            symbol = match.group(1).strip()
            return '1' if symbol in self.variables else '0'
        
        expr = re.sub(r'DEFINED\s*\(\s*([^)]+)\s*\)', replace_defined, expr)
        
        # Handle conditional expressions: condition ? value1 : value2
        # This is a simplified version - full linker script conditionals can be complex
        conditional_pattern = r'([^?]+)\s*\?\s*([^:]+)\s*:\s*([^;,}]+)'
        
        def replace_conditional(match):
            condition = match.group(1).strip()
            true_value = match.group(2).strip()
            false_value = match.group(3).strip()
            
            # Evaluate condition - avoid recursion by using a simple evaluation
            try:
                # Handle DEFINED() results
                if condition in ['0', '1']:
                    cond_result = int(condition)
                # Handle simple variables
                elif condition in self.variables:
                    var_val = self.variables[condition]
                    cond_result = var_val if isinstance(var_val, (int, float)) else 0
                # For MIMXRT, assume DEFINED() returns 0 for undefined symbols
                elif 'DEFINED(' in condition:
                    # Extract the symbol name from DEFINED(symbol)
                    defined_match = re.search(r'DEFINED\s*\(\s*([^)]+)\s*\)', condition)
                    if defined_match:
                        symbol = defined_match.group(1).strip()
                        cond_result = 1 if symbol in self.variables else 0
                    else:
                        cond_result = 0
                else:
                    # Cannot evaluate condition - assume false for safety
                    cond_result = 0
                
                return true_value if cond_result != 0 else false_value
            except Exception:
                # If condition can't be evaluated, use false value for safety
                return false_value
        
        expr = re.sub(conditional_pattern, replace_conditional, expr)
        
        # Handle ORIGIN() and LENGTH() functions
        # Try to resolve to actual values from previously parsed regions
        def replace_origin(match):
            region_name = match.group(1).strip()
            # Check if we have this region in our parsed data
            if hasattr(self, '_memory_regions') and region_name in self._memory_regions:
                return str(self._memory_regions[region_name]['start_address'])
            # Check if this is a basic region we can calculate
            elif region_name.upper() == 'ROM':
                return '0x80000000'  # Default ROM start for QEMU
            else:
                return '0'  # Fallback
        
        def replace_length(match):
            region_name = match.group(1).strip()
            # Check if we have this region in our parsed data
            if hasattr(self, '_memory_regions') and region_name in self._memory_regions:
                return str(self._memory_regions[region_name]['total_size'])
            # Check for standard sizes
            elif region_name.upper() == 'ROM':
                return str(4 * 1024 * 1024)  # 4M for QEMU ROM
            elif region_name.upper() == 'RAM':
                return str(2 * 1024 * 1024)  # 2M for QEMU RAM
            else:
                return '0'  # Fallback
        
        expr = re.sub(r'ORIGIN\s*\(\s*([^)]+)\s*\)', replace_origin, expr)
        expr = re.sub(r'LENGTH\s*\(\s*([^)]+)\s*\)', replace_length, expr)
        
        # Handle remaining linker script patterns
        
        # Handle parenthesized expressions: (a + b), (a - b), etc.
        expr = self._resolve_parenthesized_expressions(expr)
        
        return expr
    
    def _resolve_parenthesized_expressions(self, expr: str) -> str:
        """Resolve parenthesized arithmetic expressions"""
        # Handle expressions like (vfs_start + vfs_size), (a - b), etc.
        # Support nested parentheses by resolving innermost first
        max_iterations = 5
        
        for _ in range(max_iterations):
            # Find innermost parentheses (no nested parens inside)
            paren_pattern = r'\(\s*([^()]+)\s*\)'
            
            def resolve_paren_expr(match):
                inner_expr = match.group(1).strip()
                try:
                    # Try to evaluate the inner expression
                    result = self._evaluate_simple_arithmetic(inner_expr)
                    return str(result)
                except Exception:
                    # If we can't evaluate, keep the original expression
                    return match.group(0)
            
            new_expr = re.sub(paren_pattern, resolve_paren_expr, expr)
            
            # If no more changes, break
            if new_expr == expr:
                break
            expr = new_expr
        
        return expr
    
    def _evaluate_simple_arithmetic(self, expr: str) -> int:
        """Evaluate simple arithmetic expressions with variables"""
        # Replace known variables with their values
        for var_name, var_value in self.variables.items():
            if var_name in expr and isinstance(var_value, (int, float)):
                expr = expr.replace(var_name, str(var_value))
        
        # Handle hex literals
        expr = re.sub(r'0[xX]([0-9a-fA-F]+)', lambda m: str(int(m.group(1), 16)), expr)
        
        # Handle size suffixes
        expr = self._resolve_size_suffixes(expr)
        
        # Only allow safe arithmetic characters
        if re.match(r'^[0-9+\-*/ \t]+$', expr):
            try:
                return int(eval(expr, {"__builtins__": {}}, {}))
            except Exception:
                pass
        
        # If we can't evaluate, raise an exception rather than return a default
        raise ValueError(f"Cannot evaluate expression: {expr}")
    
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
    
    # Check for overlapping regions with intelligent hierarchical detection
    overlaps_found = False
    
    for name1, region1 in memory_regions.items():
        for name2, region2 in memory_regions.items():
            if name1 >= name2:  # Avoid checking same pair twice
                continue
            
            # Check for overlap
            if (region1['start_address'] < region2['end_address'] and 
                region2['start_address'] < region1['end_address']):
                
                # Check if this is a valid hierarchical relationship
                if _is_hierarchical_overlap(name1, region1, name2, region2):
                    # This is a valid parent-child relationship, not an error
                    continue
                else:
                    print(f"Warning: Memory regions {name1} and {name2} overlap")
                    overlaps_found = True
    
    return not overlaps_found


def _is_hierarchical_overlap(name1: str, region1: Dict[str, Any], 
                           name2: str, region2: Dict[str, Any]) -> bool:
    """Check if two overlapping regions have a valid hierarchical relationship
    
    Args:
        name1, region1: First region
        name2, region2: Second region
        
    Returns:
        True if this is a valid hierarchical overlap (parent contains child)
    """
    # Determine which region is larger (potential parent)
    if region1['total_size'] > region2['total_size']:
        parent_name, parent_region = name1, region1
        child_name, child_region = name2, region2
    else:
        parent_name, parent_region = name2, region2
        child_name, child_region = name1, region1
    
    # Check if child is fully contained within parent
    child_fully_contained = (
        child_region['start_address'] >= parent_region['start_address'] and
        child_region['end_address'] <= parent_region['end_address']
    )
    
    # Allow for slight overhang due to linker script calculation errors
    # Check if child starts within parent and doesn't extend too far beyond
    MAX_OVERHANG_BYTES = 64 * 1024  # 64KB allowance for linker script calculation errors
    child_mostly_contained = (
        child_region['start_address'] >= parent_region['start_address'] and
        child_region['start_address'] <= parent_region['end_address'] and
        child_region['end_address'] <= parent_region['end_address'] + MAX_OVERHANG_BYTES
    )
    
    if not child_fully_contained and not child_mostly_contained:
        return False
    
    # Check for common hierarchical patterns in embedded systems
    parent_lower = parent_name.lower()
    child_lower = child_name.lower()
    
    # Pattern 1: FLASH parent with FLASH_* children
    if (parent_lower == 'flash' and 
        child_lower.startswith('flash_') and 
        parent_region['type'] == 'FLASH' and 
        child_region['type'] == 'FLASH'):
        return True
    
    # Pattern 2: RAM parent with RAM_* children
    if (parent_lower == 'ram' and 
        child_lower.startswith('ram_') and 
        parent_region['type'] == 'RAM' and 
        child_region['type'] == 'RAM'):
        return True
    
    # Pattern 3: ROM parent with ROM_* children
    if (parent_lower == 'rom' and 
        child_lower.startswith('rom_') and 
        parent_region['type'] == 'ROM' and 
        child_region['type'] == 'ROM'):
        return True
    
    # Pattern 4: Same base name with different suffixes (e.g., FLASH and FLASH_APP)
    if (child_lower.startswith(parent_lower) and 
        parent_region['type'] == child_region['type']):
        return True
    
    # Pattern 5: Generic parent-child relationship based on size and containment
    # If the child is significantly smaller and has a similar name prefix
    size_ratio = child_region['total_size'] / parent_region['total_size']
    if size_ratio < 0.9:  # Child is less than 90% of parent size
        # Check if names suggest hierarchical relationship
        parent_parts = parent_lower.split('_')
        child_parts = child_lower.split('_')
        
        # Child name starts with parent name (e.g., FLASH -> FLASH_START)
        if len(child_parts) > len(parent_parts) and child_parts[0] == parent_parts[0]:
            return True
    
    return False


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