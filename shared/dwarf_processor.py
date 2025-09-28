#!/usr/bin/env python3
"""
DWARF debug information processing for source file mapping.

This module handles the parsing and processing of DWARF debug information
to map symbols to their source files with intelligent optimizations.
"""

import os
import logging
from typing import Dict, List, Optional, Any, Tuple
from elftools.common.exceptions import ELFError
from .exceptions import DWARFParsingError

# Configure logger
logger = logging.getLogger(__name__)

# Constants for magic values
MAX_ADDRESS = 0xFFFFFFFF  # Default max address when CU has no range
THUMB_MODE_TOLERANCE = 2   # ARM thumb mode address difference tolerance
MAX_DIE_RECURSION = 10     # Maximum recursion depth for DIE tree traversal

class DWARFProcessor:
    """Handles DWARF debug information processing for source file mapping.

    This processor extracts source file mappings from DWARF debug information
    using two complementary approaches:
    1. Line program data: Maps instruction addresses to source files
    2. DIE (Debug Information Entry) data: Maps symbol definitions to source files

    The processor optimizes performance by only processing compilation units (CUs)
    that contain symbols we actually need to map.
    """

    def __init__(self, elffile, symbol_addresses: set):
        """Initialize DWARF processor with ELF file and target addresses.

        Args:
            elffile: Open ELF file object from pyelftools
            symbol_addresses: Set of symbol addresses we need to map to source files
        """
        self.elffile = elffile
        self.symbol_addresses = symbol_addresses
        # Only keep actively used data structures
        self.dwarf_data = {
            'address_to_file': {},          # address -> filename (from line programs)
            'symbol_to_file': {},           # (symbol_name, address) -> filename
            'address_to_cu_file': {},       # address -> cu_filename
            'processed_cus': set(),         # Cache of processed CUs to avoid duplicates
            'static_symbol_mappings': [],   # List of (symbol_name, cu_source_file, decl_file) for static vars
        }

    def process_dwarf_info(self) -> Dict[str, Any]:
        """Process DWARF information and return symbol mapping data.

        Returns:
            Dictionary containing address and symbol to source file mappings

        Raises:
            DWARFParsingError: If ELF file cannot be read or has invalid format
        """
        if not self.elffile.has_dwarf_info():
            logger.debug("No DWARF debug information found in ELF file")
            return self.dwarf_data

        try:
            dwarfinfo = self.elffile.get_dwarf_info()

            # Build CU address range index
            cu_address_index = self._build_cu_address_index(dwarfinfo)
            logger.debug(f"Built CU index with {len(cu_address_index)} compilation units")

            # Only process CUs that contain relevant addresses for performance optimization
            # This avoids processing all CUs when we only need specific symbols
            relevant_cus = self._find_relevant_cus(cu_address_index)
            logger.debug(f"Found {len(relevant_cus)} relevant CUs out of {len(cu_address_index)} total")

            for cu in relevant_cus:
                try:
                    self._process_cu(cu, dwarfinfo)
                except Exception as e:
                    logger.warning(f"Failed to process CU at offset {cu.cu_offset}: {e}")
                    continue

        except (IOError, OSError) as e:
            logger.error(f"Failed to read ELF file for DWARF parsing: {e}")
            raise DWARFParsingError(f"Failed to read ELF file for DWARF parsing: {e}") from e
        except ELFError as e:
            logger.error(f"Invalid ELF file format: {e}")
            raise DWARFParsingError(f"Invalid ELF file format: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error during DWARF parsing: {e}")
            raise DWARFParsingError(f"Unexpected error during DWARF parsing: {e}") from e

        return self.dwarf_data

    def _extract_cu_address_range(self, cu) -> Tuple[int, int]:
        """Extract address range from a compilation unit.

        Args:
            cu: Compilation unit to extract range from

        Returns:
            Tuple of (low_pc, high_pc) addresses

        Note:
            In DWARF 4+, high_pc can be either:
            - An absolute address (DWARF 2/3)
            - An offset from low_pc (DWARF 4+) when value < low_pc
            This is detected by checking if high_pc < low_pc.
        """
        try:
            top_die = cu.get_top_DIE()
            if not top_die.attributes:
                return (0, MAX_ADDRESS)

            low_pc_attr = top_die.attributes.get('DW_AT_low_pc')
            high_pc_attr = top_die.attributes.get('DW_AT_high_pc')

            # If CU doesn't have address range, use full address space
            # This ensures we don't miss symbols in CUs without explicit ranges
            if not (low_pc_attr and high_pc_attr):
                logger.debug(f"CU at offset {cu.cu_offset} has no address range, using full range")
                return (0, MAX_ADDRESS)

            low_pc = int(low_pc_attr.value)
            high_pc_val = high_pc_attr.value

            # Handle DWARF 4+ where high_pc can be an offset from low_pc
            # This is indicated when high_pc value is less than low_pc
            if isinstance(high_pc_val, int) and high_pc_val < low_pc:
                high_pc = low_pc + high_pc_val
            else:
                high_pc = int(high_pc_val)

            return (low_pc, high_pc)

        except (ValueError, TypeError) as e:
            logger.debug(f"Failed to extract address range from CU: {e}")
            return (0, MAX_ADDRESS)

    def _build_cu_address_index(self, dwarfinfo) -> List[Tuple[int, int, Any]]:
        """Build an index of compilation unit address ranges for fast lookup.

        Args:
            dwarfinfo: DWARF debug information object

        Returns:
            Sorted list of (low_pc, high_pc, cu) tuples for binary search
        """
        cu_index = []

        for cu in dwarfinfo.iter_CUs():
            low_pc, high_pc = self._extract_cu_address_range(cu)
            cu_index.append((low_pc, high_pc, cu))

        cu_index.sort(key=lambda x: x[0])
        return cu_index

    def _find_relevant_cus(self, cu_index: List[Tuple[int, int, Any]]) -> List[Any]:
        """Find compilation units that contain any of our target symbol addresses.

        This optimization is crucial for performance - we only process CUs that
        contain symbols we actually need to map, avoiding unnecessary processing
        of unrelated compilation units.

        Args:
            cu_index: Sorted list of CU address ranges

        Returns:
            List of CUs that contain at least one target symbol address
        """
        relevant_cus = []
        symbol_addr_list = sorted(self.symbol_addresses)

        for symbol_addr in symbol_addr_list:
            for start_addr, end_addr, cu in cu_index:
                if start_addr <= symbol_addr <= end_addr:
                    if cu not in relevant_cus:
                        relevant_cus.append(cu)
                elif start_addr > symbol_addr:
                    # Since cu_index is sorted, no need to check further
                    break

        return relevant_cus

    def _process_cu(self, cu, dwarfinfo):
        """Process a single compilation unit to extract source mappings.

        Args:
            cu: Compilation unit to process
            dwarfinfo: DWARF debug information object
        """
        cu_offset = cu.cu_offset
        if cu_offset in self.dwarf_data['processed_cus']:
            return
        self.dwarf_data['processed_cus'].add(cu_offset)

        # Get CU address range using the shared extraction method
        cu_low_pc, cu_high_pc = self._extract_cu_address_range(cu)
        top_die = cu.get_top_DIE()

        # Get CU basic info
        cu_name = None
        cu_source_file = None
        comp_dir = None

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

        # Process both line program and DIE data as they provide complementary information:
        # - Line program: Maps instruction addresses to source files (useful for functions)
        # - DIE data: Maps symbol definitions to source files (more accurate for variables)
        self._extract_line_program_data(cu, dwarfinfo)
        self._extract_die_symbol_data_optimized(cu, dwarfinfo, cu_source_file, cu_low_pc, cu_high_pc)

    def _extract_string_value(self, value) -> Optional[str]:
        """Extract string value from DWARF attribute.

        Args:
            value: DWARF attribute value (can be bytes, str, or other)

        Returns:
            String value or None if extraction fails
        """
        try:
            if isinstance(value, bytes):
                return value.decode('utf-8', errors='ignore')
            if isinstance(value, str):
                return value
            return str(value)
        except (UnicodeDecodeError, AttributeError) as e:
            logger.debug(f"Failed to extract string value: {e}")
            return None

    def _extract_line_program_data(self, cu, dwarfinfo) -> None:
        """Extract line program data to map addresses to source files.

        Line program data provides instruction-level address to source file mappings,
        which is particularly useful for function symbols and handling compiler
        optimizations like inlining.

        Args:
            cu: Compilation unit containing the line program
            dwarfinfo: DWARF debug information object
        """
        try:
            line_program = dwarfinfo.line_program_for_CU(cu)
            if not line_program:
                return

            entries = line_program.get_entries()
            if not entries:
                return

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
                                    # Store in dictionary
                                    self.dwarf_data['address_to_file'][address] = filename

                    except (IndexError, AttributeError) as e:
                        logger.debug(f"Failed to process line program entry: {e}")
                        continue

        except Exception as e:
            logger.warning(f"Failed to extract line program data for CU at offset {cu.cu_offset}: {e}")

    def _extract_die_symbol_data_optimized(self, cu, dwarfinfo, cu_source_file: Optional[str], cu_low_pc: Optional[int], cu_high_pc: Optional[int]) -> None:
        """Extract DIE symbol data optimized for only relevant symbols.

        DIEs (Debug Information Entries) provide symbol-specific source mappings
        that are more accurate than line program data for variables and precise
        symbol definitions.

        Args:
            cu: Compilation unit to process
            dwarfinfo: DWARF debug information object
            cu_source_file: Source file path for this CU
            cu_low_pc: CU starting address
            cu_high_pc: CU ending address
        """
        try:
            # Build file entries for this CU
            file_entries = {}
            line_program = dwarfinfo.line_program_for_CU(cu)

            if line_program and hasattr(line_program.header, 'file_entry'):
                # Deduplicate file entries to handle compiler-generated duplicates
                seen_files = {}
                unique_index = 1
                for i, file_entry in enumerate(line_program.header.file_entry):
                    if file_entry and hasattr(file_entry, 'name'):
                        filename = self._extract_string_value(file_entry.name)
                        if filename and filename not in seen_files:
                            file_entries[unique_index] = filename
                            seen_files[filename] = unique_index
                            unique_index += 1

            # Process DIEs with early filtering
            top_die = cu.get_top_DIE()
            self._process_die_tree_optimized(top_die, file_entries, cu_source_file, 0, cu_low_pc, cu_high_pc)

        except Exception as e:
            logger.warning(f"Failed to extract DIE symbol data for CU at offset {cu.cu_offset}: {e}")

    def _process_die_tree_optimized(self, die, file_entries: Dict[int, str], cu_source_file: Optional[str], depth: int, cu_low_pc: Optional[int], cu_high_pc: Optional[int]) -> None:
        """Process DIE tree with optimization and depth limiting.

        Args:
            die: Debug Information Entry to process
            file_entries: Mapping of file indices to file paths
            cu_source_file: Source file for the compilation unit
            depth: Current recursion depth
            cu_low_pc: CU starting address
            cu_high_pc: CU ending address
        """
        if depth > MAX_DIE_RECURSION:  # Prevent excessive recursion
            logger.debug(f"Reached maximum DIE recursion depth of {MAX_DIE_RECURSION}")
            return

        try:
            # Early filtering - only process relevant DIE tags
            relevant_tags = {'DW_TAG_subprogram', 'DW_TAG_variable', 'DW_TAG_formal_parameter', 'DW_TAG_inlined_subroutine'}
            if hasattr(die, 'tag') and die.tag:
                if die.tag not in relevant_tags:
                    # Still need to recurse for nested relevant DIEs
                    for child_die in die.iter_children():
                        self._process_die_tree_optimized(child_die, file_entries, cu_source_file, depth + 1, cu_low_pc, cu_high_pc)
                    return

            # Process this DIE if it's relevant
            self._process_die_for_dictionaries_optimized(die, file_entries, cu_source_file, cu_low_pc, cu_high_pc)

            # Recurse to children
            for child_die in die.iter_children():
                self._process_die_tree_optimized(child_die, file_entries, cu_source_file, depth + 1, cu_low_pc, cu_high_pc)

        except Exception as e:
            logger.debug(f"Error processing DIE at depth {depth}: {e}")

    def _process_die_for_dictionaries_optimized(self, die, file_entries: Dict[int, str], cu_source_file: Optional[str], cu_low_pc: Optional[int], cu_high_pc: Optional[int]) -> None:
        """Process a DIE optimized to only handle symbols we need.

        Args:
            die: Debug Information Entry to process
            file_entries: Mapping of file indices to file paths
            cu_source_file: Source file for the compilation unit
            cu_low_pc: CU starting address
            cu_high_pc: CU ending address
        """
        try:
            if not die.attributes:
                return

            attrs = die.attributes

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

            # Only process if this address is in our symbol table
            if die_address and die_address not in self.symbol_addresses:
                # Allow small address differences for ARM thumb mode and compiler optimizations
                if not any(abs(die_address - addr) <= THUMB_MODE_TOLERANCE for addr in self.symbol_addresses):
                    return

            # Get declaration file
            decl_file = None
            decl_file_attr = attrs.get('DW_AT_decl_file')
            if decl_file_attr and hasattr(decl_file_attr, 'value'):
                file_idx = decl_file_attr.value
                if file_idx in file_entries:
                    decl_file = file_entries[file_idx]

            # Determine best source file
            is_declaration = 'DW_AT_declaration' in attrs

            # For declarations in headers, prefer the CU source file over the header.
            # This handles cases where extern declarations in headers should be attributed
            # to the compilation unit that actually defines them, providing more accurate
            # source attribution for the actual implementation.
            if is_declaration and decl_file and decl_file.endswith('.h'):
                best_source_file = cu_source_file  # Prefer CU over header for declarations
            else:
                best_source_file = decl_file if decl_file else cu_source_file


            if best_source_file:
                # Store symbol mappings
                if die_address:
                    # For symbols with addresses, use the address as key
                    symbol_key = (die_name, die_address)
                    self.dwarf_data['symbol_to_file'][symbol_key] = best_source_file
                    self.dwarf_data['address_to_cu_file'][die_address] = best_source_file
                else:
                    # For symbols without DIE addresses (like static variables)
                    # Store in our static symbol mappings list for special handling
                    self.dwarf_data['static_symbol_mappings'].append((die_name, cu_source_file, best_source_file))

                    # Also store with address 0 as fallback
                    symbol_key = (die_name, 0)
                    if symbol_key not in self.dwarf_data['symbol_to_file']:
                        self.dwarf_data['symbol_to_file'][symbol_key] = best_source_file

        except Exception as e:
            logger.debug(f"Error processing DIE for symbol '{die_name}': {e}")