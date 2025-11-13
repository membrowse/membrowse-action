#!/usr/bin/env python3
# pylint: disable=too-many-lines

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
"""

import os
import re
import logging
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass
from pathlib import Path

# Import ELF parser for architecture detection
from .elf_info import get_architecture_info, get_linker_parsing_strategy


# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class MemoryRegion:  # pylint: disable=too-few-public-methods
    """Memory region data structure"""

    name: str
    attributes: str
    address: int
    limit_size: int

    @property
    def end_address(self) -> int:
        """Calculate end address"""
        return self.address + self.limit_size - 1

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
        return {
            "attributes": self.attributes,
            "address": self.address,
            "end_address": self.end_address,
            "limit_size": self.limit_size,
        }


class LinkerScriptError(Exception):
    """Base exception for linker script parsing errors"""


class ExpressionEvaluationError(LinkerScriptError):
    """Exception raised when expression evaluation fails"""


class RegionParsingError(LinkerScriptError):
    """Exception raised when memory region parsing fails"""


class VariableResolutionError(LinkerScriptError):
    """Exception raised when variable resolution fails"""


class ScriptContentCleaner:  # pylint: disable=too-few-public-methods
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

    def set_memory_regions(self,
                           memory_regions: Dict[str,
                                                MemoryRegion]) -> None:
        """Set memory regions for ORIGIN/LENGTH function resolution"""
        self._memory_regions = memory_regions.copy()

    def get_memory_regions(self) -> Dict[str, MemoryRegion]:
        """Get copy of current memory regions"""
        return self._memory_regions.copy()

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
            # Quick substring check first (fast)
            if var_name not in expr:
                continue

            # Use word boundary regex to check if variable is in expression
            # This avoids matching _ram_start when looking for _app_ram_start
            var_pattern = r'\b' + re.escape(var_name) + r'\b'
            if not re.search(var_pattern, expr):
                continue  # Variable not in expression (was substring), skip

            if isinstance(var_value, (int, float)):
                # Substitute numeric values
                expr = re.sub(var_pattern, str(var_value), expr)
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
                    expr = re.sub(var_pattern, str(resolved_value), expr)
                except (ExpressionEvaluationError, VariableResolutionError):
                    if var_name in resolving_vars:
                        resolving_vars.remove(var_name)
                    # Skip unresolvable variables - part of iterative
                    # resolution
        return expr

    def _handle_linker_functions(self, expr: str) -> str:
        """Handle linker script functions like DEFINED(), ORIGIN(), LENGTH(), ADDR(), SIZEOF()"""
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

        # Handle ADDR() and SIZEOF() functions (aliases for ORIGIN/LENGTH)
        expr = re.sub(
            r"ADDR\s*\(\s*([^)]+)\s*\)",
            self._replace_addr,
            expr)
        expr = re.sub(
            r"SIZEOF\s*\(\s*([^)]+)\s*\)",
            self._replace_sizeof,
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
        except (ExpressionEvaluationError, KeyError, ValueError):
            # If condition can't be evaluated, use false value for safety
            return false_value

    def _replace_origin(self, match: re.Match) -> str:
        """Replace ORIGIN() function with actual address"""
        region_name = match.group(1).strip()
        # Check if we have this region in our parsed data
        if region_name in self._memory_regions:
            return str(self._memory_regions[region_name].address)
        # Cannot resolve - raise error
        raise ExpressionEvaluationError(
            f"ORIGIN({region_name}): region '{region_name}' not found")

    def _replace_length(self, match: re.Match) -> str:
        """Replace LENGTH() function with actual size"""
        region_name = match.group(1).strip()
        # Check if we have this region in our parsed data
        if region_name in self._memory_regions:
            return str(self._memory_regions[region_name].limit_size)
        # Cannot resolve - raise error
        raise ExpressionEvaluationError(
            f"LENGTH({region_name}): region '{region_name}' not found")

    def _replace_addr(self, match: re.Match) -> str:
        """Replace ADDR() function with actual address (alias for ORIGIN)"""
        region_name = match.group(1).strip()
        # Check if we have this region in our parsed data
        if region_name in self._memory_regions:
            return str(self._memory_regions[region_name].address)
        # Cannot resolve - raise error
        raise ExpressionEvaluationError(
            f"ADDR({region_name}): region '{region_name}' not found")

    def _replace_sizeof(self, match: re.Match) -> str:
        """Replace SIZEOF() function with actual size (alias for LENGTH)"""
        region_name = match.group(1).strip()
        # Check if we have this region in our parsed data
        if region_name in self._memory_regions:
            return str(self._memory_regions[region_name].limit_size)
        # Cannot resolve - raise error
        raise ExpressionEvaluationError(
            f"SIZEOF({region_name}): region '{region_name}' not found")

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
                except (ExpressionEvaluationError, ValueError, ArithmeticError):
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
                # Use word boundary regex to avoid substring matches
                expr = re.sub(r'\b' + re.escape(var_name) + r'\b',
                              str(var_value), expr)

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


class VariableExtractor:  # pylint: disable=too-few-public-methods
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
            except (ExpressionEvaluationError, ValueError):
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
                except (ExpressionEvaluationError, ValueError):
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


class MemoryRegionBuilder:  # pylint: disable=too-few-public-methods
    """Builds memory region objects from parsed data"""

    def __init__(self, evaluator: ExpressionEvaluator):
        self.evaluator = evaluator

    def parse_memory_block(  # pylint: disable=too-many-branches
            self, memory_content: str, deferred_matches: Optional[List[tuple]] = None
    ) -> tuple:
        """Parse individual memory regions from MEMORY block content

        Returns:
            Tuple of (successfully_parsed_regions, failed_matches_for_retry)
        """
        memory_regions = {}
        failed_matches = []

        # Try standard format first (with attributes in parentheses)
        standard_pattern = (
            r"(\w+)\s*\(([^)]+)\)\s*:\s*(?:ORIGIN|origin|org)\s*=\s*([^,]+),\s*"
            r"(?:LENGTH|length|len)\s*=\s*([^,}]+?)(?=\s+\w+\s*[\(:]|$|\s*})")

        # Try ESP8266/alternative format (no attributes in parentheses)
        alt_pattern = (
            r"(\w+)\s*:\s*(?:ORIGIN|origin|org)\s*=\s*([^,]+),\s*"
            r"(?:LENGTH|length|len)\s*=\s*([^,}]+?)(?=\s+\w+\s*:|$|\s*})"
        )

        # Try no-comma format (whitespace separator, used in some Intel/embedded scripts)
        # Pattern must handle expressions with spaces (e.g., "ADDR(x) -
        # ADDR(y)")
        no_comma_pattern = (
            r"(\w+)\s*:\s*(?:ORIGIN|origin|org)\s*=\s*([^\s]+(?:\s*[-+*/]\s*[^\s]+)*)\s+"
            r"(?:LENGTH|length|len)\s*=\s*([^/\n]+?)(?=\s*(?://|$|\n|(?:\w+\s*:)))")

        # First try standard pattern
        for match in re.finditer(standard_pattern, memory_content):
            region = self._build_region_from_match(match, has_attributes=True)
            if region:
                memory_regions[region.name] = region
                # Update evaluator immediately so subsequent regions can
                # reference this one
                self.evaluator.set_memory_regions({
                    **self.evaluator.get_memory_regions(),
                    region.name: region
                })
            else:
                failed_matches.append((match, True))

        # If no regions found with standard pattern, try alternative (ESP8266)
        if not memory_regions and not failed_matches:
            for match in re.finditer(alt_pattern, memory_content):
                region = self._build_region_from_match(
                    match, has_attributes=False)
                if region:
                    memory_regions[region.name] = region
                    # Update evaluator immediately
                    self.evaluator.set_memory_regions({
                        **self.evaluator.get_memory_regions(),
                        region.name: region
                    })
                else:
                    failed_matches.append((match, False))

        # If still no regions found, try no-comma format
        if not memory_regions and not failed_matches:
            for match in re.finditer(no_comma_pattern, memory_content):
                region = self._build_region_from_match(
                    match, has_attributes=False)
                if region:
                    memory_regions[region.name] = region
                    # Update evaluator immediately
                    self.evaluator.set_memory_regions({
                        **self.evaluator.get_memory_regions(),
                        region.name: region
                    })
                else:
                    failed_matches.append((match, False))

        # Process deferred matches from previous iteration (after parsing new
        # ones)
        if deferred_matches:
            for match, has_attributes in deferred_matches:
                region = self._build_region_from_match(match, has_attributes)
                if region:
                    memory_regions[region.name] = region
                    # Update evaluator
                    self.evaluator.set_memory_regions({
                        **self.evaluator.get_memory_regions(),
                        region.name: region
                    })
                else:
                    # Still can't parse, defer again
                    failed_matches.append((match, has_attributes))

        return memory_regions, failed_matches

    def _build_region_from_match(
        self, match: re.Match, has_attributes: bool
    ) -> Optional[MemoryRegion]:
        """Build a memory region from a regex match"""
        # Save current state in case we need to restore
        saved_regions = self.evaluator.get_memory_regions()

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

            # For self-referential LENGTH expressions (e.g., ADDR(dccm) when parsing dccm),
            # temporarily add the region with a placeholder size so ADDR() can
            # resolve
            temp_region = MemoryRegion(
                name=name,
                attributes=attributes,
                address=origin,
                limit_size=0,  # Placeholder
            )
            self.evaluator.set_memory_regions({
                **self.evaluator.get_memory_regions(),
                name: temp_region
            })

            length = self._parse_size(length_str)

            return MemoryRegion(
                name=name,
                attributes=attributes,
                address=origin,
                limit_size=length,
            )

        except (ExpressionEvaluationError, ValueError, KeyError):
            # Restore previous state on failure
            self.evaluator.set_memory_regions(saved_regions)
            # Don't log here - region will be retried in subsequent iterations
            return None

    def _parse_address(self, addr_str: str) -> int:
        """Parse address string (supports hex, decimal, variables, and expressions)"""
        addr_str = addr_str.strip()

        # Evaluate as expression (handles variables and arithmetic)
        # This will raise ExpressionEvaluationError if it fails
        return self.evaluator.evaluate_expression(addr_str, set())

    def _parse_size(self, size_str: str) -> int:
        """Parse size string (supports K, M, G suffixes, variables, and expressions)"""
        size_str = size_str.strip()

        # Evaluate as expression (handles variables, arithmetic, and size
        # suffixes)
        return self.evaluator.evaluate_expression(size_str, set())


class LinkerScriptParser:  # pylint: disable=too-few-public-methods
    """Main parser orchestrator for linker script files"""

    def __init__(self, ld_scripts: List[str], elf_file: Optional[str] = None,
                 user_variables: Optional[Dict[str, Any]] = None):
        """Initialize the parser with linker script paths and optional ELF file

        Args:
            ld_scripts: List of linker script file paths
            elf_file: Optional path to ELF file for architecture detection
            user_variables: Optional dict of user-defined variables to use during parsing
                          (e.g., {'__micropy_flash_size__': '4096K', 'RAM_START': '0x20000000'})
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
                self.parsing_strategy = get_linker_parsing_strategy(
                    self.elf_info)
                logger.info("Detected architecture: %s, platform: %s",
                            self.elf_info.architecture.value,
                            self.elf_info.platform.value)
            else:
                logger.warning(
                    "Could not extract architecture info from ELF file: %s",
                    self.elf_file)

        # Initialize components
        self.evaluator = ExpressionEvaluator()
        self.variable_extractor = VariableExtractor(self.evaluator)
        self.region_builder = MemoryRegionBuilder(self.evaluator)

        # Apply architecture-specific default variables
        if self.parsing_strategy.get('default_variables'):
            self.evaluator.add_variables(
                self.parsing_strategy['default_variables'])

        # Apply user-defined variables (override architecture defaults)
        if user_variables:
            self.evaluator.add_variables(user_variables)

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

        # Merge extracted variables with existing default variables (preserve
        # architecture defaults)
        self.evaluator.add_variables(self.variable_extractor.variables)

    def _parse_all_memory_regions(self) -> Dict[str, MemoryRegion]:
        """Parse memory regions from all scripts with iterative dependency resolution"""
        memory_regions = {}
        deferred_matches = []

        # Parse regions iteratively to handle ORIGIN/LENGTH dependencies
        max_iterations = 3
        for iteration in range(max_iterations):
            old_count = len(memory_regions)
            new_deferred = []

            for script_path in self.ld_scripts:
                script_regions, script_deferred = self._parse_single_script(
                    script_path, deferred_matches if iteration > 0 else None
                )
                memory_regions.update(script_regions)
                new_deferred.extend(script_deferred)
                # Update evaluator with current regions for ORIGIN/LENGTH
                # resolution
                self.evaluator.set_memory_regions(memory_regions)

            # Update deferred list for next iteration
            deferred_matches = new_deferred

            # If no new regions were added and no deferred matches remain,
            # we're done
            if len(memory_regions) == old_count and not deferred_matches:
                break

        # Fail if any regions remain unresolved
        if deferred_matches:
            failed_regions = set()
            for match, _ in deferred_matches:
                region_name = match.group(1) if match.groups() else 'unknown'
                failed_regions.add(region_name)

            raise RegionParsingError(
                f"Could not resolve memory regions after {max_iterations} iterations: "
                f"{', '.join(sorted(failed_regions))}")

        return memory_regions

    def _parse_single_script(
            self, script_path: str, deferred_matches: Optional[List[tuple]] = None
    ) -> tuple:
        """Parse memory regions from a single linker script file

        Returns:
            Tuple of (parsed_regions, failed_matches)
        """
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
            return {}, []

        memory_content = memory_match.group(1)
        return self.region_builder.parse_memory_block(
            memory_content, deferred_matches)


# Convenience functions for backward compatibility
def parse_linker_scripts(
    ld_scripts: List[str], elf_file: Optional[str] = None
) -> Dict[str, Dict[str, Any]]:
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
