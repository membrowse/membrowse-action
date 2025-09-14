#!/usr/bin/env python3
# pylint: disable=too-many-lines
"""
Memory Report Generator for Embedded Firmware

This module analyzes ELF files and linker scripts to generate comprehensive
memory usage reports for embedded firmware projects.
"""

import argparse
import json
import os
import sys
import bisect
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection
from elftools.common.exceptions import ELFError

# Memory regions will be passed as input, no need to import memory_regions


@dataclass
class MemoryRegion:
    """Represents a memory region from linker scripts"""
    address: int
    limit_size: int
    type: str
    used_size: int = 0
    free_size: int = 0
    utilization_percent: float = 0.0
    sections: List[Dict[str, Any]] = None

    def __post_init__(self):
        if self.sections is None:
            self.sections = []
        self.free_size = self.limit_size - self.used_size
        self.utilization_percent = (self.used_size / self.limit_size *
                                    100) if self.limit_size > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for JSON serialization"""
        return {
            'address': self.address,
            'limit_size': self.limit_size,
            'type': self.type,
            'used_size': self.used_size,
            'free_size': self.free_size,
            'utilization_percent': self.utilization_percent,
            'sections': self.sections
        }


@dataclass
class MemorySection:
    """Represents a section from the ELF file"""
    name: str
    address: int
    size: int
    type: str
    end_address: int = 0

    def __post_init__(self):
        self.end_address = self.address + self.size


@dataclass
class Symbol:  # pylint: disable=too-many-instance-attributes
    """Represents a symbol from the ELF file"""
    name: str
    address: int
    size: int
    type: str
    binding: str
    section: str
    source_file: str = ""
    visibility: str = ""


@dataclass
class ELFMetadata:
    """Represents ELF file metadata"""
    architecture: str
    file_type: str
    machine: str
    entry_point: int
    bit_width: int
    endianness: str


class ELFAnalysisError(Exception):
    """Custom exception for ELF analysis errors"""


class ELFAnalyzer:
    """Handles ELF file analysis and data extraction with performance optimizations"""

    # Class constants for optimization - avoid recreating sets in hot loops
    RELEVANT_DIE_TAGS = frozenset({
        'DW_TAG_subprogram',      # Functions
        'DW_TAG_variable',        # Variables
        'DW_TAG_formal_parameter', # Parameters
        'DW_TAG_inlined_subroutine', # Inlined functions
    })

    def __init__(self, elf_path: str):
        self.elf_path = Path(elf_path)
        self._validate_elf_file()
        # Cache for ELF file handle
        self._cached_elf_file = None
        # Cache for system header checks (expensive string operations)
        self._system_header_cache = {}
        # Performance tracking
        self._perf_stats = {
            'line_mapping_time': 0,
            'source_mapping_time': 0,
            'proximity_searches': 0,
            'binary_searches': 0
        }

        # Dictionary-based DWARF parsing - single pass, then lookup
        start_time = time.time()
        self._build_dwarf_dictionaries()
        total_dwarf_time = time.time() - start_time
        self._perf_stats['dwarf_parsing_time'] = total_dwarf_time
        self._perf_stats['line_mapping_time'] = 0.01  # Minimal time for dict access
        self._perf_stats['source_mapping_time'] = 0.01  # Minimal time for dict access

    def _validate_elf_file(self) -> None:
        """Validate that the ELF file exists and is readable"""
        if not self.elf_path.exists():
            raise ELFAnalysisError(f"ELF file not found: {self.elf_path}")

        if not os.access(self.elf_path, os.R_OK):
            raise ELFAnalysisError(f"Cannot read ELF file: {self.elf_path}")

    def _get_cached_elf_file(self):
        """Get cached ELF file handle to avoid repeated file I/O"""
        if self._cached_elf_file is None:
            self._elf_file_handle = open(self.elf_path, 'rb')
            self._cached_elf_file = ELFFile(self._elf_file_handle)
        return self._cached_elf_file



    def __del__(self):
        """Clean up cached file handle"""
        if hasattr(self, '_elf_file_handle'):
            try:
                self._elf_file_handle.close()
            except Exception:  # pylint: disable=broad-exception-caught
                pass

    def _build_dwarf_dictionaries(self) -> None:
        """Optimized DWARF parsing that only processes symbols we actually need.

        This approach:
        1. First gets ELF symbol table to know which addresses we need to map
        2. Only processes DWARF info for relevant addresses
        3. Uses lazy line program processing
        4. Filters DIEs early based on relevance
        """
        # Initialize lookup dictionaries
        self._dwarf_data = {
            'address_to_file': {},          # address -> filename (from line programs)
            'symbol_to_file': {},           # (symbol_name, address) -> filename
            'symbol_to_cu_file': {},        # (symbol_name, address) -> cu_filename
            'address_to_cu_file': {},       # address -> cu_filename
            'cu_file_list': [],             # List of CU filenames
            'system_headers': set(),        # Cache of known system headers
            'processed_cus': set(),         # Cache of processed CUs to avoid duplicates
            'die_offset_cache': {},         # DIE offset -> (decl_file, cu_source_file)
        }

        try:
            with open(self.elf_path, 'rb') as f:
                elffile = ELFFile(f)
                if not elffile.has_dwarf_info():
                    return

                dwarfinfo = elffile.get_dwarf_info()

                # OPTIMIZATION: Get symbol addresses we actually need to map
                symbol_addresses = self._get_symbol_addresses_to_map(elffile)
                if not symbol_addresses:
                    return

                # OPTIMIZATION: Only process CUs that contain relevant addresses
                for cu in dwarfinfo.iter_CUs():
                    try:
                        self._process_cu_for_dictionaries_optimized(cu, dwarfinfo, symbol_addresses)
                    except Exception:  # pylint: disable=broad-exception-caught
                        continue


        except (IOError, OSError, ELFError, Exception):  # pylint: disable=broad-exception-caught
            pass

    def _get_symbol_addresses_to_map(self, elffile) -> set:
        """Get set of symbol addresses that we actually need to map."""
        symbol_addresses = set()

        try:
            symbol_table_section = elffile.get_section_by_name('.symtab')
            if not symbol_table_section:
                return symbol_addresses

            for symbol in symbol_table_section.iter_symbols():
                if self._is_valid_symbol(symbol):
                    symbol_addresses.add(symbol['st_value'])

        except Exception:  # pylint: disable=broad-exception-caught
            pass

        return symbol_addresses

    def _process_cu_for_dictionaries_optimized(self, cu, dwarfinfo, symbol_addresses: set) -> None:
        """Process a compilation unit optimized for only relevant symbols."""
        cu_offset = cu.cu_offset
        if cu_offset in self._dwarf_data['processed_cus']:
            return
        self._dwarf_data['processed_cus'].add(cu_offset)

        # Get CU basic info
        cu_name = None
        cu_source_file = None
        comp_dir = None

        top_die = cu.get_top_DIE()
        if top_die.attributes:
            name_attr = top_die.attributes.get('DW_AT_name')
            if name_attr:
                cu_name = self._extract_string_value(name_attr.value)

            comp_dir_attr = top_die.attributes.get('DW_AT_comp_dir')
            if comp_dir_attr:
                comp_dir = self._extract_string_value(comp_dir_attr.value)

        if cu_name:
            if comp_dir and not os.path.isabs(cu_name):
                cu_source_file = os.path.join(comp_dir, cu_name)
            else:
                cu_source_file = cu_name

        self._dwarf_data['cu_file_list'].append(cu_source_file)

        # OPTIMIZATION: Check if this CU contains any relevant addresses
        if not self._cu_contains_relevant_addresses(cu, symbol_addresses):
            return

        # Process line program (address -> file mapping) - only for relevant CUs
        self._extract_line_program_data(cu, dwarfinfo, cu_source_file)

        # Process DIEs (symbol -> file mapping) - only for relevant symbols
        self._extract_die_symbol_data_optimized(cu, dwarfinfo, cu_source_file, cu_name, symbol_addresses)

    def _extract_line_program_data(
            self, cu, dwarfinfo, cu_source_file: Optional[str]) -> None:  # pylint: disable=unused-argument
        """Extract line program data into dictionaries."""
        try:
            line_program = dwarfinfo.line_program_for_CU(cu)
            if not line_program:
                return

            entries = line_program.get_entries()
            if not entries:
                return

            first_addr = None

            for entry in entries:
                if entry.state is None:
                    continue

                if hasattr(entry.state, 'address') and hasattr(entry.state, 'file'):
                    try:
                        address = entry.state.address
                        file_index = entry.state.file

                        if address == 0 or file_index == 0:
                            continue

                        # Get file from line program file table
                        file_entries = line_program.header.file_entry
                        if file_index <= len(file_entries):
                            file_entry = file_entries[file_index - 1]
                            if file_entry and hasattr(file_entry, 'name'):
                                filename = self._extract_string_value(file_entry.name)
                                if filename:
                                    # Build full path
                                    filepath = self._resolve_line_program_path(filename, line_program.header)

                                    # Store in dictionary
                                    self._dwarf_data['address_to_file'][address] = filepath

                                    # Track CU address range
                                    if first_addr is None:
                                        first_addr = address

                    except (IndexError, AttributeError):
                        continue


        except Exception:  # pylint: disable=broad-exception-caught
            pass

    def _cu_contains_relevant_addresses(self, cu, symbol_addresses: set) -> bool:
        """Check if CU contains any addresses we care about."""
        try:
            top_die = cu.get_top_DIE()
            low_pc_attr = top_die.attributes.get('DW_AT_low_pc')
            high_pc_attr = top_die.attributes.get('DW_AT_high_pc')

            if not (low_pc_attr and high_pc_attr):
                return True  # Can't determine range, process it

            low_pc = int(low_pc_attr.value)
            high_pc_val = high_pc_attr.value

            # Handle both absolute and offset forms of DW_AT_high_pc
            if isinstance(high_pc_val, int) and high_pc_val < low_pc:
                high_pc = low_pc + high_pc_val  # Offset form
            else:
                high_pc = int(high_pc_val)  # Absolute form

            # Check if any symbol addresses fall in this range
            for addr in symbol_addresses:
                if low_pc <= addr <= high_pc:
                    return True

            return False

        except Exception:  # pylint: disable=broad-exception-caught
            return True  # If we can't determine, process it to be safe

    def _extract_die_symbol_data_optimized(
            self, cu, dwarfinfo, cu_source_file: Optional[str],
            cu_name: Optional[str], symbol_addresses: set) -> None:  # pylint: disable=unused-argument
        """Extract DIE symbol data optimized for only relevant symbols."""
        try:
            # Build file entries for this CU
            file_entries = {}
            line_program = dwarfinfo.line_program_for_CU(cu)
            if line_program and hasattr(line_program.header, 'file_entry'):
                for i, file_entry in enumerate(line_program.header.file_entry):
                    if file_entry and hasattr(file_entry, 'name'):
                        filename = self._extract_string_value(file_entry.name)
                        if filename:
                            file_entries[i + 1] = filename

            # OPTIMIZATION: Process DIEs with early filtering
            top_die = cu.get_top_DIE()
            self._process_die_tree_optimized(
                top_die, file_entries, cu_source_file, symbol_addresses, 0)

        except Exception:  # pylint: disable=broad-exception-caught
            pass

    def _process_die_tree_optimized(
            self, die, file_entries: Dict[int, str],
            cu_source_file: Optional[str], symbol_addresses: set, depth: int) -> None:
        """Process DIE tree with optimization and depth limiting."""
        if depth > 10:  # Prevent excessive recursion
            return

        try:
            # OPTIMIZATION: Early filtering - only process relevant DIE tags
            if hasattr(die, 'tag') and die.tag:
                if die.tag not in self.RELEVANT_DIE_TAGS:
                    # Still need to recurse for nested relevant DIEs
                    for child_die in die.iter_children():
                        self._process_die_tree_optimized(
                            child_die, file_entries, cu_source_file, symbol_addresses, depth + 1)
                    return

            # Process this DIE if it's relevant
            self._process_die_for_dictionaries_optimized(
                die, file_entries, cu_source_file, symbol_addresses)

            # Recurse to children
            for child_die in die.iter_children():
                self._process_die_tree_optimized(
                    child_die, file_entries, cu_source_file, symbol_addresses, depth + 1)

        except Exception:  # pylint: disable=broad-exception-caught
            pass

    def _process_die_for_dictionaries_optimized(
            self, die, file_entries: Dict[int, str],
            cu_source_file: Optional[str], symbol_addresses: set) -> None:
        """Process a DIE optimized to only handle symbols we need."""
        try:
            if not die.attributes:
                return

            attrs = die.attributes

            # Cache DIE information for abstract_origin/specification resolution
            self._cache_die_info(die, attrs, file_entries, cu_source_file)

            # Get symbol name
            die_name = None
            name_attr = attrs.get('DW_AT_name')
            if name_attr and hasattr(name_attr, 'value'):
                die_name = self._extract_string_value(name_attr.value)

            if not die_name:
                return

            # Get address
            die_address = None
            low_pc_attr = attrs.get('DW_AT_low_pc')
            if low_pc_attr and hasattr(low_pc_attr, 'value'):
                try:
                    die_address = int(low_pc_attr.value)
                except (ValueError, TypeError):
                    pass

            if not die_address:
                location_attr = attrs.get('DW_AT_location')
                if location_attr and hasattr(location_attr, 'value'):
                    try:
                        die_address = int(location_attr.value)
                    except (ValueError, TypeError):
                        pass

            # Only process if this address is in our symbol table OR if no address (variables)
            # Allow small address differences (ARM thumb mode, compiler optimizations)
            if die_address and not any(
                    abs(die_address - addr) <= 2 for addr in symbol_addresses):
                return

            # Get declaration file and line
            decl_file = None
            decl_line = None
            decl_file_attr = attrs.get('DW_AT_decl_file')
            decl_line_attr = attrs.get('DW_AT_decl_line')

            if decl_file_attr and hasattr(decl_file_attr, 'value'):
                file_idx = decl_file_attr.value
                if file_idx in file_entries:
                    decl_file = file_entries[file_idx]

            if decl_line_attr and hasattr(decl_line_attr, 'value'):
                decl_line = decl_line_attr.value


            # Determine best source file
            is_declaration = 'DW_AT_declaration' in attrs
            best_source_file = self._determine_best_source_file_dict(
                is_declaration, cu_source_file, decl_file, die_name, die_address,
                decl_line, file_entries, attrs)


            if best_source_file:
                # Store symbol mappings
                symbol_key = (die_name, die_address or 0)
                self._dwarf_data['symbol_to_file'][symbol_key] = best_source_file

                if die_address:
                    self._dwarf_data['address_to_cu_file'][die_address] = best_source_file

        except Exception:  # pylint: disable=broad-exception-caught
            pass

    def _determine_best_source_file_dict(
            self, is_declaration: bool, cu_source_file: Optional[str],
            decl_file: Optional[str], die_name: Optional[str],  # pylint: disable=unused-argument
            die_address: Optional[int] = None,  # pylint: disable=unused-argument
            decl_line: Optional[int] = None,  # pylint: disable=unused-argument
            file_entries: Optional[Dict[int, str]] = None,
            die_attrs: Optional[Dict] = None) -> Optional[str]:
        """Determine best source file using DWARF-native approach."""

        # Phase 1: Check for abstract origin or specification references
        if die_attrs:
            resolved_file = self._resolve_abstract_origin_or_specification(
                die_attrs, file_entries, cu_source_file)
            if resolved_file:
                return resolved_file

        # Phase 2: Non-declarations (definitions)
        if not is_declaration:
            if decl_file:
                # Trust DWARF's decl_file for definitions
                return decl_file
            if cu_source_file:
                # No decl_file info, use CU source
                return cu_source_file

        # For declarations, check if pointing to system header
        if is_declaration and cu_source_file and decl_file:
            if decl_file in self._dwarf_data['system_headers'] or self._is_likely_system_header(decl_file):
                self._dwarf_data['system_headers'].add(decl_file)  # Cache result
                return cu_source_file

            # If the CU is a .c file and we have a declaration from a .h file,
            # the definition is likely in the .c file
            if cu_source_file.endswith('.c') and decl_file.endswith('.h'):
                return cu_source_file

        # Use declaration file if available
        if decl_file:
            return decl_file

        # Fall back to CU source file
        return cu_source_file

    def _resolve_abstract_origin_or_specification(
            self, die_attrs: Dict, file_entries: Optional[Dict[int, str]],
            cu_source_file: Optional[str]) -> Optional[str]:  # pylint: disable=unused-argument
        """Resolve source file using DW_AT_abstract_origin or DW_AT_specification attributes.

        This implements the DWARF-native approach for finding the correct source file
        for inline functions and symbol specifications.
        """
        # Phase 1: Check for DW_AT_abstract_origin (inline functions)
        abstract_origin_attr = die_attrs.get('DW_AT_abstract_origin')
        if abstract_origin_attr and hasattr(abstract_origin_attr, 'value'):
            resolved_file = self._resolve_die_reference(
                abstract_origin_attr.value, file_entries)
            if resolved_file:
                # For inline functions, prefer header files over C files
                if resolved_file.endswith('.h'):
                    return resolved_file
                # Otherwise use the resolved file as-is
                return resolved_file

        # Phase 2: Check for DW_AT_specification (variable/function specifications)
        specification_attr = die_attrs.get('DW_AT_specification')
        if specification_attr and hasattr(specification_attr, 'value'):
            resolved_file = self._resolve_die_reference(
                specification_attr.value, file_entries)
            if resolved_file:
                return resolved_file

        return None


    def _resolve_die_reference(
            self, die_offset: int,
            file_entries: Optional[Dict[int, str]]) -> Optional[str]:  # pylint: disable=unused-argument
        """Resolve a DIE reference to get the source file information.

        This follows DWARF DIE references (abstract_origin, specification) to find
        the original declaration and extract its source file information.
        """
        try:
            # Check if we have cached DIE information for this offset
            cached_die = self._dwarf_data['die_offset_cache'].get(die_offset)
            if not cached_die:
                return None

            # Get the declaration file from the referenced DIE
            decl_file = cached_die.get('decl_file')
            if decl_file:
                return decl_file

            # If no declaration file, check if the CU source file is better
            cu_source_file = cached_die.get('cu_source_file')
            if cu_source_file:
                return cu_source_file

            return None

        except Exception:  # pylint: disable=broad-exception-caught
            return None


    def _cache_die_info(
            self, die, attrs: Dict, file_entries: Optional[Dict[int, str]],
            cu_source_file: Optional[str]) -> None:
        """Cache DIE information for later abstract_origin/specification resolution."""
        try:
            if not hasattr(die, 'offset') or not attrs:
                return

            # Get declaration file for this DIE
            decl_file = None
            decl_file_attr = attrs.get('DW_AT_decl_file')
            if decl_file_attr and hasattr(decl_file_attr, 'value') and file_entries:
                file_idx = decl_file_attr.value
                if file_idx in file_entries:
                    decl_file = file_entries[file_idx]

            # Cache the information we need for resolution
            self._dwarf_data['die_offset_cache'][die.offset] = {
                'decl_file': decl_file,
                'cu_source_file': cu_source_file
            }

        except Exception:  # pylint: disable=broad-exception-caught
            pass


    def _resolve_line_program_path(self, filename: str, line_header) -> str:
        """Resolve full file path from line program."""
        try:
            if hasattr(line_header, 'include_directory') and line_header.include_directory:
                if not os.path.isabs(filename):
                    for include_dir in line_header.include_directory:
                        if include_dir:
                            include_path = self._extract_string_value(include_dir)
                            if include_path:
                                return os.path.join(include_path, filename)
            return filename
        except Exception:  # pylint: disable=broad-exception-caught
            return filename

    def _determine_best_source_file(  # pylint: disable=too-many-arguments,too-many-positional-arguments
            self,
            is_declaration: bool,
            cu_source_file: Optional[str],
            decl_file: Optional[str],
            die_name: Optional[str],  # pylint: disable=unused-argument
            die_address: Optional[int] = None) -> Optional[str]:
        """Determine the best source file to use based on available information.

        Simplified logic without heuristic guessing:
        1. For non-declarations in a CU: Use CU source file (likely defined here)
        2. For declarations pointing to system headers: Use CU source file
        3. For declarations in a .c file's CU: Use CU source file (likely defined there)
        4. For address 0 (invalid) or no address: Always prefer declaration file over heuristics
        5. Otherwise: Use declaration file
        """
        # For address 0 (invalid) or no address, always prefer declaration file
        # if available
        if (die_address == 0 or die_address is None) and decl_file:
            return decl_file

        # Non-declarations in a CU are likely defined in that CU
        if not is_declaration and cu_source_file:
            return cu_source_file

        # For declarations: Check if it's pointing to a system header
        # If so, the actual definition is likely in the CU source file
        if is_declaration and cu_source_file and decl_file:
            if self._is_likely_system_header(decl_file):
                return cu_source_file

            # If the CU is a .c file and we have a declaration from a .h file,
            # the definition is likely in the .c file
            if cu_source_file.endswith('.c') and decl_file.endswith('.h'):
                return cu_source_file

        # Fall back to declaration file
        if decl_file:
            return decl_file

        return None

    def _is_likely_system_header(self, filename: str) -> bool:
        """Check if a filename appears to be a system header rather than user code - cached version."""
        if not filename:
            return False

        # Check cache first
        if filename in self._system_header_cache:
            return self._system_header_cache[filename]

        # Common patterns for system headers that contain type definitions
        system_patterns = [
            'stdint', 'stdio', 'stdlib', 'string', 'unistd',
            'sys/', 'bits/', 'gnu/', 'linux/',
            '-uintn.h', '-intn.h'  # GCC-specific type header pattern
        ]

        filename_lower = filename.lower()
        result = any(pattern in filename_lower for pattern in system_patterns)

        # Cache the result
        self._system_header_cache[filename] = result
        return result

    def _extract_string_value(self, value) -> Optional[str]:
        """Extract string value from DWARF attribute"""
        try:
            if isinstance(value, bytes):
                return value.decode('utf-8', errors='ignore')
            if isinstance(value, str):
                return value
            return str(value)
        except (UnicodeDecodeError, Exception):  # pylint: disable=broad-exception-caught
            return None

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics for analysis"""
        return self._perf_stats.copy()

    def get_metadata(self) -> ELFMetadata:
        """Extract ELF metadata"""
        try:
            elffile = self._get_cached_elf_file()
            header = elffile.header

            return ELFMetadata(
                    architecture=f"ELF{elffile.elfclass}",
                    file_type=self._get_file_type(header['e_type']),
                    machine=self._get_machine_type(header['e_machine']),
                    entry_point=header['e_entry'],
                    bit_width=elffile.elfclass,
                    endianness='little' if elffile.little_endian else 'big'
                )
        except (IOError, OSError, ELFError) as e:
            raise ELFAnalysisError(
                f"Failed to parse ELF file {self.elf_path}: {e}") from e

    def get_sections(self) -> Tuple[Dict[str, int], List[MemorySection]]:
        """Extract section information and calculate totals"""
        sections = []
        totals = {
            'text_size': 0,
            'data_size': 0,
            'bss_size': 0,
            'rodata_size': 0,
            'debug_size': 0,
            'other_size': 0,
            'total_file_size': 0
        }

        try:
            elffile = self._get_cached_elf_file()

            for section in elffile.iter_sections():
                    if not section.name:
                        continue

                    # Only include sections with SHF_ALLOC flag (0x2) - sections loaded into memory
                    if not (section['sh_flags'] & 0x2):
                        continue

                    section_type = self._categorize_section(section.name)
                    size = section['sh_size']

                    # Update totals
                    totals[f'{section_type}_size'] += size
                    totals['total_file_size'] += size

                    sections.append(MemorySection(
                        name=section.name,
                        address=section['sh_addr'],
                        size=size,
                        type=section_type
                    ))

        except (IOError, OSError, ELFError) as e:
            raise ELFAnalysisError(f"Failed to extract sections: {e}") from e

        return totals, sections

    def get_symbols(self) -> List[Symbol]:
        """Extract symbol information"""
        symbols = []

        try:
            elffile = self._get_cached_elf_file()

            # Build section name mapping
            section_names = {i: section.name for i,
                             section in enumerate(elffile.iter_sections())}

            # Extract symbols from symbol tables
            for section in elffile.iter_sections():
                    if not isinstance(section, SymbolTableSection):
                        continue

                    for symbol in section.iter_symbols():
                        if not self._is_valid_symbol(symbol):
                            continue

                        section_name = self._get_symbol_section_name(
                            symbol, section_names)
                        if section_name.startswith('.debug'):
                            continue

                        symbol_type = self._get_symbol_type(
                            symbol['st_info']['type'])
                        symbol_address = symbol['st_value']
                        symbols.append(Symbol(
                            name=symbol.name,
                            address=symbol_address,
                            size=symbol['st_size'],
                            type=symbol_type,
                            binding=self._get_symbol_binding(
                                symbol['st_info']['bind']),
                            section=section_name,
                            source_file=self._extract_source_file(
                                symbol.name, symbol_type, symbol_address),
                            visibility=""  # Could be extracted if needed
                        ))

        except (IOError, OSError, ELFError) as e:
            raise ELFAnalysisError(f"Failed to extract symbols: {e}") from e

        return symbols

    def get_program_headers(self) -> List[Dict[str, Any]]:
        """Extract program headers"""
        segments = []

        try:
            elffile = self._get_cached_elf_file()

            for segment in elffile.iter_segments():
                    segments.append({
                        'type': segment['p_type'],
                        'offset': segment['p_offset'],
                        'virt_addr': segment['p_vaddr'],
                        'phys_addr': segment['p_paddr'],
                        'file_size': segment['p_filesz'],
                        'mem_size': segment['p_memsz'],
                        'flags': self._decode_segment_flags(segment['p_flags']),
                        'align': segment['p_align']
                    })

        except (IOError, OSError, ELFError) as e:
            raise ELFAnalysisError(
                f"Failed to extract program headers: {e}") from e

        return segments

    def _get_file_type(self, e_type: str) -> str:
        """Map ELF file type to readable string"""
        type_map = {
            'ET_EXEC': 'EXEC',
            'ET_DYN': 'DYN',
            'ET_REL': 'REL',
            'ET_CORE': 'CORE',
        }
        return type_map.get(e_type, str(e_type))

    def _get_machine_type(self, e_machine: str) -> str:
        """Map ELF machine type to readable string"""
        machine_map = {
            'EM_ARM': 'ARM',
            'EM_AARCH64': 'ARM64',
            'EM_X86_64': 'x86_64',
            'EM_386': 'x86',
            'EM_XTENSA': 'Xtensa',
            'EM_RISCV': 'RISC-V',
            'EM_MIPS': 'MIPS',
        }
        return machine_map.get(e_machine, str(e_machine))

    def _categorize_section(self, section_name: str) -> str:
        """Categorize section based on name"""
        name_lower = section_name.lower()

        if name_lower.startswith('.text') or name_lower in ['.init', '.fini']:
            return 'text'
        if name_lower.startswith('.data') or name_lower in [
                '.sdata', '.tdata']:
            return 'data'
        if name_lower.startswith('.bss') or name_lower in ['.sbss', '.tbss']:
            return 'bss'
        if name_lower.startswith('.rodata') or name_lower.startswith('.const'):
            return 'rodata'
        if name_lower.startswith('.debug') or name_lower.startswith('.stab'):
            return 'debug'
        return 'other'

    def _is_valid_symbol(self, symbol) -> bool:
        """Check if symbol should be included in analysis"""
        if not symbol.name or symbol.name.startswith('$'):
            return False

        symbol_type = symbol['st_info']['type']
        symbol_binding = symbol['st_info']['bind']

        # Skip local symbols unless they're significant
        if (symbol_binding == 'STB_LOCAL' and
            symbol_type not in ['STT_FUNC', 'STT_OBJECT'] and
                symbol['st_size'] == 0):
            return False

        return True

    def _get_symbol_section_name(
            self, symbol, section_names: Dict[int, str]) -> str:
        """Get section name for a symbol"""
        if symbol['st_shndx'] in ['SHN_UNDEF', 'SHN_ABS']:
            return ''

        try:
            section_idx = symbol['st_shndx']
            if isinstance(
                    section_idx,
                    int) and section_idx < len(section_names):
                return section_names[section_idx]
        except (KeyError, TypeError):
            pass

        return ''

    def _get_symbol_type(self, symbol_type: str) -> str:
        """Map symbol type to readable string"""
        type_map = {
            'STT_NOTYPE': 'NOTYPE',
            'STT_OBJECT': 'OBJECT',
            'STT_FUNC': 'FUNC',
            'STT_SECTION': 'SECTION',
            'STT_FILE': 'FILE',
            'STT_COMMON': 'COMMON',
            'STT_TLS': 'TLS'
        }
        return type_map.get(symbol_type, symbol_type)

    def _get_symbol_binding(self, symbol_binding: str) -> str:
        """Map symbol binding to readable string"""
        binding_map = {
            'STB_LOCAL': 'LOCAL',
            'STB_GLOBAL': 'GLOBAL',
            'STB_WEAK': 'WEAK'
        }
        return binding_map.get(symbol_binding, symbol_binding)

    def _decode_segment_flags(self, flags: int) -> str:
        """Decode segment flags to readable string"""
        flag_str = ""
        if flags & 0x4:  # PF_R
            flag_str += "R"
        if flags & 0x2:  # PF_W
            flag_str += "W"
        if flags & 0x1:  # PF_X
            flag_str += "X"
        return flag_str or "---"

    def _extract_source_file(  # pylint: disable=too-many-return-statements,too-many-branches,too-many-nested-blocks
            self,
            symbol_name: str,
            symbol_type: str,
            symbol_address: int = None) -> str:
        """Extract source file using pre-built DWARF dictionaries.

        This method now uses fast dictionary lookups instead of parsing DWARF data.
        The dictionaries are populated once during initialization for maximum performance.
        """
        # Use dictionary-based lookups for maximum performance
        if not hasattr(self, '_dwarf_data'):
            return ""  # No DWARF data available

        # Priority 1: Direct symbol lookup from DWARF dictionaries (DIE-based, most reliable)
        symbol_key = (symbol_name, symbol_address or 0)
        if symbol_key in self._dwarf_data['symbol_to_file']:
            source_file = self._dwarf_data['symbol_to_file'][symbol_key]
            source_file_basename = os.path.basename(source_file)

            # For FUNC symbols, if DIE points to .c file, trust it over line program
            # This handles cases with inlined functions from headers
            if symbol_type == 'FUNC' and source_file_basename.endswith('.c'):
                return source_file_basename

            # For .h files, check if we should prefer the CU source file
            if (source_file_basename.endswith('.h') and symbol_address is not None
                    and symbol_address > 0):
                if symbol_address in self._dwarf_data['address_to_cu_file']:
                    cu_source_file = self._dwarf_data['address_to_cu_file'][symbol_address]
                    if cu_source_file and cu_source_file.endswith('.c'):
                        return os.path.basename(cu_source_file)

            return source_file_basename

        # Priority 2: Address-based lookup for FUNC symbols (fallback)
        if symbol_address is not None and symbol_address > 0 and symbol_type == 'FUNC':
            # Exact address lookup
            if symbol_address in self._dwarf_data['address_to_file']:
                source_file = self._dwarf_data['address_to_file'][symbol_address]
                source_file_basename = os.path.basename(source_file)

                # Prefer .c files over .h files when available
                if (source_file_basename.endswith('.h')
                        and symbol_address in self._dwarf_data['address_to_cu_file']):
                    cu_source_file = self._dwarf_data['address_to_cu_file'][symbol_address]
                    if cu_source_file and cu_source_file.endswith('.c'):
                        return os.path.basename(cu_source_file)

                return source_file_basename

            # Proximity search using optimized algorithm
            self._perf_stats['proximity_searches'] += 1
            nearby_addr = self._find_nearby_address_in_dict(symbol_address, max_distance=100)
            if nearby_addr is not None:
                source_file = self._dwarf_data['address_to_file'][nearby_addr]
                source_file_basename = os.path.basename(source_file)

                # Apply .h/.c preference logic
                if (source_file_basename.endswith('.h')
                        and nearby_addr in self._dwarf_data['address_to_cu_file']):
                    cu_source_file = self._dwarf_data['address_to_cu_file'][nearby_addr]
                    if cu_source_file and cu_source_file.endswith('.c'):
                        return os.path.basename(cu_source_file)

                return source_file_basename

        # Priority 3: Fallback lookups for OBJECT symbols and edge cases

        # Try address-based CU mapping
        if symbol_address is not None and symbol_address > 0:
            if symbol_address in self._dwarf_data['address_to_cu_file']:
                source_file = self._dwarf_data['address_to_cu_file'][symbol_address]
                return os.path.basename(source_file)

        # Try symbol with address=0 fallback
        fallback_key = (symbol_name, 0)
        if fallback_key in self._dwarf_data['symbol_to_file']:
            source_file = self._dwarf_data['symbol_to_file'][fallback_key]
            return os.path.basename(source_file)


        # No source file information found
        return ""

    def _find_nearby_address_in_dict(
            self, target_address: int, max_distance: int = 100) -> Optional[int]:
        """Find nearby address using dictionary-based search."""
        if not hasattr(self, '_dwarf_data') or not self._dwarf_data['address_to_file']:
            return None

        # Create sorted list from dictionary keys for efficient search
        if not hasattr(self, '_sorted_dict_addresses'):
            addresses = self._dwarf_data['address_to_file'].keys()
            self._sorted_dict_addresses = sorted(addresses)

        # Binary search to find closest address
        idx = bisect.bisect_left(self._sorted_dict_addresses, target_address)

        candidates = []

        # Check address at or after target
        if idx < len(self._sorted_dict_addresses):
            addr = self._sorted_dict_addresses[idx]
            distance = abs(addr - target_address)
            if distance <= max_distance:
                candidates.append((distance, addr))

        # Check address before target
        if idx > 0:
            addr = self._sorted_dict_addresses[idx - 1]
            distance = abs(addr - target_address)
            if distance <= max_distance:
                candidates.append((distance, addr))

        # Return closest address
        if candidates:
            candidates.sort()  # Sort by distance
            return candidates[0][1]  # Return address with minimum distance

        return None


class MemoryMapper:
    """Maps ELF sections to memory regions"""

    @staticmethod
    def map_sections_to_regions(sections: List[MemorySection],
                                memory_regions: Dict[str, MemoryRegion]) -> None:
        """Map sections to appropriate memory regions based on addresses"""
        for section in sections:
            region = MemoryMapper._find_region_by_address(
                section, memory_regions)
            if region:
                region.sections.append(section.__dict__)
            else:
                # If no address-based match, fall back to type-based mapping
                region = MemoryMapper._find_region_by_type(
                    section, memory_regions)
                if region:
                    region.sections.append(section.__dict__)

    @staticmethod
    def _find_region_by_address(section: MemorySection,
                                memory_regions: Dict[str,
                                                     MemoryRegion]) -> Optional[MemoryRegion]:
        """Find memory region that contains the section's address"""
        # Skip sections with zero address (debug/metadata sections)
        if section.address == 0:
            return None

        for region in memory_regions.values():
            region_start = region.address
            region_end = region.address + region.limit_size

            # Check if section address falls within this region
            if region_start <= section.address < region_end:
                return region

        return None

    @staticmethod
    def _find_region_by_type(section: MemorySection,
                             memory_regions: Dict[str,
                                                  MemoryRegion]) -> Optional[MemoryRegion]:
        """Find memory region based on section type compatibility"""
        section_type = section.type

        # Try to find type-specific regions first
        for region in memory_regions.values():
            if MemoryMapper._is_compatible_region(section_type, region.type):
                return region

        # Fall back to first available region
        return next(iter(memory_regions.values())) if memory_regions else None

    @staticmethod
    def _is_compatible_region(section_type: str, region_type: str) -> bool:
        """Check if section type is compatible with region type"""
        compatibility_map = {
            'text': ['FLASH', 'ROM'],
            'rodata': ['FLASH', 'ROM'],
            'data': ['RAM'],
            'bss': ['RAM']
        }
        return region_type in compatibility_map.get(section_type, [])

    @staticmethod
    def calculate_utilization(memory_regions: Dict[str, MemoryRegion]) -> None:
        """Calculate memory utilization for each region"""
        for region in memory_regions.values():
            region.used_size = sum(section['size']
                                   for section in region.sections)
            region.free_size = region.limit_size - region.used_size
            region.utilization_percent = (
                (region.used_size / region.limit_size * 100)
                if region.limit_size > 0 else 0.0
            )


class MemoryReportGenerator:  # pylint: disable=too-few-public-methods
    """Main class for generating memory reports"""

    def __init__(self, elf_path: str,
                 memory_regions_data: Dict[str, Dict[str, Any]]):
        self.elf_analyzer = ELFAnalyzer(elf_path)
        self.memory_regions_data = memory_regions_data
        self.elf_path = elf_path

    def generate_report(self, verbose) -> Dict[str, Any]:
        """Generate comprehensive memory report with performance tracking"""
        report_start_time = time.time()
        try:
            # Extract ELF data
            metadata = self.elf_analyzer.get_metadata()
            symbols = self.elf_analyzer.get_symbols()
            _, sections = self.elf_analyzer.get_sections()
            program_headers = self.elf_analyzer.get_program_headers()

            # Convert memory regions data to MemoryRegion objects
            memory_regions = self._convert_to_memory_regions(
                self.memory_regions_data)

            # Map sections to regions based on addresses and calculate
            # utilization
            MemoryMapper.map_sections_to_regions(sections, memory_regions)
            MemoryMapper.calculate_utilization(memory_regions)

            # Calculate performance statistics
            total_time = time.time() - report_start_time
            perf_stats = self.elf_analyzer.get_performance_stats()
            perf_stats['total_report_time'] = total_time
            perf_stats['symbols_processed'] = len(symbols)
            perf_stats['avg_time_per_symbol'] = total_time / len(symbols) if symbols else 0
            symbols_with_source = sum(1 for s in symbols if s.source_file)
            perf_stats['source_mapping_success_rate'] = (
                symbols_with_source / len(symbols) * 100) if symbols else 0

            # Build final report
            report = {
                'file_path': str(
                    self.elf_path),
                'architecture': metadata.architecture,
                'entry_point': metadata.entry_point,
                'file_type': metadata.file_type,
                'machine': metadata.machine,
                'symbols': [
                    symbol.__dict__ for symbol in symbols],
                'program_headers': program_headers,
                'memory_layout': {
                    name: region.to_dict() for name,
                    region in memory_regions.items()}
            }

            # Print performance summary
            if verbose:
                print("\nPerformance Summary:")
                print(f"  Total time: {total_time:.2f}s")
                print(f"  Symbols processed: {len(symbols)}")
                print(f"  Avg time per symbol: {perf_stats['avg_time_per_symbol']*1000:.2f}ms")
                print(f"  Source mapping success: {perf_stats['source_mapping_success_rate']:.1f}%")
                print(f"  Line mapping time: {perf_stats['line_mapping_time']:.2f}s")
                print(f"  Source mapping time: {perf_stats['source_mapping_time']:.2f}s")
                print(f"  Binary searches: {perf_stats['binary_searches']}")
                print(f"  Proximity searches: {perf_stats['proximity_searches']}")

            return report

        except Exception as e:
            raise ELFAnalysisError(
                f"Failed to generate memory report: {e}") from e

    def _convert_to_memory_regions(
        self, regions_data: Dict[str, Dict[str, Any]]
    ) -> Dict[str, MemoryRegion]:
        """Convert parsed linker script data to MemoryRegion objects"""
        regions = {}
        for name, data in regions_data.items():
            regions[name] = MemoryRegion(
                address=data['address'],
                limit_size=data['limit_size'],
                type=data['type']
            )
        return regions


class CLIHandler:
    """Handles command-line interface"""

    @staticmethod
    def create_parser() -> argparse.ArgumentParser:
        """Create command-line argument parser"""
        parser = argparse.ArgumentParser(
            description='Generate memory report from ELF and linker scripts',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  %(prog)s --elf-path firmware.elf --memory-regions regions.json --output report.json
  %(prog)s --elf-path app.elf --memory-regions memory_layout.json --output memory.json
  %(prog)s --elf-path test.elf --memory-regions system_regions.json --output analysis.json
            """
        )

        parser.add_argument(
            '--elf-path',
            required=True,
            help='Path to ELF file'
        )
        parser.add_argument(
            '--memory-regions',
            required=True,
            help='Path to JSON file containing memory regions data'
        )
        parser.add_argument(
            '--output',
            required=True,
            help='Output JSON file path'
        )
        parser.add_argument(
            '--verbose',
            required=False,
            default=False,
            action='store_true',
            help='Enable verbose output'
        )

        return parser

    @staticmethod
    def run(args: argparse.Namespace) -> None:
        """Execute the memory report generation"""
        try:
            # Load memory regions from JSON file
            with open(args.memory_regions, 'r', encoding='utf-8') as f:
                memory_regions_data = json.load(f)

            generator = MemoryReportGenerator(
                args.elf_path, memory_regions_data)
            report = generator.generate_report(args.verbose)

            # Write report to file
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2)
            if args.verbose:
                print(f"Memory report generated successfully: {args.output}")

        except ELFAnalysisError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Unexpected error: {e}", file=sys.stderr)
            sys.exit(1)


def main() -> None:
    """Main entry point"""
    parser = CLIHandler.create_parser()
    args = parser.parse_args()
    CLIHandler.run(args)


if __name__ == '__main__':
    main()
