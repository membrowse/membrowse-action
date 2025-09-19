#!/usr/bin/env python3
"""
DWARF debug information processing for source file mapping.

This module handles the parsing and processing of DWARF debug information
to map symbols to their source files with intelligent optimizations.
"""

import os
from typing import Dict, List, Optional, Any, Tuple
from elftools.common.exceptions import ELFError
from .exceptions import DWARFParsingError


class DWARFProcessor:
    """Handles DWARF debug information processing for source file mapping"""

    def __init__(self, elffile, symbol_addresses: set):
        """Initialize DWARF processor with ELF file and target addresses."""
        self.elffile = elffile
        self.symbol_addresses = symbol_addresses
        self.dwarf_data = {
            'address_to_file': {},          # address -> filename (from line programs)
            'symbol_to_file': {},           # (symbol_name, address) -> filename
            'symbol_to_cu_file': {},        # (symbol_name, address) -> cu_filename
            'address_to_cu_file': {},       # address -> cu_filename
            'cu_file_list': [],             # List of CU filenames
            'system_headers': set(),        # Cache of known system headers
            'processed_cus': set(),         # Cache of processed CUs to avoid duplicates
            'die_offset_cache': {},         # DIE offset -> (decl_file, cu_source_file)
            'static_symbol_mappings': [],   # List of (symbol_name, cu_source_file, decl_file) for static vars
        }

    def process_dwarf_info(self) -> Dict[str, Any]:
        """Process DWARF information and return symbol mapping data."""
        if not self.elffile.has_dwarf_info():
            return self.dwarf_data

        try:
            dwarfinfo = self.elffile.get_dwarf_info()

            # Build CU address range index
            cu_address_index = self._build_cu_address_index(dwarfinfo)

            # Only process CUs that contain relevant addresses
            relevant_cus = self._find_relevant_cus(cu_address_index)

            for cu in relevant_cus:
                try:
                    self._process_cu(cu, dwarfinfo)
                except Exception:  # pylint: disable=broad-exception-caught
                    continue

        except (IOError, OSError) as e:
            raise DWARFParsingError(f"Failed to read ELF file for DWARF parsing: {e}") from e
        except ELFError as e:
            raise DWARFParsingError(f"Invalid ELF file format: {e}") from e
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Warning: DWARF parsing encountered unexpected error: {e}")

        return self.dwarf_data

    def _build_cu_address_index(self, dwarfinfo) -> List[Tuple[int, int, Any]]:
        """Build an index of compilation unit address ranges for fast lookup."""
        cu_index = []

        for cu in dwarfinfo.iter_CUs():
            try:
                top_die = cu.get_top_DIE()
                if not top_die.attributes:
                    continue

                low_pc_attr = top_die.attributes.get('DW_AT_low_pc')
                high_pc_attr = top_die.attributes.get('DW_AT_high_pc')

                if not (low_pc_attr and high_pc_attr):
                    cu_index.append((0, 0xFFFFFFFF, cu))
                    continue

                low_pc = int(low_pc_attr.value)
                high_pc_val = high_pc_attr.value

                if isinstance(high_pc_val, int) and high_pc_val < low_pc:
                    high_pc = low_pc + high_pc_val
                else:
                    high_pc = int(high_pc_val)

                cu_index.append((low_pc, high_pc, cu))

            except Exception:  # pylint: disable=broad-exception-caught
                cu_index.append((0, 0xFFFFFFFF, cu))

        cu_index.sort(key=lambda x: x[0])
        return cu_index

    def _find_relevant_cus(self, cu_index: List[Tuple[int, int, Any]]) -> List[Any]:
        """Find compilation units that contain any of our target symbol addresses."""
        relevant_cus = []
        symbol_addr_list = sorted(self.symbol_addresses)

        for symbol_addr in symbol_addr_list:
            for start_addr, end_addr, cu in cu_index:
                if start_addr <= symbol_addr <= end_addr:
                    if cu not in relevant_cus:
                        relevant_cus.append(cu)
                elif start_addr > symbol_addr:
                    break

        return relevant_cus

    def _process_cu(self, cu, dwarfinfo):
        """Process a single compilation unit."""
        cu_offset = cu.cu_offset
        if cu_offset in self.dwarf_data['processed_cus']:
            return
        self.dwarf_data['processed_cus'].add(cu_offset)

        # Get CU address range for mapping symbols
        cu_low_pc = None
        cu_high_pc = None
        top_die = cu.get_top_DIE()
        if top_die.attributes:
            low_pc_attr = top_die.attributes.get('DW_AT_low_pc')
            high_pc_attr = top_die.attributes.get('DW_AT_high_pc')
            if low_pc_attr and high_pc_attr:
                try:
                    cu_low_pc = int(low_pc_attr.value)
                    high_pc_val = high_pc_attr.value
                    if isinstance(high_pc_val, int) and high_pc_val < cu_low_pc:
                        cu_high_pc = cu_low_pc + high_pc_val
                    else:
                        cu_high_pc = int(high_pc_val)
                except (ValueError, TypeError):
                    pass

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

        self.dwarf_data['cu_file_list'].append(cu_source_file)

        # Process line program (address -> file mapping)
        self._extract_line_program_data(cu, dwarfinfo, cu_source_file)

        # Process DIEs (symbol -> file mapping)
        self._extract_die_symbol_data_optimized(cu, dwarfinfo, cu_source_file, cu_name, cu_low_pc, cu_high_pc)

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

    def _extract_line_program_data(self, cu, dwarfinfo, cu_source_file: Optional[str]) -> None:
        """Extract line program data into dictionaries."""
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

                    except (IndexError, AttributeError):
                        continue

        except Exception:  # pylint: disable=broad-exception-caught
            pass

    def _extract_die_symbol_data_optimized(self, cu, dwarfinfo, cu_source_file: Optional[str], cu_name: Optional[str], cu_low_pc: Optional[int], cu_high_pc: Optional[int]) -> None:
        """Extract DIE symbol data optimized for only relevant symbols."""
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

        except Exception:  # pylint: disable=broad-exception-caught
            pass

    def _process_die_tree_optimized(self, die, file_entries: Dict[int, str], cu_source_file: Optional[str], depth: int, cu_low_pc: Optional[int], cu_high_pc: Optional[int]) -> None:
        """Process DIE tree with optimization and depth limiting."""
        if depth > 10:  # Prevent excessive recursion
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

        except Exception:  # pylint: disable=broad-exception-caught
            pass

    def _process_die_for_dictionaries_optimized(self, die, file_entries: Dict[int, str], cu_source_file: Optional[str], cu_low_pc: Optional[int], cu_high_pc: Optional[int]) -> None:
        """Process a DIE optimized to only handle symbols we need."""
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
                # Allow small address differences (ARM thumb mode, compiler optimizations)
                if not any(abs(die_address - addr) <= 2 for addr in self.symbol_addresses):
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

            # For declarations in headers, prefer the CU source file over the header
            # This handles cases where extern declarations in headers should be attributed
            # to the compilation unit that actually defines them
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

        except Exception:  # pylint: disable=broad-exception-caught
            pass