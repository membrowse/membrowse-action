#!/usr/bin/env python3
"""
Memory Report Generator for Embedded Firmware

This module analyzes ELF files and linker scripts to generate comprehensive
memory usage reports for embedded firmware projects.
"""

import argparse
import json
import os
import sys
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
    """Handles ELF file analysis and data extraction"""

    def __init__(self, elf_path: str):
        self.elf_path = Path(elf_path)
        self._validate_elf_file()
        self._source_file_mapping = {
            'by_address': {},      # int -> str (address -> source_file)
            'by_compound_key': {}  # tuple -> str ((symbol_name, address) -> source_file)
        }
        self._line_mapping = {}    # int -> str (address -> source_file from .debug_line)
        self._build_line_mapping()
        self._build_source_file_mapping()

    def _validate_elf_file(self) -> None:
        """Validate that the ELF file exists and is readable"""
        if not self.elf_path.exists():
            raise ELFAnalysisError(f"ELF file not found: {self.elf_path}")

        if not os.access(self.elf_path, os.R_OK):
            raise ELFAnalysisError(f"Cannot read ELF file: {self.elf_path}")

    def _build_line_mapping(self) -> None:
        """
        Build a mapping {address: source_file_path} from .debug_line section.
        This provides the most reliable source file mapping for all addresses that
        correspond to actual code in source files.
        """
        # Also build compilation unit address ranges
        self._cu_ranges = []  # List of (low_addr, high_addr, cu_name, cu_path)
        self._all_cus = []  # List of all CU names, even without address ranges
        
        try:
            with open(self.elf_path, 'rb') as f:
                elffile = ELFFile(f)
                
                if not elffile.has_dwarf_info():
                    return

                dwarfinfo = elffile.get_dwarf_info()

                for cu in dwarfinfo.iter_CUs():
                    top_die = cu.get_top_DIE()

                    # Get the compilation directory if available
                    comp_dir_attr = top_die.attributes.get('DW_AT_comp_dir')
                    comp_dir = comp_dir_attr.value.decode('utf-8', errors='ignore') if comp_dir_attr else ""
                    
                    # Get compilation unit name
                    cu_name_attr = top_die.attributes.get('DW_AT_name')
                    cu_name = cu_name_attr.value.decode('utf-8', errors='ignore') if cu_name_attr else "unknown"
                    
                    # Store all CU names
                    self._all_cus.append(cu_name)
                    
                    # Get address range for this CU
                    low_pc_attr = top_die.attributes.get('DW_AT_low_pc')
                    high_pc_attr = top_die.attributes.get('DW_AT_high_pc')
                    
                    if low_pc_attr:
                        low_pc = low_pc_attr.value
                        # high_pc can be an address or an offset
                        if high_pc_attr:
                            high_pc_val = high_pc_attr.value
                            # Check if it's an offset (DW_FORM_data*) or absolute address
                            if high_pc_attr.form in ('DW_FORM_data1', 'DW_FORM_data2', 'DW_FORM_data4', 'DW_FORM_data8'):
                                high_pc = low_pc + high_pc_val
                            else:
                                high_pc = high_pc_val
                            
                            # Store CU range
                            self._cu_ranges.append((low_pc, high_pc, cu_name, os.path.join(comp_dir, cu_name) if comp_dir else cu_name))

                    lineprog = dwarfinfo.line_program_for_CU(cu)
                    if not lineprog:
                        continue

                    # Get file and directory tables - handle different pyelftools versions
                    try:
                        file_entries = lineprog.header.file_entry
                        include_dirs = lineprog.header.include_directory
                    except AttributeError:
                        # Try alternative access method
                        file_entries = lineprog['file_entry'] if 'file_entry' in lineprog else []
                        include_dirs = lineprog['include_directory'] if 'include_directory' in lineprog else []

                    # Process line program entries
                    for entry in lineprog.get_entries():
                        if entry.state is None:
                            continue
                        state = entry.state

                        # Skip invalid entries
                        if (state.end_sequence or not hasattr(state, 'address') or 
                            state.address is None or not hasattr(state, 'file') or 
                            state.file is None or state.file == 0):
                            continue

                        # Get file entry (DWARF file index is 1-based)
                        try:
                            file_entry = file_entries[state.file - 1]
                            filename = file_entry.name
                            if isinstance(filename, bytes):
                                filename = filename.decode('utf-8', errors='ignore')

                            # Resolve full path
                            if hasattr(file_entry, 'dir_index') and file_entry.dir_index > 0:
                                # File is in an include directory
                                try:
                                    incdir = include_dirs[file_entry.dir_index - 1]
                                    if isinstance(incdir, bytes):
                                        incdir = incdir.decode('utf-8', errors='ignore')
                                    dirpath = os.path.join(comp_dir, incdir) if comp_dir else incdir
                                except (IndexError, AttributeError):
                                    dirpath = comp_dir
                            else:
                                # File is in compilation directory
                                dirpath = comp_dir

                            # Build full path and normalize
                            if dirpath:
                                filepath = os.path.normpath(os.path.join(dirpath, filename))
                            else:
                                filepath = filename

                            self._line_mapping[state.address] = filepath

                        except (IndexError, AttributeError):
                            continue

        except (IOError, OSError, ELFError, Exception):  # pylint: disable=broad-exception-caught
            # If line parsing fails, continue without line info
            pass

    def _build_source_file_mapping(self) -> None:
        """Build mapping from addresses and (symbol,address) pairs to source files using DWARF info.

        Uses two-tier approach:
        1. Primary: address -> source_file (most reliable for duplicate symbol names)
        2. Secondary: (symbol_name, address) -> source_file (fallback with address=0 placeholder)
        
        Prioritizes definition locations over declaration locations.
        """
        try:
            with open(self.elf_path, 'rb') as f:
                elffile = ELFFile(f)

                if not elffile.has_dwarf_info():
                    return  # No debug info available

                dwarfinfo = elffile.get_dwarf_info()

                # Iterate through all compilation units
                for cu in dwarfinfo.iter_CUs():
                    # Get the compilation unit's source file (for definitions)
                    cu_source_file = self._get_cu_source_file(cu)
                    
                    # Get the file table for this compilation unit
                    file_entries = self._get_file_entries(dwarfinfo, cu)

                    # Iterate through all DIEs (Debug Information Entries) in this CU
                    for die in cu.iter_DIEs():
                        self._process_die_for_source_mapping(die, file_entries, cu_source_file, cu_source_file)

        except (IOError, OSError, ELFError, Exception):  # pylint: disable=broad-exception-caught
            # If DWARF parsing fails, continue without source file info
            pass

    def _get_cu_source_file(self, cu) -> Optional[str]:
        """Extract the source file name for this compilation unit (definition location)"""
        try:
            # Get the root DIE of the compilation unit
            top_die = cu.get_top_DIE()
            
            # Look for DW_AT_name which contains the source file for this CU
            if 'DW_AT_name' in top_die.attributes:
                name_attr = top_die.attributes['DW_AT_name']
                if hasattr(name_attr, 'value'):
                    return self._extract_string_value(name_attr.value)
                    
            # Some compilers use DW_AT_comp_dir + DW_AT_name
            # We just want the filename, not the full path
            
        except (AttributeError, Exception):  # pylint: disable=broad-exception-caught
            pass
            
        return None

    def _get_file_entries(self, dwarfinfo, cu) -> Dict[int, str]:
        """Extract file entries from the line program"""
        file_entries = {}

        try:
            # Get line program for this compilation unit
            line_program = dwarfinfo.line_program_for_CU(cu)
            if line_program is None:
                return file_entries

            # Build file index to filename mapping
            for i, file_entry in enumerate(line_program.header.file_entry):
                if hasattr(file_entry, 'name'):
                    filename = file_entry.name.decode(
                        'utf-8') if isinstance(file_entry.name, bytes) else str(file_entry.name)
                    file_entries[i + 1] = filename  # DWARF file indices start at 1

        except (AttributeError, Exception):  # pylint: disable=broad-exception-caught
            # Handle different pyelftools versions or missing line program
            pass

        return file_entries

    def _process_die_for_source_mapping(self, die, file_entries: Dict[int, str], 
                                       cu_source_file: Optional[str], cu_name: Optional[str] = None) -> None:
        """Process a DIE to extract source file information.
        
        Enhanced version that better distinguishes variable definitions from declarations.
        Uses compilation unit context and DWARF attributes to determine the most accurate
        source file location.
        """
        if not die.attributes:
            return

        # Extract all relevant attributes
        die_name = None
        decl_file = None
        die_address = None
        has_location = False
        is_declaration = False
        
        die_tag = die.tag if hasattr(die, 'tag') else None

        # Extract relevant attributes
        for attr_name, attr in die.attributes.items():
            if attr_name == 'DW_AT_name':
                if hasattr(attr, 'value'):
                    die_name = self._extract_string_value(attr.value)
            elif attr_name == 'DW_AT_decl_file':
                if hasattr(attr, 'value') and attr.value in file_entries:
                    decl_file = file_entries[attr.value]
            elif attr_name == 'DW_AT_declaration':
                is_declaration = True
            elif attr_name in ['DW_AT_low_pc', 'DW_AT_location']:
                has_location = True
                if hasattr(attr, 'value'):
                    try:
                        die_address = int(attr.value)
                    except (ValueError, TypeError):
                        pass

        # Determine which source file to use - simplified logic
        source_file = self._determine_best_source_file(
            is_declaration, cu_source_file, decl_file, die_name
        )
        
        # Store the mapping if we have useful information
        if die_name and source_file:
            # Primary: Store by address if available and valid
            if die_address is not None and die_address > 0:
                # Only store or overwrite if this is a definition (not a declaration)
                # or if we don't have an existing mapping
                if not is_declaration or die_address not in self._source_file_mapping['by_address']:
                    self._source_file_mapping['by_address'][die_address] = source_file

            # Secondary: Always store by compound key for fallback
            # Use 0 as placeholder for missing address to maintain consistent key structure
            address_key = die_address if die_address is not None else 0
            compound_key = (die_name, address_key)
            
            # For compound key, also prioritize definitions over declarations
            # Only overwrite existing mapping if this is a definition and the existing is a declaration
            if compound_key not in self._source_file_mapping['by_compound_key']:
                self._source_file_mapping['by_compound_key'][compound_key] = source_file
            elif not is_declaration:
                # This is a definition - overwrite any existing declaration
                self._source_file_mapping['by_compound_key'][compound_key] = source_file
            
    def _determine_best_source_file(self, is_declaration: bool, cu_source_file: Optional[str], 
                                  decl_file: Optional[str], die_name: Optional[str]) -> Optional[str]:
        """Determine the best source file to use based on available information.
        
        Simplified logic without heuristic guessing:
        1. For non-declarations in a CU: Use CU source file (likely defined here)
        2. For declarations pointing to system headers: Use CU source file  
        3. For declarations in a .c file's CU: Use CU source file (likely defined there)
        4. Otherwise: Use declaration file
        """
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
        """Check if a filename appears to be a system header rather than user code."""
        if not filename:
            return False
            
        # Common patterns for system headers that contain type definitions
        system_patterns = [
            'stdint', 'stdio', 'stdlib', 'string', 'unistd',
            'sys/', 'bits/', 'gnu/', 'linux/',
            '-uintn.h', '-intn.h'  # GCC-specific type header pattern
        ]
        
        filename_lower = filename.lower()
        return any(pattern in filename_lower for pattern in system_patterns)

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

    def get_metadata(self) -> ELFMetadata:
        """Extract ELF metadata"""
        try:
            with open(self.elf_path, 'rb') as f:
                elffile = ELFFile(f)
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
            raise ELFAnalysisError(f"Failed to parse ELF file {self.elf_path}: {e}") from e

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
            with open(self.elf_path, 'rb') as f:
                elffile = ELFFile(f)

                for section in elffile.iter_sections():
                    if not section.name or section.name.startswith('.debug'):
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
            with open(self.elf_path, 'rb') as f:
                elffile = ELFFile(f)

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

                        section_name = self._get_symbol_section_name(symbol, section_names)
                        if section_name.startswith('.debug'):
                            continue

                        symbol_type = self._get_symbol_type(symbol['st_info']['type'])
                        symbol_address = symbol['st_value']
                        symbols.append(Symbol(
                            name=symbol.name,
                            address=symbol_address,
                            size=symbol['st_size'],
                            type=symbol_type,
                            binding=self._get_symbol_binding(symbol['st_info']['bind']),
                            section=section_name,
                            source_file=self._extract_source_file(symbol.name, symbol_address, symbol_type),
                            visibility=""  # Could be extracted if needed
                        ))

        except (IOError, OSError, ELFError) as e:
            raise ELFAnalysisError(f"Failed to extract symbols: {e}") from e

        return symbols

    def get_program_headers(self) -> List[Dict[str, Any]]:
        """Extract program headers"""
        segments = []

        try:
            with open(self.elf_path, 'rb') as f:
                elffile = ELFFile(f)

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
            raise ELFAnalysisError(f"Failed to extract program headers: {e}") from e

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
        if name_lower.startswith('.data') or name_lower in ['.sdata', '.tdata']:
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

    def _get_symbol_section_name(self, symbol, section_names: Dict[int, str]) -> str:
        """Get section name for a symbol"""
        if symbol['st_shndx'] in ['SHN_UNDEF', 'SHN_ABS']:
            return ''

        try:
            section_idx = symbol['st_shndx']
            if isinstance(section_idx, int) and section_idx < len(section_names):
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

    def _extract_source_file(self, symbol_name: str, symbol_address: int = None, 
                           symbol_type: str = None) -> str:
        """Extract source file using .debug_line as primary source.
        
        Uses the clean approach: .debug_line provides compiler-verified source locations
        for all addresses that correspond to actual code/data in source files.
        
        Priority:
        1. Exact .debug_line lookup (most reliable)
        2. Nearby address search (handle alignment/optimization)
        3. Minimal DIE fallback only for edge cases
        """
        
        # Try .debug_line first for FUNC symbols (code)
        # For OBJECT symbols (data), skip .debug_line since it rarely has data addresses
        if symbol_address is not None and symbol_address > 0 and symbol_type == 'FUNC':
            
            # Priority 1: Exact .debug_line lookup
            if symbol_address in self._line_mapping:
                source_file = self._line_mapping[symbol_address]
                return os.path.basename(source_file)
            
            # Priority 2: Search nearby addresses (handle compiler alignment/optimization)
            # This is especially useful for functions where the symbol address might be 
            # slightly different from the first instruction address
            for offset in range(-100, 101):  # Search +/- 100 bytes, step by 1
                check_addr = symbol_address + offset
                if check_addr in self._line_mapping:
                    source_file = self._line_mapping[check_addr]
                    source_file_basename = os.path.basename(source_file)
                    
                    # IMPORTANT: If .debug_line points to a header file, but we have a DIE 
                    # definition in a .c file, prefer the .c file (same logic as for OBJECT symbols)
                    if source_file_basename.endswith('.h'):
                        # First try by_address mapping for exact address match
                        if symbol_address in self._source_file_mapping['by_address']:
                            die_source_file = self._source_file_mapping['by_address'][symbol_address]
                            if die_source_file.endswith('.c'):
                                return os.path.basename(die_source_file)
                        
                        # Try nearby DIE addresses (DIE and symbol might have slightly different addresses)
                        for die_offset in [-10, -5, -1, 1, 5, 10]:
                            check_die_addr = symbol_address + die_offset
                            if check_die_addr in self._source_file_mapping['by_address']:
                                die_source_file = self._source_file_mapping['by_address'][check_die_addr]
                                if die_source_file.endswith('.c'):
                                    return os.path.basename(die_source_file)
                        
                        # Also check compound key fallback
                        compound_key_fallback = (symbol_name, 0)
                        if compound_key_fallback in self._source_file_mapping['by_compound_key']:
                            die_source_file = self._source_file_mapping['by_compound_key'][compound_key_fallback]
                            if die_source_file.endswith('.c'):
                                return os.path.basename(die_source_file)
                    
                    return source_file_basename
        
        # DIE-based fallback for cases where .debug_line doesn't help
        # This is especially important for OBJECT symbols (global variables)
        
        # For OBJECT symbols with addresses, check by_address mapping first
        if symbol_type == 'OBJECT' and symbol_address is not None and symbol_address > 0:
            if symbol_address in self._source_file_mapping['by_address']:
                source_file = self._source_file_mapping['by_address'][symbol_address]
                return os.path.basename(source_file)
        
        # Check compound key fallback (for symbols without addresses in line info)
        compound_key_fallback = (symbol_name, 0)
        if compound_key_fallback in self._source_file_mapping['by_compound_key']:
            source_file = self._source_file_mapping['by_compound_key'][compound_key_fallback]
            return os.path.basename(source_file)
            
        # No source file information found
        return ""


class MemoryMapper:
    """Maps ELF sections to memory regions"""

    @staticmethod
    def map_sections_to_regions(sections: List[MemorySection],
                                memory_regions: Dict[str, MemoryRegion]) -> None:
        """Map sections to appropriate memory regions based on addresses"""
        for section in sections:
            region = MemoryMapper._find_region_by_address(section, memory_regions)
            if region:
                region.sections.append(section.__dict__)
            else:
                # If no address-based match, fall back to type-based mapping
                region = MemoryMapper._find_region_by_type(section, memory_regions)
                if region:
                    region.sections.append(section.__dict__)

    @staticmethod
    def _find_region_by_address(section: MemorySection,
                                memory_regions: Dict[str, MemoryRegion]) -> Optional[MemoryRegion]:
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
                             memory_regions: Dict[str, MemoryRegion]) -> Optional[MemoryRegion]:
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
            region.used_size = sum(section['size'] for section in region.sections)
            region.free_size = region.limit_size - region.used_size
            region.utilization_percent = (
                (region.used_size / region.limit_size * 100)
                if region.limit_size > 0 else 0.0
            )


class MemoryReportGenerator:  # pylint: disable=too-few-public-methods
    """Main class for generating memory reports"""

    def __init__(self, elf_path: str, memory_regions_data: Dict[str, Dict[str, Any]]):
        self.elf_analyzer = ELFAnalyzer(elf_path)
        self.memory_regions_data = memory_regions_data
        self.elf_path = elf_path

    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive memory report"""
        try:
            # Extract ELF data
            metadata = self.elf_analyzer.get_metadata()
            symbols = self.elf_analyzer.get_symbols()
            totals, sections = self.elf_analyzer.get_sections()
            program_headers = self.elf_analyzer.get_program_headers()

            # Convert memory regions data to MemoryRegion objects
            memory_regions = self._convert_to_memory_regions(self.memory_regions_data)

            # Map sections to regions based on addresses and calculate utilization
            MemoryMapper.map_sections_to_regions(sections, memory_regions)
            MemoryMapper.calculate_utilization(memory_regions)

            # Build final report
            return {
                'file_path': str(self.elf_path),
                'architecture': metadata.architecture,
                'entry_point': metadata.entry_point,
                'file_type': metadata.file_type,
                'machine': metadata.machine,
                'symbols': [symbol.__dict__ for symbol in symbols],
                'program_headers': program_headers,
                'memory_layout': {
                    name: region.to_dict() for name, region in memory_regions.items()
                }
            }

        except Exception as e:
            raise ELFAnalysisError(f"Failed to generate memory report: {e}") from e

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

        return parser

    @staticmethod
    def run(args: argparse.Namespace) -> None:
        """Execute the memory report generation"""
        try:
            # Load memory regions from JSON file
            with open(args.memory_regions, 'r', encoding='utf-8') as f:
                memory_regions_data = json.load(f)

            generator = MemoryReportGenerator(args.elf_path, memory_regions_data)
            report = generator.generate_report()

            # Write report to file
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2)

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
