#!/usr/bin/env python3
"""
DWARF debug information processing for source file mapping.

This module handles the parsing and processing of DWARF debug information
to map symbols to their source files with intelligent optimizations.
"""

import posixpath
import logging
import bisect
from typing import Dict, List, Optional, Any, Tuple
from collections import deque
from elftools.common.exceptions import ELFError, ELFRelocationError
from elftools.common.utils import struct_parse
from elftools.dwarf.structs import DWARFStructs
from ..core.exceptions import DWARFParsingError, DWARFCUProcessingError, DWARFAttributeError
from .line_sequences import (
    has_function_at_zero, is_dead_sequence, line_sequences, rows_by_address)
from .paths import is_abs, to_posix

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

# pyelftools only parses CUs with 4 or 8 byte addresses (AVR uses 2)
SUPPORTED_ADDRESS_SIZES = (4, 8)

# DWARF expression opcodes, DWARF 5 section 7.7.1
DW_OP_ADDR = 0x03
DW_OP_PLUS_UCONST = 0x23
DW_OP_ADDRX = 0xa1
DW_OP_GNU_ADDR_INDEX = 0xfb

# unit_length values 0xfffffff0-0xfffffffe are reserved, DWARF 5 section 7.4
_DWARF_RESERVED_LENGTH = 0xfffffff0


def _read_uleb128(data, pos: int) -> Tuple[Optional[int], int]:
    """ULEB128 value at data[pos] and the position after it, (None, pos) if truncated."""
    value = 0
    for i, byte_val in enumerate(data[pos:]):
        value |= (byte_val & 0x7F) << (7 * i)
        if not byte_val & 0x80:
            return value, pos + i + 1
    return None, pos


def _iter_cu_headers(dwarfinfo):
    """Yield (offset, header) for every CU header in .debug_info.

    Parsed with pyelftools' own header struct but without building the CU,
    because pyelftools fails on a CU whose address size it does not support.
    """
    section = dwarfinfo.debug_info_sec
    if section is None:
        # has_dwarf_info() is also true for a stripped ELF with only .eh_frame
        return
    offset = 0
    while offset + 4 <= section.size:
        initial_length = struct_parse(
            dwarfinfo.structs.the_Dwarf_uint32, section.stream, offset)
        if _DWARF_RESERVED_LENGTH <= initial_length < 0xFFFFFFFF:
            logger.warning(
                "Stopping at CU with reserved unit length 0x%x at offset %d",
                initial_length, offset)
            return
        structs = DWARFStructs(
            little_endian=dwarfinfo.config.little_endian,
            dwarf_format=64 if initial_length == 0xFFFFFFFF else 32,
            address_size=4,
            dwarf_version=2)
        header = struct_parse(structs.Dwarf_CU_header, section.stream, offset)
        yield offset, header
        offset += header['unit_length'] + structs.initial_length_field_size()


def _iter_supported_cus(dwarfinfo):
    """Yield the CUs pyelftools can parse, warning once per skipped address size."""
    skipped = set()
    for offset, header in _iter_cu_headers(dwarfinfo):
        if header['address_size'] in SUPPORTED_ADDRESS_SIZES:
            yield dwarfinfo.get_CU_at(offset)
        elif header['address_size'] not in skipped:
            skipped.add(header['address_size'])
            logger.warning(
                "Skipping DWARF source mapping for CUs with unsupported address size %d",
                header['address_size'])


def _file_index_base(line_program) -> int:
    """Index of the first entry in a line program's file table.

    File numbers (in line program rows and in DW_AT_decl_file) index the
    line program's file table, whose numbering is set by the line program
    header version: 0-based from DWARF 5, 1-based before. The CU version
    does not decide it, because toolchains mix the two: GCC 11+ with an
    assembler-generated line table emits DWARF 5 .debug_info alongside a
    version 3 .debug_line.
    """
    return 0 if line_program.header.version >= 5 else 1


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
        self.little_endian = getattr(elffile, 'little_endian', True)
        self._function_at_zero = None  # see _has_function_at_zero

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
            # address -> line number (from line programs)
            'address_to_line': {},
            # (start, end, CU offset) of every live line sequence, end exclusive
            'line_sequences': [],
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
            try:
                dwarfinfo = self.elffile.get_dwarf_info()
            except ELFRelocationError as e:
                # --emit-relocs leaves .rel.debug_* entries in linked binaries,
                # some of a type pyelftools rejects (TinyGo R_ARM_NONE). Their
                # DWARF is already resolved, so read it as stored.
                logger.debug("Reading DWARF without relocation: %s", e)
                dwarfinfo = self.elffile.get_dwarf_info(relocate_dwarf_sections=False)

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

        for cu in _iter_supported_cus(dwarfinfo):
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

        # Check if any CUs have full address range (no specific ranges)
        # Full-range CUs can contain any symbol, so binary search optimization
        # doesn't work reliably when they exist (e.g., C++ <artificial> CUs)
        has_full_range = any(
            start == 0 and end == MAX_ADDRESS
            for start, end, _ in cu_index
        )

        if has_full_range:
            logger.debug("Found full-range CUs, processing all %d CUs", len(cu_index))
            return [cu for _, _, cu in cu_index]

        # Use binary search optimization only when all CUs have specific ranges
        logger.debug("Using binary search optimization for %d CUs", len(cu_index))

        relevant_cus = []
        relevant_cu_set = set()
        start_addresses = [start for start, _, _ in cu_index]

        for symbol_addr in self.symbol_addresses:
            pos = bisect.bisect_right(start_addresses, symbol_addr) - 1
            if pos >= 0:
                start_addr, end_addr, cu = cu_index[pos]
                if start_addr <= symbol_addr <= end_addr and cu not in relevant_cu_set:
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

        cu_name = to_posix(cu_name)
        comp_dir = to_posix(comp_dir)
        # Placeholder names such as TinyGo "<unknown>" or GCC LTO "<artificial>"
        if cu_name and cu_name.startswith('<') and cu_name.endswith('>'):
            cu_name = None
        if cu_name:
            if comp_dir and not is_abs(cu_name):
                cu_source_file = posixpath.normpath(posixpath.join(comp_dir, cu_name))
            else:
                cu_source_file = posixpath.normpath(cu_name)

        # The line program's file table, joined with its directories, is
        # shared by the line rows (address_to_file) and DW_AT_decl_file
        file_paths = self._line_program_file_paths(dwarfinfo, cu, comp_dir)

        # Process both line program and DIE data as they provide complementary information:
        # - Line program: Maps instruction addresses to source files (useful for functions)
        # - DIE data: Maps symbol definitions to source files (more accurate for variables)

        # Track coverage before line program processing
        # die_coverage_before = len(self.dwarf_data['symbol_to_file'])  #
        # unused

        # Skip line program processing if requested (20-30% performance
        # improvement)
        if not self.skip_line_program:
            self._extract_line_program_data(cu, dwarfinfo, file_paths)

        self._extract_die_symbol_data_optimized(
            cu, cu_source_file, cu_low_pc, cu_high_pc, file_paths)

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

    def _line_program_file_paths(self, dwarfinfo, cu,
                                 comp_dir: Optional[str]) -> Dict[int, str]:
        """The CU's line program file table as {file index: full path}.

        A file entry names a file relative to one of the line program's
        directories (its dir_index); the directory may itself be relative to
        the CU's compilation directory. Before DWARF 5, dir_index 0 is the
        compilation directory and the directory list is 1-based; from DWARF 5
        the list is 0-based and its first entry is the compilation directory.
        Indices follow the file table's numbering (_file_index_base), the one
        DW_AT_decl_file and the line rows use. Both are kept as recorded by
        the compiler, so a file is a full path when the compiler knew one.
        """
        try:
            line_program = dwarfinfo.line_program_for_CU(cu)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.debug("No line program for CU at offset %d: %s", cu.cu_offset, e)
            return {}
        if not line_program or not hasattr(line_program.header, 'file_entry'):
            return {}
        header = line_program.header
        directories = [to_posix(self._extract_string_value(d))
                       for d in (getattr(header, 'include_directory', None) or [])]
        dwarf5 = header.version >= 5
        paths: Dict[int, str] = {}
        for idx, entry in enumerate(header.file_entry, start=_file_index_base(line_program)):
            if not entry or not hasattr(entry, 'name'):
                continue
            name = to_posix(self._extract_string_value(entry.name))
            if not name:
                continue
            # pyelftools stores None when a DWARF 5 entry format carries no
            # DW_LNCT_directory_index; the file is then in directory 0
            dir_index = getattr(entry, 'dir_index', None)
            paths[idx] = self._join_file_entry(
                name, 0 if dir_index is None else dir_index, directories, dwarf5, comp_dir)
        return paths

    @staticmethod
    def _join_file_entry(name: str, dir_index: int, directories: List[Optional[str]],
                         dwarf5: bool, comp_dir: Optional[str]) -> str:
        """The full path of one line program file entry (see
        _line_program_file_paths); the bare name when no directory is known."""
        if is_abs(name):
            return posixpath.normpath(name)
        directory = None
        if dwarf5:
            if 0 <= dir_index < len(directories):
                directory = directories[dir_index]
        elif dir_index == 0:
            directory = comp_dir
        elif 1 <= dir_index <= len(directories):
            directory = directories[dir_index - 1]
        if directory and comp_dir and not is_abs(directory):
            directory = posixpath.join(comp_dir, directory)
        if not directory:
            return name
        return posixpath.normpath(posixpath.join(directory, name))

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

    def _get_die_name_and_spec(self, die) -> Tuple[Optional[str], Optional[Any]]:
        """Extract symbol name from DIE, following abstract_origin/specification chain.

        For C++ templates and inlined functions, DWARF uses reference chains:
        concrete DIE (with address) -> abstract_origin -> specification -> name

        Args:
            die: Debug Information Entry to extract name from

        Returns:
            Tuple of (name, spec_die) where spec_die is the DIE containing
            the name (for later attribute lookups like decl_file)
        """
        if not die.attributes:
            return None, None

        # Try direct name first
        name_attr = die.attributes.get('DW_AT_name')
        if name_attr and hasattr(name_attr, 'value'):
            return self._extract_string_value(name_attr.value), None

        # Follow abstract_origin (C++ template instantiations, inlined functions)
        ref_die = die
        spec_die = None
        if 'DW_AT_abstract_origin' in die.attributes:
            abstract_die = die.get_DIE_from_attribute('DW_AT_abstract_origin')
            if abstract_die and abstract_die.attributes:
                name_attr = abstract_die.attributes.get('DW_AT_name')
                if name_attr and hasattr(name_attr, 'value'):
                    return self._extract_string_value(name_attr.value), abstract_die
                ref_die = abstract_die
                spec_die = abstract_die

        # Follow specification (C++ method definitions)
        if 'DW_AT_specification' in ref_die.attributes:
            spec_die = ref_die.get_DIE_from_attribute('DW_AT_specification')
            if spec_die and spec_die.attributes:
                name_attr = spec_die.attributes.get('DW_AT_name')
                if name_attr and hasattr(name_attr, 'value'):
                    return self._extract_string_value(name_attr.value), spec_die

        return None, spec_die

    def _get_die_decl_file(
            self, die, spec_die, file_entries: Dict[int, str]) -> Optional[str]:
        """Extract declaration file from DIE or its specification DIE.

        Args:
            die: Primary DIE to check
            spec_die: Specification DIE (from _get_die_name_and_spec)
            file_entries: Mapping of file indices to file paths

        Returns:
            Declaration file path or None
        """
        # Check primary DIE first
        for check_die in [die, spec_die]:
            if check_die and check_die.attributes:
                decl_file_attr = check_die.attributes.get('DW_AT_decl_file')
                if decl_file_attr and hasattr(decl_file_attr, 'value'):
                    file_idx = decl_file_attr.value
                    if file_idx in file_entries:
                        return file_entries[file_idx]
        return None

    def _parse_location_expression(
            self, location_value, address_size: Optional[int] = None,
            resolve_addr_index=None) -> Optional[int]:
        """Extract a static address from a DWARF location expression.

        Handles DW_OP_addr (0x03), DW_OP_addrx (0xa1) and DW_OP_GNU_addr_index
        (0xfb). Other expressions return None.

        Args:
            location_value: DWARF location expression (list or bytes)
            address_size: CU address size. When given, a trailing
                DW_OP_plus_uconst (0x23) offset is added, as LLVM emits for
                variables inside merged globals.
            resolve_addr_index: Callable mapping a .debug_addr index to an
                address, needed for DW_OP_addrx and DW_OP_GNU_addr_index.

        Returns:
            Extracted address or None if the expression is not supported
        """
        try:
            # Handle both list (from ListContainer) and bytes formats
            if not hasattr(location_value, '__iter__'):
                return None
            address, rest = self._expression_address(
                list(location_value), address_size, resolve_addr_index)
            if address is None:
                return None
            offset = self._parse_plus_uconst(rest)
            return None if offset is None else address + offset
        except (TypeError, AttributeError, IndexError, ValueError) as e:
            logger.debug("Failed to parse location expression: %s", e)
            return None

    def _expression_address(self, expr_bytes, address_size, resolve_addr_index):
        """Address from the leading operation and the operations after it, (None, []) if none."""
        opcode = expr_bytes[0] if expr_bytes else None
        if opcode == DW_OP_ADDR:
            if not address_size:
                # Unknown address size: the rest of the expression is the address
                address_size = len(expr_bytes) - 1
            addr_bytes = expr_bytes[1:1 + address_size]
            if not addr_bytes or len(addr_bytes) < address_size:
                return None, []
            byteorder = 'little' if self.little_endian else 'big'
            return (int.from_bytes(bytes(addr_bytes), byteorder),
                    expr_bytes[1 + address_size:])
        if opcode in (DW_OP_ADDRX, DW_OP_GNU_ADDR_INDEX) and resolve_addr_index:
            index, pos = _read_uleb128(expr_bytes, 1)
            if index is not None:
                return resolve_addr_index(index), expr_bytes[pos:]
        return None, []

    @staticmethod
    def _parse_plus_uconst(rest) -> Optional[int]:
        """Offset of an optional trailing DW_OP_plus_uconst, None if unsupported.

        Operand is ULEB128, see DWARF 5 section 7.6.
        """
        if not rest:
            return 0
        if rest[0] != DW_OP_PLUS_UCONST:
            return None
        value, pos = _read_uleb128(rest, 1)
        return value if value is not None and pos == len(rest) else None

    @staticmethod
    def _addr_index_resolver(cu):
        """Callable mapping a .debug_addr index of this CU to an address, None on failure."""
        def resolve(index: int) -> Optional[int]:
            debug_addr = cu.dwarfinfo.debug_addr_sec
            attrs = cu.get_top_DIE().attributes
            base = attrs.get('DW_AT_addr_base') or attrs.get('DW_AT_GNU_addr_base')
            if not debug_addr or not base:
                return None
            try:
                return struct_parse(
                    cu.structs.the_Dwarf_target_addr, debug_addr.stream,
                    base.value + index * cu['address_size'])
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.debug("Failed to read .debug_addr index %d: %s", index, e)
                return None
        return resolve

    def _extract_line_program_data(
            self, cu, dwarfinfo, file_paths: Dict[int, str]) -> None:
        """Extract line program data to map addresses to source files.

        Line program data provides instruction-level address to source file mappings,
        which is particularly useful for function symbols and handling compiler
        optimizations like inlining.

        Rows are taken one sequence at a time (see line_sequences), and
        sequences of code the linker discarded are dropped as a whole. When
        sequences of different CUs name the same address, the first one
        stored keeps it.

        Args:
            cu: Compilation unit containing the line program
            dwarfinfo: DWARF debug information object
            file_paths: The CU's file table from _line_program_file_paths
        """
        try:
            line_program = dwarfinfo.line_program_for_CU(cu)
            if not line_program:
                return
            entries = line_program.get_entries()
            if not entries:
                return
            try:
                address_size = cu['address_size']
            except KeyError:
                address_size = 4

            address_to_file = self.dwarf_data['address_to_file']
            for rows, end in line_sequences(entries, file_paths):
                start = rows[0][0]
                if end <= start or is_dead_sequence(
                        start, address_size, self._has_function_at_zero()):
                    continue
                for address, (filename, line) in rows_by_address(rows, end).items():
                    if address not in address_to_file:
                        address_to_file[address] = filename
                        if line:
                            self.dwarf_data['address_to_line'][address] = line
                self.dwarf_data['line_sequences'].append((start, end, cu.cu_offset))

        except Exception as e:
            logger.error(
                "Failed to extract line program data for CU at offset %d: %s",
                cu.cu_offset, e)
            raise DWARFCUProcessingError(
                f"Failed to extract line program data for CU at offset {cu.cu_offset}: {e}") from e

    def _has_function_at_zero(self) -> bool:
        """has_function_at_zero for this ELF, computed once."""
        if self._function_at_zero is None:
            self._function_at_zero = has_function_at_zero(self.elffile)
        return self._function_at_zero

    def _extract_die_symbol_data_optimized(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals,too-many-branches,too-many-statements
            self,
            cu,
            cu_source_file: Optional[str],
            cu_low_pc: Optional[int],
            cu_high_pc: Optional[int],
            file_entries: Dict[int, str]) -> None:
        """Extract DIE symbol data optimized for only relevant symbols.

        DIEs (Debug Information Entries) provide symbol-specific source mappings
        that are more accurate than line program data for variables and precise
        symbol definitions.

        Args:
            cu: Compilation unit to process
            cu_source_file: Source file path for this CU
            cu_low_pc: CU starting address
            cu_high_pc: CU ending address
            file_entries: The CU's file table from _line_program_file_paths,
                keyed by the original DWARF file index that DW_AT_decl_file
                references
        """
        try:
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

            # Get symbol name (follows abstract_origin/specification chain for C++)
            die_name, spec_die = self._get_die_name_and_spec(die)
            if not die_name:
                return

            # Get address from low_pc or location expression
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
                    die_address = self._parse_location_expression(
                        location_attr.value, die.cu['address_size'],
                        self._addr_index_resolver(die.cu))

            # Only process if this address is in our symbol table
            if die_address and not self._is_address_in_symbol_set_with_tolerance(
                    die_address):
                return

            # Get declaration file (checks DIE and spec_die)
            decl_file = self._get_die_decl_file(die, spec_die, file_entries)

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
