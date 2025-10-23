#!/usr/bin/env python3
"""
DWARF debug information processing for source file mapping.

This module handles the parsing and processing of DWARF debug information
to map symbols to their source files with intelligent optimizations.
"""

import os
import logging
import bisect
from typing import Dict, List, Optional, Any, Tuple
from collections import deque
from elftools.common.exceptions import ELFError
from ..core.exceptions import DWARFParsingError, DWARFCUProcessingError, DWARFAttributeError

# Configure logger
logger = logging.getLogger(__name__)

# Constants for magic values
MAX_ADDRESS = 0xFFFFFFFF  # Default max address when CU has no range
THUMB_MODE_TOLERANCE = 2   # ARM thumb mode address difference tolerance

# ARM machine types that use Thumb mode
ARM_MACHINES = {
    'EM_ARM',      # ARM 32-bit
    40,            # EM_ARM numeric value
}


class DWARFProcessor:  # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """Handles DWARF debug information processing for source file mapping.

    This processor extracts source file mappings from DWARF debug information
    using two complementary approaches:
    1. Line program data: Maps instruction addresses to source files
    2. DIE (Debug Information Entry) data: Maps symbol definitions to source files

    The processor optimizes performance by only processing compilation units (CUs)
    that contain symbols we actually need to map.
    """

    def __init__(
            self,
            elffile,
            symbol_addresses: set,
            skip_line_program: bool = False,
            machine: str = None):
        """Initialize DWARF processor with ELF file and target addresses.

        Args:
            elffile: Open ELF file object from pyelftools
            symbol_addresses: Set of symbol addresses we need to map to source files
            skip_line_program: Skip line program processing for faster analysis
            machine: ELF machine type (e.g., 'EM_ARM', 'EM_XTENSA')
                     for architecture-specific handling
        """
        self.elffile = elffile
        self.symbol_addresses = symbol_addresses
        self.skip_line_program = skip_line_program
        self.machine = machine

        # Determine if we need address tolerance based on architecture
        # ARM Thumb mode requires ±2 byte tolerance, other architectures use
        # exact match
        self.address_tolerance = THUMB_MODE_TOLERANCE if self._is_arm_architecture(
            machine) else 0

        if self.address_tolerance > 0:
            logger.debug(
                "Architecture %s uses address tolerance ±%d bytes",
                machine, self.address_tolerance)

        # Track which symbols we've already found to enable early termination
        self.found_symbols = set()
        self.target_symbol_count = len(symbol_addresses)
        # Precompute sorted symbol addresses for fast tolerance checking
        self.sorted_symbol_addresses = sorted(symbol_addresses)
        # Only keep actively used data structures
        self.dwarf_data = {
            # address -> filename (from line programs)
            'address_to_file': {},
            # (symbol_name, address) -> filename
            'symbol_to_file': {},
            'address_to_cu_file': {},       # address -> cu_filename
            'processed_cus': set(),         # Cache of processed CUs to avoid duplicates
            # List of (symbol_name, cu_source_file, decl_file) for static vars
            'static_symbol_mappings': [],
        }

    def _is_arm_architecture(self, machine) -> bool:
        """Check if the architecture is ARM and requires Thumb mode tolerance.

        Args:
            machine: ELF machine type (string or integer)

        Returns:
            True if ARM architecture, False otherwise
        """
        if machine is None:
            return False

        # Handle both string and numeric machine types
        if isinstance(machine, str):
            return machine in ARM_MACHINES

        # Numeric machine type
        return machine in ARM_MACHINES

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
            logger.debug(
                "Built CU index with %d compilation units",
                len(cu_address_index))

            # Only process CUs that contain relevant addresses for performance optimization
            # This avoids processing all CUs when we only need specific symbols
            relevant_cus = self._find_relevant_cus(cu_address_index)
            logger.debug(
                "Found %d relevant CUs out of %d total",
                len(relevant_cus), len(cu_address_index))

            for cu in relevant_cus:
                try:
                    self._process_cu(cu, dwarfinfo)
                    # Early termination disabled for correctness - other
                    # optimizations provide sufficient speedup
                    # if len(self.found_symbols) >= min(self.target_symbol_count * 2, 1000):
                    #     logger.debug("Early termination: found %d symbols (target: %d)",
                    #                  len(self.found_symbols), self.target_symbol_count)
                    #     break
                except Exception as e:
                    logger.error(
                        "Failed to process CU at offset %d: %s", cu.cu_offset, e)
                    raise DWARFCUProcessingError(
                        f"Failed to process CU at offset {cu.cu_offset}: {e}") from e

        except (IOError, OSError) as e:
            logger.error("Failed to read ELF file for DWARF parsing: %s", e)
            raise DWARFParsingError(
                f"Failed to read ELF file for DWARF parsing: {e}") from e
        except ELFError as e:
            logger.error("Invalid ELF file format: %s", e)
            raise DWARFParsingError(f"Invalid ELF file format: {e}") from e
        except Exception as e:
            logger.error("Unexpected error during DWARF parsing: %s", e)
            raise DWARFParsingError(
                f"Unexpected error during DWARF parsing: {e}") from e

        return self.dwarf_data

    def _is_address_in_symbol_set_with_tolerance(
            self, die_address: int) -> bool:
        """Check if die_address is in symbol set or within tolerance using binary search.

        Args:
            die_address: Address to check

        Returns:
            True if address is in symbol set or within architecture-specific tolerance
        """
        # Fast exact match first
        if die_address in self.symbol_addresses:
            return True

        # If no tolerance needed (non-ARM architectures), only exact match
        if self.address_tolerance == 0:
            return False

        # Use binary search to find addresses within tolerance range
        # Find insertion point for die_address - tolerance
        start_idx = bisect.bisect_left(
            self.sorted_symbol_addresses,
            die_address - self.address_tolerance)
        # Find insertion point for die_address + tolerance
        end_idx = bisect.bisect_right(
            self.sorted_symbol_addresses,
            die_address + self.address_tolerance)

        # Check if any address in the range is within tolerance
        for i in range(start_idx, end_idx):
            if abs(
                    die_address -
                    self.sorted_symbol_addresses[i]) <= self.address_tolerance:
                return True

        return False

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
                logger.debug(
                    "CU at offset %d has no address range, using full range",
                    cu.cu_offset)
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
            logger.error("Failed to extract address range from CU: %s", e)
            raise DWARFAttributeError(
                f"Failed to extract address range from CU: {e}") from e

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

    def _find_relevant_cus(
            self, cu_index: List[Tuple[int, int, Any]]) -> List[Any]:
        """Find compilation units that contain any of our target symbol addresses.

        This optimization is crucial for performance - we only process CUs that
        contain symbols we actually need to map, avoiding unnecessary processing
        of unrelated compilation units.

        Uses binary search for O(log n) lookups when CUs have specific ranges,
        falls back to processing all CUs when most have full ranges.

        Args:
            cu_index: Sorted list of CU address ranges

        Returns:
            List of CUs that contain at least one target symbol address
        """

        # Check if most CUs have the full address range (no specific ranges)
        full_range_count = sum(
            1 for start,
            end,
            _ in cu_index if start == 0 and end == MAX_ADDRESS)
        total_cus = len(cu_index)

        # If more than 80% of CUs have full range, process all (optimization
        # doesn't help)
        if full_range_count > 0.8 * total_cus:
            logger.debug(
                "Most CUs (%d/%d) have full range, processing all CUs",
                full_range_count, total_cus)
            return [cu for _, _, cu in cu_index]

        # Use binary search optimization when CUs have meaningful ranges
        logger.debug(
            "Using binary search optimization: %d/%d CUs have full range",
            full_range_count, total_cus)

        relevant_cus = []
        relevant_cu_set = set()  # Track CUs we've already added for O(1) lookup
        symbol_addr_list = sorted(self.symbol_addresses)

        # Pre-extract start addresses for binary search
        start_addresses = [start_addr for start_addr, _, _ in cu_index]

        for symbol_addr in symbol_addr_list:
            # Use binary search to find the rightmost CU start address <=
            # symbol_addr
            pos = bisect.bisect_right(start_addresses, symbol_addr) - 1

            if pos >= 0:
                start_addr, end_addr, cu = cu_index[pos]
                if start_addr <= symbol_addr <= end_addr:
                    if cu not in relevant_cu_set:
                        relevant_cus.append(cu)
                        relevant_cu_set.add(cu)

        return relevant_cus

    def _process_cu(self, cu, dwarfinfo):  # pylint: disable=too-many-locals
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

        # Track coverage before line program processing
        # die_coverage_before = len(self.dwarf_data['symbol_to_file'])  #
        # unused

        # Skip line program processing if requested (20-30% performance
        # improvement)
        if not self.skip_line_program:
            self._extract_line_program_data(cu, dwarfinfo)

        self._extract_die_symbol_data_optimized(
            cu, dwarfinfo, cu_source_file, cu_low_pc, cu_high_pc)

        # Track coverage after line program processing
        total_addresses = len(self.dwarf_data['address_to_file'])
        die_coverage_after = len(self.dwarf_data['symbol_to_file'])
        line_program_addresses = total_addresses

        # Store coverage metrics in dwarf_data for aggregation
        if 'coverage_metrics' not in self.dwarf_data:
            self.dwarf_data['coverage_metrics'] = {
                'die_symbols': 0,
                'line_program_addresses': 0,
                'cus_processed': 0,
                'line_program_skipped': self.skip_line_program
            }

        self.dwarf_data['coverage_metrics']['die_symbols'] = die_coverage_after
        self.dwarf_data['coverage_metrics']['line_program_addresses'] = line_program_addresses
        self.dwarf_data['coverage_metrics']['cus_processed'] += 1

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
            logger.error("Failed to extract string value: %s", e)
            raise DWARFAttributeError(
                f"Failed to extract string value: {e}") from e

    def _parse_location_expression(self, location_value) -> Optional[int]:
        """Parse DWARF location expression to extract address from DW_OP_addr.

        DWARF location expressions are bytecode sequences that describe where
        a variable is located. For global/static variables, the most common
        form is DW_OP_addr (opcode 0x03) followed by an address.

        Args:
            location_value: DWARF location expression (list or bytes)

        Returns:
            Extracted address or None if parsing fails or not a DW_OP_addr expression

        Note:
            This parser currently handles only DW_OP_addr (0x03) expressions.
            More complex location expressions (e.g., register-relative, computed)
            are not supported and will return None.
        """
        try:
            # Handle both list (from ListContainer) and bytes formats
            if hasattr(location_value, '__iter__'):
                expr_bytes = list(location_value) if not isinstance(
                    location_value, list) else location_value
            else:
                return None

            # Check if this is a DW_OP_addr (0x03) expression
            # DW_OP_addr format: [0x03, addr_byte1, addr_byte2, ...]
            if not expr_bytes or expr_bytes[0] != 0x03:
                return None

            # Extract address bytes (skip the opcode at index 0)
            addr_bytes = expr_bytes[1:]

            if not addr_bytes:
                return None

            # Convert bytes to address (little-endian, typical for most architectures)
            # For 32-bit: [b0, b1, b2, b3] -> b0 + (b1<<8) + (b2<<16) +
            # (b3<<24)
            address = 0
            for i, byte_val in enumerate(addr_bytes):
                address |= (byte_val << (i * 8))

            return address

        except (TypeError, AttributeError, IndexError) as e:
            logger.debug(
                "Failed to parse location expression: %s", e)
            return None

    def _extract_line_program_data(self, cu, dwarfinfo) -> None:  # pylint: disable=too-many-nested-blocks
        """Extract line program data to map addresses to source files.

        Line program data provides instruction-level address to source file mappings,
        which is particularly useful for function symbols and handling compiler
        optimizations like inlining.

        Args:
            cu: Compilation unit containing the line program
            dwarfinfo: DWARF debug information object
        """
        try:  # pylint: disable=too-many-nested-blocks
            line_program = dwarfinfo.line_program_for_CU(cu)
            if not line_program:
                return

            entries = line_program.get_entries()
            if not entries:
                return

            for entry in entries:
                if entry.state is None:
                    continue

                if hasattr(
                        entry.state,
                        'address') and hasattr(
                        entry.state,
                        'file'):
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
                                filename = self._extract_string_value(
                                    file_entry.name)
                                if filename:
                                    # Store in dictionary
                                    self.dwarf_data['address_to_file'][address] = filename

                    except (IndexError, AttributeError) as e:
                        logger.error(
                            "Failed to process line program entry: %s", e)
                        raise DWARFAttributeError(
                            f"Failed to process line program entry: {e}") from e

        except Exception as e:
            logger.error(
                "Failed to extract line program data for CU at offset %d: %s",
                cu.cu_offset, e)
            raise DWARFCUProcessingError(
                f"Failed to extract line program data for CU at offset {cu.cu_offset}: {e}") from e

    def _extract_die_symbol_data_optimized(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals,too-many-branches,too-many-statements
            self,
            cu,
            dwarfinfo,
            cu_source_file: Optional[str],
            cu_low_pc: Optional[int],
            cu_high_pc: Optional[int]) -> None:
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
                # Build file entries preserving original DWARF file indices
                # DWARF 4 and earlier: file indices are 1-based
                # DWARF 5 and later: file indices are 0-based
                # Even if there are duplicates, we must keep original indices
                # because DW_AT_decl_file references them by their original
                # index
                dwarf_version = cu['version']
                start_index = 0 if dwarf_version >= 5 else 1
                for idx, file_entry in enumerate(
                        line_program.header.file_entry, start=start_index):
                    if file_entry and hasattr(file_entry, 'name'):
                        filename = self._extract_string_value(file_entry.name)
                        if filename:
                            file_entries[idx] = filename

            # Process DIEs with early filtering
            top_die = cu.get_top_DIE()
            self._process_die_tree(
                top_die,
                file_entries,
                cu_source_file,
                0,
                cu_low_pc,
                cu_high_pc)

        except Exception as e:
            logger.error(
                "Failed to extract DIE symbol data for CU at offset %d: %s",
                cu.cu_offset, e)
            raise DWARFCUProcessingError(
                f"Failed to extract DIE symbol data for CU at offset {cu.cu_offset}: {e}") from e

    def _process_die_tree(self,  # pylint: disable=too-many-arguments,too-many-positional-arguments
                          die,
                          file_entries: Dict[int,
                                             str],
                          cu_source_file: Optional[str],
                          depth: int,  # pylint: disable=unused-argument
                          cu_low_pc: Optional[int],  # pylint: disable=unused-argument
                          cu_high_pc: Optional[int]) -> None:  # pylint: disable=unused-argument
        """Process DIE tree.

        Args:
            die: Debug Information Entry to process
            file_entries: Mapping of file indices to file paths
            cu_source_file: Source file for the compilation unit
            depth: Initial depth (maintained for API compatibility)
            cu_low_pc: CU starting address
            cu_high_pc: CU ending address
        """
        stack = deque([die])

        while stack:
            current_die = stack.pop()

            relevant_tags = {
                'DW_TAG_subprogram',
                'DW_TAG_variable',
                'DW_TAG_formal_parameter',
                'DW_TAG_inlined_subroutine'}

            for child_die in current_die.iter_children():
                stack.append(child_die)

            if hasattr(current_die, 'tag') and current_die.tag:
                if current_die.tag not in relevant_tags:
                    continue
                self._process_die_for_dictionaries_optimized(
                    current_die, file_entries, cu_source_file, cu_low_pc, cu_high_pc)

    def _process_die_for_dictionaries_optimized(  # pylint: disable=too-many-branches,too-many-statements,too-many-nested-blocks,too-many-arguments,too-many-positional-arguments,too-many-locals
            self,
            die,
            file_entries: Dict[int, str],
            cu_source_file: Optional[str],
            cu_low_pc: Optional[int],  # pylint: disable=unused-argument
            cu_high_pc: Optional[int]) -> None:  # pylint: disable=unused-argument
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

            # Get symbol name - may be in specification
            die_name = None
            name_attr = attrs.get('DW_AT_name')
            if name_attr and hasattr(name_attr, 'value'):
                die_name = self._extract_string_value(name_attr.value)

            # If no name, check if there's a specification reference
            spec_die = None
            if not die_name:
                spec_attr = attrs.get('DW_AT_specification')
                if spec_attr:
                    # Follow the specification reference to get name and other
                    # attributes
                    spec_die = die.get_DIE_from_attribute(
                        'DW_AT_specification')
                    if spec_die and spec_die.attributes:
                        name_attr = spec_die.attributes.get('DW_AT_name')
                        if name_attr and hasattr(name_attr, 'value'):
                            die_name = self._extract_string_value(
                                name_attr.value)

            if not die_name:
                return

            # Get address
            die_address = None
            low_pc_attr = attrs.get('DW_AT_low_pc')
            if low_pc_attr and hasattr(low_pc_attr, 'value'):
                try:
                    die_address = int(low_pc_attr.value)
                except (ValueError, TypeError) as e:
                    logger.debug(
                        "Could not parse DW_AT_low_pc value '%s' for symbol '%s': %s",
                        low_pc_attr.value, die_name, e)

            if not die_address:
                location_attr = attrs.get('DW_AT_location')
                if location_attr and hasattr(location_attr, 'value'):
                    # DW_AT_location contains DWARF expressions, parse them
                    die_address = self._parse_location_expression(
                        location_attr.value)
                    if not die_address:
                        logger.debug(
                            "Could not parse DW_AT_location expression for symbol '%s' "
                            "(not a simple DW_OP_addr or unsupported expression type)", die_name)

            # Only process if this address is in our symbol table
            if die_address and not self._is_address_in_symbol_set_with_tolerance(
                    die_address):
                return

            # Track found symbols for early termination (only count after full processing)
            # We'll add to found_symbols at the end of processing to ensure
            # mapping is complete

            # Get declaration file
            decl_file = None
            decl_file_attr = attrs.get('DW_AT_decl_file')
            if decl_file_attr and hasattr(decl_file_attr, 'value'):
                file_idx = decl_file_attr.value
                if file_idx in file_entries:
                    decl_file = file_entries[file_idx]

            # Determine best source file
            is_declaration = 'DW_AT_declaration' in attrs
            has_location = 'DW_AT_location' in attrs or die_address is not None
            has_external_linkage = 'DW_AT_external' in attrs

            # Check specification DIE for external linkage if not found
            # directly
            if not has_external_linkage and spec_die and spec_die.attributes:
                has_external_linkage = 'DW_AT_external' in spec_die.attributes

            # Source file selection strategy:
            # 1. Static symbols (no DW_AT_external): Use decl_file (where they're declared/defined)
            #    - Static variables in headers should map to the header
            # 2. Global symbols (DW_AT_external) with definitions: Use CU source file
            #    - Global variables defined in .c but declared in .h should map to .c
            # 3. Declarations only (no location): Use decl_file
            #    - Function prototypes, extern declarations should map to where declared

            if (not is_declaration and has_location and has_external_linkage
                    and decl_file != cu_source_file and cu_source_file):
                # Definition with external linkage - prefer CU source file
                # This handles cases like usb_device where DW_AT_decl_file points to header
                # but the actual definition is in the .c file
                best_source_file = cu_source_file
            else:
                # All other cases: use decl_file if available
                # - Static variables/functions (including those in headers)
                # - Declarations
                # - Cases where decl_file matches cu_source_file
                best_source_file = decl_file if decl_file else cu_source_file

            if best_source_file:
                # Store symbol mappings
                if die_address:
                    # For symbols with addresses, store with exact address
                    symbol_key = (die_name, die_address)
                    self.dwarf_data['symbol_to_file'][symbol_key] = best_source_file
                    self.dwarf_data['address_to_cu_file'][die_address] = best_source_file

                    # For ARM architectures, also store with tolerance-adjusted addresses
                    # ARM Thumb: LSB of function address indicates mode (0=ARM, 1=Thumb)
                    # DIEs store actual instruction addresses, ELF symbols
                    # include mode bit
                    if self.address_tolerance > 0:
                        symbol_to_file = self.dwarf_data['symbol_to_file']
                        address_to_cu = self.dwarf_data['address_to_cu_file']
                        for offset in range(-self.address_tolerance,
                                            self.address_tolerance + 1):
                            if offset != 0:  # Already stored exact address above
                                adjusted_addr = die_address + offset
                                adjusted_key = (die_name, adjusted_addr)
                                # Use setdefault for single lookup instead of
                                # check + set
                                symbol_to_file.setdefault(
                                    adjusted_key, best_source_file)
                                address_to_cu.setdefault(
                                    adjusted_addr, best_source_file)

                    # Track found symbols for early termination after
                    # successful mapping
                    if die_address in self.symbol_addresses:
                        self.found_symbols.add(die_address)
                    # For ARM, also check tolerance-adjusted addresses
                    elif self.address_tolerance > 0:
                        for offset in range(-self.address_tolerance,
                                            self.address_tolerance + 1):
                            if die_address + offset in self.symbol_addresses:
                                self.found_symbols.add(die_address + offset)
                                break
                else:
                    # For symbols without DIE addresses (like static variables)
                    # Store in our static symbol mappings list for special
                    # handling
                    self.dwarf_data['static_symbol_mappings'].append(
                        (die_name, cu_source_file, best_source_file))

                    # Also store with address 0 as fallback
                    symbol_key = (die_name, 0)
                    if symbol_key not in self.dwarf_data['symbol_to_file']:
                        self.dwarf_data['symbol_to_file'][symbol_key] = best_source_file

        except Exception as e:
            symbol_label = die_name if 'die_name' in locals() else 'unknown'
            logger.error(
                "Error processing DIE for symbol '%s': %s", symbol_label, e)
            raise DWARFAttributeError(
                f"Error processing DIE for symbol: {e}") from e
