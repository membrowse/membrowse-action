#!/usr/bin/env python3

"""
memory_regions.py - Refactored modular linker script parser

This module provides a clean, modular approach to parsing GNU LD linker scripts
to extract memory region information including:
- Region names (FLASH, RAM, etc.)
- Start addresses (ORIGIN)
- Sizes (LENGTH)
- Attributes (rx, rw, etc.)

The module is split into focused classes with clear responsibilities:
- LinkerScriptParser: Main parsing orchestrator
- ScriptContentCleaner: Handles preprocessing and cleanup
- ExpressionEvaluator: Evaluates linker script expressions
- MemoryRegionBuilder: Constructs memory region objects
- RegionTypeDetector: Determines region types based on names/attributes
"""

import os
import re
import logging
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# Import ELF parser for architecture detection
try:
    from .elf_parser import get_architecture_info, get_linker_parsing_strategy, ELFInfo
except ImportError:
    from elf_parser import get_architecture_info, get_linker_parsing_strategy, ELFInfo


# Configure logging
logger = logging.getLogger(__name__)


class RegionType(Enum):
    """Memory region types"""

    FLASH = "FLASH"
    ROM = "ROM"
    RAM = "RAM"
    CCM = "CCM"
    EEPROM = "EEPROM"
    BACKUP = "BACKUP"
    UNKNOWN = "UNKNOWN"


@dataclass
class MemoryRegion:
    """Memory region data structure"""

    name: str
    region_type: RegionType
    attributes: str
    start_address: int
    total_size: int

    @property
    def end_address(self) -> int:
        """Calculate end address"""
        return self.start_address + self.total_size - 1

    @property
    def address(self) -> int:
        """Alias for start_address for compatibility"""
        return self.start_address

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for backward compatibility"""
        return {
            "type": self.region_type.value,
            "attributes": self.attributes,
            "start_address": self.start_address,
            "address": self.start_address,  # Duplicate for schema compatibility
            "end_address": self.end_address,
            "total_size": self.total_size,
            "used_size": 0,  # Will be filled by section analysis
            "free_size": self.total_size,  # Will be updated after section analysis
            "utilization_percent": 0.0,
            "sections": [],
        }


class LinkerScriptError(Exception):
    """Base exception for linker script parsing errors"""


class ExpressionEvaluationError(LinkerScriptError):
    """Exception raised when expression evaluation fails"""


class RegionParsingError(LinkerScriptError):
    """Exception raised when memory region parsing fails"""


class ScriptContentCleaner:
    """Handles preprocessing and cleanup of linker script content"""

    @staticmethod
    def clean_content(content: str) -> str:
        """Remove comments and normalize whitespace from linker script content"""
        # Remove C-style comments /* ... */
        content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
        # Remove C++-style comments // ...
        content = re.sub(r"//.*", "", content)

        # Handle preprocessor directives - remove them and their content
        content = ScriptContentCleaner._remove_preprocessor_blocks(content)

        # Remove remaining single-line preprocessor directives
        content = re.sub(
            r"#[a-zA-Z_][a-zA-Z0-9_]*\b.*$", "", content, flags=re.MULTILINE
        )

        # Normalize whitespace
        content = re.sub(r"\s+", " ", content)
        return content

    @staticmethod
    def _remove_preprocessor_blocks(content: str) -> str:
        """Remove preprocessor conditional blocks"""
        # Handle nested #if/#endif blocks more carefully
        # Remove preprocessor directives but preserve variable definitions

        # Handle #if blocks with only preprocessor directives
        # Find blocks without variable assignments (no '=' followed by ';')
        if_blocks_to_remove = []

        # Find all #if...#endif blocks
        if_pattern = r"#if[^#]*?(?:#(?:elif|else)[^#]*?)*?#endif"

        for match in re.finditer(if_pattern, content, re.DOTALL):
            block_content = match.group(0)
            # If the block doesn't contain variable assignments, mark it for
            # removal
            if "=" not in block_content or ";" not in block_content:
                if_blocks_to_remove.append(match.group(0))

        # Remove the identified blocks
        for block in if_blocks_to_remove:
            content = content.replace(block, " ")

        # For remaining #if blocks, remove preprocessor lines but keep content
        # Remove #if, #elif, #else, #endif lines but preserve content
        lines = content.split("\n")
        filtered_lines = []

        for line in lines:
            stripped = line.strip()
            if (
                stripped.startswith("#if")
                or stripped.startswith("#elif")
                or stripped.startswith("#else")
                or stripped.startswith("#endif")
            ):
                # Skip preprocessor directives
                continue
            if stripped.startswith("#error"):
                # Skip error directives
                continue
            filtered_lines.append(line)

        return "\n".join(filtered_lines)


class RegionTypeDetector:
    """Determines memory region types based on names and attributes"""

    # Region type patterns (order matters - more specific first)
    TYPE_PATTERNS = [
        (RegionType.EEPROM, ["eeprom"]),
        (RegionType.CCM, ["ccmram", "ccm"]),
        (RegionType.BACKUP, ["backup"]),
        (RegionType.FLASH, ["flash", "rom", "code"]),
        (RegionType.RAM, ["ram", "sram", "data", "heap", "stack"]),
    ]

    @classmethod
    def detect_type(cls, name: str, attributes: str) -> RegionType:
        """Determine memory region type based on name and attributes"""
        name_lower = name.lower()
        attrs_lower = attributes.lower()

        # Check name patterns first (more specific patterns first)
        for region_type, patterns in cls.TYPE_PATTERNS:
            if any(pattern in name_lower for pattern in patterns):
                return region_type

        # Check attributes if name is not conclusive
        if "x" in attrs_lower and "w" not in attrs_lower:
            # Execute but not write = ROM/FLASH
            return RegionType.ROM
        if "w" in attrs_lower:
            # Writable = RAM
            return RegionType.RAM
        if "r" in attrs_lower and "x" not in attrs_lower and "w" not in attrs_lower:
            # Read-only = ROM
            return RegionType.ROM
        return RegionType.UNKNOWN


class ExpressionEvaluator:
    """Evaluates linker script expressions and variables"""

    def __init__(self):
        self.variables: Dict[str, Any] = {}
        self._memory_regions: Dict[str, MemoryRegion] = {}

    def set_variables(self, variables: Dict[str, Any]) -> None:
        """Set variables for expression evaluation"""
        self.variables = variables.copy()
    
    def add_variables(self, variables: Dict[str, Any]) -> None:
        """Add variables to existing variables dictionary"""
        self.variables.update(variables)

    def set_memory_regions(self, memory_regions: Dict[str, MemoryRegion]) -> None:
        """Set memory regions for ORIGIN/LENGTH function resolution"""
        self._memory_regions = memory_regions.copy()

    def evaluate_expression(
        self, expr: str, resolving_vars: Optional[Set[str]] = None
    ) -> int:
        """Evaluate linker script expression with variables and arithmetic"""
        expr = expr.strip()

        # Initialize set to track variables being resolved (cycle detection)
        if resolving_vars is None:
            resolving_vars = set()

        # Handle linker script functions first
        expr = self._handle_linker_functions(expr)

        # Replace variables with their values
        expr = self._substitute_variables(expr, resolving_vars)

        # Handle size suffixes before arithmetic evaluation
        expr = self._resolve_size_suffixes(expr)

        # Handle simple arithmetic expressions
        return self._evaluate_arithmetic(expr)

    def _substitute_variables(
            self,
            expr: str,
            resolving_vars: Set[str]) -> str:
        """Substitute variables in expression with their values"""
        for var_name, var_value in self.variables.items():
            if (
                var_name in expr
            ):  # Only process variables that are actually in the expression
                if isinstance(var_value, (int, float)):
                    expr = expr.replace(var_name, str(var_value))
                elif isinstance(var_value, str) and var_name not in resolving_vars:
                    # Try to recursively evaluate string variables with cycle
                    # detection
                    try:
                        resolving_vars.add(var_name)
                        resolved_value = self.evaluate_expression(
                            var_value, resolving_vars
                        )
                        resolving_vars.remove(var_name)
                        self.variables[var_name] = (
                            resolved_value  # Cache the resolved value
                        )
                        expr = expr.replace(var_name, str(resolved_value))
                    except Exception:
                        if var_name in resolving_vars:
                            resolving_vars.remove(var_name)
                        # Skip unresolvable variables
        return expr

    def _handle_linker_functions(self, expr: str) -> str:
        """Handle linker script functions like DEFINED(), ORIGIN(), LENGTH()"""
        # Handle DEFINED() function
        expr = re.sub(
            r"DEFINED\s*\(\s*([^)]+)\s*\)",
            self._replace_defined,
            expr)

        # Handle conditional expressions: condition ? value1 : value2
        conditional_pattern = r"([^?]+)\s*\?\s*([^:]+)\s*:\s*([^;,}]+)"
        expr = re.sub(conditional_pattern, self._replace_conditional, expr)

        # Handle ORIGIN() and LENGTH() functions
        expr = re.sub(
            r"ORIGIN\s*\(\s*([^)]+)\s*\)",
            self._replace_origin,
            expr)
        expr = re.sub(
            r"LENGTH\s*\(\s*([^)]+)\s*\)",
            self._replace_length,
            expr)

        # Handle parenthesized expressions
        expr = self._resolve_parenthesized_expressions(expr)

        return expr

    def _replace_defined(self, match: re.Match) -> str:
        """Replace DEFINED() function with 1 or 0"""
        symbol = match.group(1).strip()
        return "1" if symbol in self.variables else "0"

    def _replace_conditional(self, match: re.Match) -> str:
        """Replace conditional expressions"""
        condition = match.group(1).strip()
        true_value = match.group(2).strip()
        false_value = match.group(3).strip()

        try:
            # Evaluate condition
            if condition in ["0", "1"]:
                cond_result = int(condition)
            elif condition in self.variables:
                var_val = self.variables[condition]
                cond_result = var_val if isinstance(
                    var_val, (int, float)) else 0
            elif "DEFINED(" in condition:
                # Extract the symbol name from DEFINED(symbol)
                defined_match = re.search(
                    r"DEFINED\s*\(\s*([^)]+)\s*\)", condition)
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

    def _replace_origin(self, match: re.Match) -> str:
        """Replace ORIGIN() function with actual address"""
        region_name = match.group(1).strip()
        # Check if we have this region in our parsed data
        if region_name in self._memory_regions:
            return str(self._memory_regions[region_name].start_address)
        # Check if this is a basic region we can calculate
        if region_name.upper() == "ROM":
            return "0x80000000"  # Default ROM start for QEMU
        return "0"  # Fallback

    def _replace_length(self, match: re.Match) -> str:
        """Replace LENGTH() function with actual size"""
        region_name = match.group(1).strip()
        # Check if we have this region in our parsed data
        if region_name in self._memory_regions:
            return str(self._memory_regions[region_name].total_size)
        # Check for standard sizes
        if region_name.upper() == "ROM":
            return str(4 * 1024 * 1024)  # 4M for QEMU ROM
        if region_name.upper() == "RAM":
            return str(2 * 1024 * 1024)  # 2M for QEMU RAM
        return "0"  # Fallback

    def _resolve_parenthesized_expressions(self, expr: str) -> str:
        """Resolve parenthesized arithmetic expressions"""
        max_iterations = 5

        for _ in range(max_iterations):
            # Find innermost parentheses (no nested parens inside)
            paren_pattern = r"\(\s*([^()]+)\s*\)"

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

        # Handle hex and octal literals
        expr = re.sub(r"0[xX]([0-9a-fA-F]+)",
                      lambda m: str(int(m.group(1), 16)), expr)

        # Handle octal literals
        expr = re.sub(r"\b0([0-7]+)\b",
                      lambda m: str(int(m.group(1), 8)), expr)

        # Handle size suffixes
        expr = self._resolve_size_suffixes(expr)

        # Use safe arithmetic evaluation instead of eval
        try:
            return self._safe_arithmetic_eval(expr)
        except (ValueError, ArithmeticError) as exc:
            raise ExpressionEvaluationError(
                f"Cannot evaluate expression: {expr}") from exc

    def _evaluate_arithmetic(self, expr: str) -> int:
        """Evaluate arithmetic expressions"""
        # Replace hex and octal literals
        expr = re.sub(r"0[xX]([0-9a-fA-F]+)",
                      lambda m: str(int(m.group(1), 16)), expr)

        # Replace octal literals (0 followed by digits, but not 0x)
        expr = re.sub(r"\b0([0-7]+)\b",
                      lambda m: str(int(m.group(1), 8)), expr)

        # Use safe arithmetic evaluation instead of eval
        try:
            return self._safe_arithmetic_eval(expr)
        except (ValueError, ArithmeticError):
            pass

        # Try to parse as single number
        if expr.startswith("0x") or expr.startswith("0X"):
            return int(expr, 16)
        if expr.startswith("0") and len(expr) > 1:
            return int(expr, 8)
        return int(expr, 10)

    def _safe_arithmetic_eval(self, expr: str) -> int:
        """Safely evaluate arithmetic expressions without using eval"""
        # Only allow safe arithmetic characters
        if not re.match(r"^[0-9+\-*/() \t]+$", expr):
            raise ValueError(f"Invalid characters in expression: {expr}")

        # Use a simple recursive descent parser for arithmetic
        return self._parse_expression(expr.replace(" ", "").replace("\t", ""))

    def _parse_expression(self, expr: str) -> int:
        """Parse arithmetic expression using recursive descent"""
        index = [0]  # Use list to allow modification in nested functions

        def parse_number():
            start = index[0]
            while index[0] < len(expr) and expr[index[0]].isdigit():
                index[0] += 1
            if start == index[0]:
                raise ValueError(f"Expected number at position {index[0]}")
            return int(expr[start:index[0]])

        def parse_factor():
            if index[0] < len(expr) and expr[index[0]] == "(":
                index[0] += 1  # Skip '('
                result = parse_expr()
                if index[0] >= len(expr) or expr[index[0]] != ")":
                    raise ValueError("Missing closing parenthesis")
                index[0] += 1  # Skip ')'
                return result
            if index[0] < len(expr) and expr[index[0]] == "-":
                index[0] += 1  # Skip '-'
                return -parse_factor()
            if index[0] < len(expr) and expr[index[0]] == "+":
                index[0] += 1  # Skip '+'
                return parse_factor()
            return parse_number()

        def parse_term():
            result = parse_factor()
            while index[0] < len(expr) and expr[index[0]] in "*/":
                op = expr[index[0]]
                index[0] += 1
                right = parse_factor()
                if op == "*":
                    result *= right
                else:  # op == "/"
                    if right == 0:
                        raise ArithmeticError("Division by zero")
                    result //= right  # Integer division
            return result

        def parse_expr():
            result = parse_term()
            while index[0] < len(expr) and expr[index[0]] in "+-":
                op = expr[index[0]]
                index[0] += 1
                right = parse_term()
                if op == "+":
                    result += right
                else:  # op == "-"
                    result -= right
            return result

        result = parse_expr()
        if index[0] < len(expr):
            raise ValueError(
                f"Unexpected character at position {index[0]}: {expr[index[0]]}")
        return result

    def _resolve_size_suffixes(self, expr: str) -> str:
        """Resolve size suffixes (K, M, G) in expressions"""
        # Handle size multipliers in expressions
        multipliers = {
            "K": 1024,
            "M": 1024 * 1024,
            "G": 1024 * 1024 * 1024,
            "KB": 1024,
            "MB": 1024 * 1024,
            "GB": 1024 * 1024 * 1024,
        }

        # Pattern to match numbers with suffixes: 256K, 1M, etc.
        pattern = r"(\d+)\s*([KMG]B?)\b"

        def replace_suffix(match):
            number = int(match.group(1))
            suffix = match.group(2).upper()
            return str(number * multipliers[suffix])

        return re.sub(pattern, replace_suffix, expr, flags=re.IGNORECASE)


class VariableExtractor:
    """Extracts and manages variables from linker scripts"""

    def __init__(self, evaluator: ExpressionEvaluator):
        self.evaluator = evaluator
        self.variables: Dict[str, Any] = {}

    def extract_from_script(self, script_path: str) -> None:
        """Extract variable definitions from a linker script"""
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Remove comments and preprocessor directives
        content = ScriptContentCleaner.clean_content(content)

        # Add platform-specific default values
        self._add_platform_defaults(script_path)

        # Find variable assignments: var_name = value;
        var_pattern = r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;]+);"

        # First pass: extract simple variables and store complex ones
        simple_vars = {}
        complex_vars = {}

        for match in re.finditer(var_pattern, content):
            var_name = match.group(1).strip()
            var_value = match.group(2).strip()

            # Skip if this looks like a linker symbol assignment (starts with
            # __)
            if var_name.startswith("__"):
                continue

            try:
                # Try to evaluate simple expressions immediately
                if self._is_simple_expression(var_value):
                    evaluated_value = self.evaluator.evaluate_expression(
                        var_value, set()
                    )
                    simple_vars[var_name] = evaluated_value
                else:
                    # Store complex expressions for later resolution
                    complex_vars[var_name] = var_value
            except Exception:
                # Store as string for potential later resolution
                complex_vars[var_name] = var_value

        # Add simple variables to our variables dict
        self.variables.update(simple_vars)
        self.evaluator.add_variables(self.variables)

        # Multiple passes to resolve complex variables that depend on other
        # variables
        max_iterations = 10  # Increased for more complex dependencies
        for _ in range(max_iterations):
            resolved_any = False
            unresolved_vars = {}

            for var_name, var_value in complex_vars.items():
                try:
                    evaluated_value = self.evaluator.evaluate_expression(
                        var_value, set()
                    )
                    self.variables[var_name] = evaluated_value
                    self.evaluator.add_variables({var_name: evaluated_value})
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

    def _add_platform_defaults(self, script_path: str) -> None:
        """Add common default values for different platforms"""
        script_path_lower = script_path.lower()

        if "mimxrt" in script_path_lower:
            self.variables.update(
                {
                    "MICROPY_HW_FLASH_SIZE": 0x800000,  # 8MB default
                    "MICROPY_HW_FLASH_RESERVED": 0,
                    "MICROPY_HW_SDRAM_AVAIL": 1,  # Enable SDRAM for testing
                    "MICROPY_HW_SDRAM_SIZE": 0x2000000,  # 32MB default
                }
            )
        elif "nrf" in script_path_lower:
            self.variables.update(
                {
                    "_sd_size": 0,
                    "_sd_ram": 0,
                    "_fs_size": 65536,  # 64K default
                    "_bootloader_head_size": 0,
                    "_bootloader_tail_size": 0,
                    "_bootloader_head_ram_size": 0,
                }
            )
        elif "samd" in script_path_lower:
            self.variables.update(
                {
                    "_etext": 0x10000,  # Default code size
                    "_codesize": 0x10000,  # Default 64K
                    "BootSize": 0x2000,  # Default 8K bootloader
                }
            )

    def _is_simple_expression(self, expr: str) -> bool:
        """Check if an expression is simple enough to evaluate immediately"""
        expr = expr.strip()

        # Simple numeric literals
        if re.match(
                r"^0[xX][0-9a-fA-F]+$",
                expr) or re.match(
                r"^\d+[kKmMgG]?$",
                expr):
            return True

        # Simple arithmetic with only literals
        if re.match(r"^[0-9a-fA-Fx+\-*/() \t]+$", expr):
            return True

        return False


class MemoryRegionBuilder:
    """Builds memory region objects from parsed data"""

    def __init__(self, evaluator: ExpressionEvaluator):
        self.evaluator = evaluator

    def parse_memory_block(
            self, memory_content: str) -> Dict[str, MemoryRegion]:
        """Parse individual memory regions from MEMORY block content"""
        memory_regions = {}

        # Try standard format first (with attributes in parentheses)
        standard_pattern = (
            r"(\w+)\s*\(([^)]+)\)\s*:\s*(?:ORIGIN|origin|org)\s*=\s*([^,]+),\s*"
            r"(?:LENGTH|length|len)\s*=\s*([^,}]+?)(?=\s+\w+\s*[\(:]|$|\s*})")

        # Try ESP8266/alternative format (no attributes in parentheses)
        alt_pattern = (
            r"(\w+)\s*:\s*(?:ORIGIN|origin|org)\s*=\s*([^,]+),\s*"
            r"(?:LENGTH|length|len)\s*=\s*([^,}]+?)(?=\s+\w+\s*:|$|\s*})"
        )

        # First try standard pattern
        for match in re.finditer(standard_pattern, memory_content):
            region = self._build_region_from_match(match, has_attributes=True)
            if region:
                memory_regions[region.name] = region

        # If no regions found with standard pattern, try alternative (ESP8266)
        if not memory_regions:
            for match in re.finditer(alt_pattern, memory_content):
                region = self._build_region_from_match(
                    match, has_attributes=False)
                if region:
                    memory_regions[region.name] = region

        return memory_regions

    def _build_region_from_match(
        self, match: re.Match, has_attributes: bool
    ) -> Optional[MemoryRegion]:
        """Build a memory region from a regex match"""
        try:
            if has_attributes:
                name = match.group(1).strip()
                attributes = match.group(2).strip()
                origin_str = match.group(3).strip()
                length_str = match.group(4).strip()
            else:
                name = match.group(1).strip()
                attributes = ""  # No attributes in alternative format
                origin_str = match.group(2).strip()
                length_str = match.group(3).strip()

            origin = self._parse_address(origin_str)
            length = self._parse_size(length_str)
            region_type = RegionTypeDetector.detect_type(name, attributes)

            return MemoryRegion(
                name=name,
                region_type=region_type,
                attributes=attributes,
                start_address=origin,
                total_size=length,
            )

        except Exception as e:
            region_name = match.group(1) if match.groups() else 'unknown'
            logger.warning(
                "Failed to parse memory region %s: %s",
                region_name,
                e)
            return None

    def _parse_address(self, addr_str: str) -> int:
        """Parse address string (supports hex, decimal, variables, and expressions)"""
        addr_str = addr_str.strip()

        # Try to evaluate as expression first (handles variables and
        # arithmetic)
        try:
            return self.evaluator.evaluate_expression(addr_str, set())
        except Exception:
            # Fallback to simple parsing
            try:
                if addr_str.startswith("0x") or addr_str.startswith("0X"):
                    return int(addr_str, 16)
                if addr_str.startswith("0") and len(addr_str) > 1:
                    # Octal notation
                    return int(addr_str, 8)
                return int(addr_str, 10)
            except Exception as exc:
                # Final fallback for complex expressions
                raise ExpressionEvaluationError(
                    f"Could not parse address '{addr_str}' - unsupported expressions"
                ) from exc

    def _parse_size(self, size_str: str) -> int:
        """Parse size string (supports K, M, G suffixes, variables, and expressions)"""
        size_str = size_str.strip()

        # First, try to evaluate as expression (handles variables and arithmetic)
        # This handles complex expressions like "512 * 1024" or variable
        # references
        try:
            return self.evaluator.evaluate_expression(size_str, set())
        except Exception:
            pass

        # If expression evaluation fails, try size suffixes
        try:
            size_str_upper = size_str.upper()

            # Handle size multipliers
            multipliers = {
                "K": 1024,
                "M": 1024 * 1024,
                "G": 1024 * 1024 * 1024,
                "KB": 1024,
                "MB": 1024 * 1024,
                "GB": 1024 * 1024 * 1024,
            }

            for suffix, multiplier in multipliers.items():
                if size_str_upper.endswith(suffix):
                    base_value = size_str[: -len(suffix)]
                    try:
                        # Try to evaluate base value (may contain
                        # variables/expressions)
                        base_int = self.evaluator.evaluate_expression(
                            base_value, set())
                        return base_int * multiplier
                    except Exception:
                        # Fallback to simple parsing
                        return int(base_value) * multiplier

            # Fallback to simple parsing
            if size_str_upper.startswith("0X"):
                return int(size_str, 16)
            if size_str.startswith("0") and len(size_str) > 1:
                return int(size_str, 8)
            return int(size_str, 10)
        except Exception as exc:
            # Final fallback for complex expressions
            raise ExpressionEvaluationError(
                f"Could not parse size '{size_str}' - contains unsupported expressions"
            ) from exc


class LinkerScriptParser:
    """Main parser orchestrator for linker script files"""

    def __init__(self, ld_scripts: List[str], elf_file: Optional[str] = None):
        """Initialize the parser with linker script paths and optional ELF file
        
        Args:
            ld_scripts: List of linker script file paths
            elf_file: Optional path to ELF file for architecture detection
        """
        self.ld_scripts = [str(Path(script).resolve())
                           for script in ld_scripts]
        self.elf_file = str(Path(elf_file).resolve()) if elf_file else None
        self._validate_scripts()

        # Get architecture information from ELF file if provided
        self.elf_info = None
        self.parsing_strategy = {}
        if self.elf_file:
            self.elf_info = get_architecture_info(self.elf_file)
            if self.elf_info:
                self.parsing_strategy = get_linker_parsing_strategy(self.elf_info)
                logger.info("Detected architecture: %s, platform: %s", 
                           self.elf_info.architecture.value, 
                           self.elf_info.platform.value)
            else:
                logger.warning("Could not extract architecture info from ELF file: %s", 
                              self.elf_file)

        # Initialize components
        self.evaluator = ExpressionEvaluator()
        self.variable_extractor = VariableExtractor(self.evaluator)
        self.region_builder = MemoryRegionBuilder(self.evaluator)
        
        # Apply architecture-specific default variables
        if self.parsing_strategy.get('default_variables'):
            self.evaluator.add_variables(self.parsing_strategy['default_variables'])

    def _validate_scripts(self) -> None:
        """Validate that all linker scripts exist"""
        for script in self.ld_scripts:
            if not os.path.exists(script):
                raise FileNotFoundError(f"Linker script not found: {script}")

    def parse_memory_regions(self) -> Dict[str, Dict[str, Any]]:
        """Parse memory regions from linker scripts"""
        # First pass: extract variables from all scripts
        self._extract_all_variables()

        # Second pass: parse memory regions using variables
        memory_regions = self._parse_all_memory_regions()

        # Convert to dictionary format for backward compatibility
        return {name: region.to_dict()
                for name, region in memory_regions.items()}

    def _extract_all_variables(self) -> None:
        """Extract variables from all linker scripts"""
        # Process scripts in reverse order for proper dependency resolution
        for script_path in reversed(self.ld_scripts):
            self.variable_extractor.extract_from_script(script_path)

        # Additional pass: extract variables in forward order for dependencies
        for script_path in self.ld_scripts:
            self.variable_extractor.extract_from_script(script_path)
        
        # Merge extracted variables with existing default variables (preserve architecture defaults)
        self.evaluator.add_variables(self.variable_extractor.variables)

    def _parse_all_memory_regions(self) -> Dict[str, MemoryRegion]:
        """Parse memory regions from all scripts with iterative dependency resolution"""
        memory_regions = {}

        # Parse regions iteratively to handle ORIGIN/LENGTH dependencies
        max_iterations = 3
        for _ in range(max_iterations):
            old_count = len(memory_regions)

            for script_path in self.ld_scripts:
                script_regions = self._parse_single_script(script_path)
                memory_regions.update(script_regions)
                # Update evaluator with current regions for ORIGIN/LENGTH
                # resolution
                self.evaluator.set_memory_regions(memory_regions)

            # If no new regions were added, we're done
            if len(memory_regions) == old_count:
                break

        return memory_regions

    def _parse_single_script(
            self, script_path: str) -> Dict[str, MemoryRegion]:
        """Parse memory regions from a single linker script file"""
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Remove comments and normalize whitespace
        content = ScriptContentCleaner.clean_content(content)

        # Find MEMORY block (case insensitive)
        memory_match = re.search(
            r"MEMORY\s*\{([^}]+)\}",
            content,
            re.IGNORECASE)
        if not memory_match:
            return {}

        memory_content = memory_match.group(1)
        return self.region_builder.parse_memory_block(memory_content)


# Convenience functions for backward compatibility
def parse_linker_scripts(ld_scripts: List[str], elf_file: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Convenience function to parse memory regions from linker scripts

    Args:
        ld_scripts: List of paths to linker script files
        elf_file: Optional path to ELF file for architecture detection

    Returns:
        Dictionary mapping region names to region information

    Raises:
        FileNotFoundError: If any linker script file is not found
        LinkerScriptError: If parsing fails for critical regions
    """
    parser = LinkerScriptParser(ld_scripts, elf_file)
    return parser.parse_memory_regions()


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

    # Check for common embedded memory regions
    region_types = {region["type"] for region in memory_regions.values()}

    if "FLASH" not in region_types and "ROM" not in region_types:
        logger.warning(
            "No FLASH/ROM regions found - unusual for embedded systems")

    if "RAM" not in region_types:
        logger.warning("No RAM regions found - unusual for embedded systems")

    # Check for overlapping regions with intelligent hierarchical detection
    overlaps_found = False

    for name1, region1 in memory_regions.items():
        for name2, region2 in memory_regions.items():
            if name1 >= name2:  # Avoid checking same pair twice
                continue

            # Check for overlap
            if (
                region1["start_address"] < region2["end_address"]
                and region2["start_address"] < region1["end_address"]
            ):

                # Check if this is a valid hierarchical relationship
                if _is_hierarchical_overlap(name1, region1, name2, region2):
                    # This is a valid parent-child relationship, not an error
                    continue
                logger.warning(
                    "Memory regions %s and %s overlap", name1, name2)
                overlaps_found = True

    return not overlaps_found


def _is_hierarchical_overlap(
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
    if region1["total_size"] > region2["total_size"]:
        parent_name, parent_region = name1, region1
        child_name, child_region = name2, region2
    else:
        parent_name, parent_region = name2, region2
        child_name, child_region = name1, region1

    # Check if child is fully contained within parent
    child_fully_contained = (
        child_region["start_address"] >= parent_region["start_address"]
        and child_region["end_address"] <= parent_region["end_address"]
    )

    # Allow for slight overhang due to linker script calculation errors
    # Check if child starts within parent and doesn't extend too far beyond
    MAX_OVERHANG_BYTES = (
        64 * 1024
    )  # 64KB allowance for linker script calculation errors
    child_mostly_contained = (
        child_region["start_address"] >= parent_region["start_address"]
        and child_region["start_address"] <= parent_region["end_address"]
        and child_region["end_address"]
        <= parent_region["end_address"] + MAX_OVERHANG_BYTES
    )

    if not child_fully_contained and not child_mostly_contained:
        return False

    # Check for common hierarchical patterns in embedded systems
    parent_lower = parent_name.lower()
    child_lower = child_name.lower()

    # Pattern 1: FLASH parent with FLASH_* children
    if (
        parent_lower == "flash"
        and child_lower.startswith("flash_")
        and parent_region["type"] == "FLASH"
        and child_region["type"] == "FLASH"
    ):
        return True

    # Pattern 2: RAM parent with RAM_* children
    if (
        parent_lower == "ram"
        and child_lower.startswith("ram_")
        and parent_region["type"] == "RAM"
        and child_region["type"] == "RAM"
    ):
        return True

    # Pattern 3: ROM parent with ROM_* children
    if (
        parent_lower == "rom"
        and child_lower.startswith("rom_")
        and parent_region["type"] == "ROM"
        and child_region["type"] == "ROM"
    ):
        return True

    # Pattern 4: Same base name with different suffixes (e.g., FLASH and
    # FLASH_APP)
    if (
        child_lower.startswith(parent_lower)
        and parent_region["type"] == child_region["type"]
    ):
        return True
    
    # Pattern 4b: Parent name with suffix contains child name with suffix 
    # (e.g., FLASH_APP contains FLASH_FS, FLASH_TEXT)
    if (
        parent_lower.startswith("flash_") and child_lower.startswith("flash_")
        and parent_region["type"] == "FLASH" 
        and child_region["type"] == "FLASH"
    ):
        return True

    # Pattern 5: Generic parent-child relationship based on size and containment
    # If the child is significantly smaller and has a similar name prefix
    size_ratio = child_region["total_size"] / parent_region["total_size"]
    if size_ratio < 0.9:  # Child is less than 90% of parent size
        # Check if names suggest hierarchical relationship
        parent_parts = parent_lower.split("_")
        child_parts = child_lower.split("_")

        # Child name starts with parent name (e.g., FLASH -> FLASH_START)
        if len(child_parts) > len(
                parent_parts) and child_parts[0] == parent_parts[0]:
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
        key=lambda x: x[1]["start_address"])

    for name, region in sorted_regions:
        size_kb = region["total_size"] / 1024
        attributes = region.get("attributes", "")
        lines.append(
            f"  {name:12} ({region['type']:8}): "
            f"0x{region['start_address']:08x} - 0x{region['end_address']:08x} "
            f"({size_kb:8.1f} KB) [{attributes}]"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    # Simple test/demo when run directly
    import sys

    if len(sys.argv) < 2:
        print(
            "Usage: python memory_regions.py <linker_script1> [linker_script2] ...")
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
