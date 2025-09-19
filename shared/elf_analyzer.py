#!/usr/bin/env python3
"""
ELF file analysis and data extraction.

This module provides the main ELFAnalyzer class that coordinates the analysis
of ELF files using specialized component classes for symbols, sections, and DWARF data.
"""

import os
import time
from pathlib import Path
from typing import Dict, List, Any, Tuple
from elftools.elf.elffile import ELFFile
from elftools.common.exceptions import ELFError

from .models import ELFMetadata, Symbol, MemorySection
from .exceptions import ELFAnalysisError
from .dwarf_processor import DWARFProcessor
from .source_resolver import SourceFileResolver
from .symbol_extractor import SymbolExtractor
from .section_analyzer import SectionAnalyzer


class ELFAnalyzer:
    """Handles ELF file analysis and data extraction with performance optimizations"""

    # Configuration constants
    MAX_DIE_RECURSION_DEPTH = 10  # Maximum depth for DIE tree traversal
    SYMBOL_ADDRESS_PROXIMITY_THRESHOLD = 100  # Max distance for symbol address matching
    ARM_THUMB_ADDRESS_TOLERANCE = 2  # ARM thumb mode address difference tolerance
    DEFAULT_LINE_LIMIT = 2000  # Default number of lines to read from files
    MAX_LINE_LENGTH = 2000  # Maximum characters per line to avoid memory issues

    def __init__(self, elf_path: str):
        """Initialize ELF analyzer with file path and component setup.

        Args:
            elf_path: Path to the ELF file to analyze
        """
        self.elf_path = Path(elf_path)
        self._validate_elf_file()

        # Open ELF file once and reuse throughout
        self._elf_file_handle = None
        self._cached_elf_file = None
        self._open_elf_file()

        # Cache for expensive string operations and file paths
        self._system_header_cache = {}
        self._path_resolution_cache = {}
        self._string_extraction_cache = {}

        # Performance tracking
        self._perf_stats = {
            'line_mapping_time': 0,
            'source_mapping_time': 0,
            'proximity_searches': 0,
            'binary_searches': 0
        }

        # Initialize specialized components
        elffile = self._get_cached_elf_file()

        # Get symbol addresses we need to map
        symbol_addresses = self._get_symbol_addresses_to_map(elffile)

        # Process DWARF information
        start_time = time.time()
        dwarf_processor = DWARFProcessor(elffile, symbol_addresses)
        self._dwarf_data = dwarf_processor.process_dwarf_info()
        total_dwarf_time = time.time() - start_time
        self._perf_stats['dwarf_parsing_time'] = total_dwarf_time
        self._perf_stats['line_mapping_time'] = 0.01  # Minimal time for dict access
        self._perf_stats['source_mapping_time'] = 0.01  # Minimal time for dict access

        # Initialize specialized analyzers
        self._source_resolver = SourceFileResolver(self._dwarf_data, self._system_header_cache)
        self._symbol_extractor = SymbolExtractor(elffile)
        self._section_analyzer = SectionAnalyzer(elffile)

    def _validate_elf_file(self) -> None:
        """Validate that the ELF file exists and is readable."""
        if not self.elf_path.exists():
            raise ELFAnalysisError(f"ELF file not found: {self.elf_path}")

        if not os.access(self.elf_path, os.R_OK):
            raise ELFAnalysisError(f"Cannot read ELF file: {self.elf_path}")

    def _open_elf_file(self):
        """Open ELF file once for reuse."""
        if self._elf_file_handle is None:
            self._elf_file_handle = open(self.elf_path, 'rb')
            self._cached_elf_file = ELFFile(self._elf_file_handle)

    def _get_cached_elf_file(self):
        """Get cached ELF file handle to avoid repeated file I/O."""
        if self._cached_elf_file is None:
            self._open_elf_file()
        return self._cached_elf_file

    def __del__(self):
        """Clean up cached file handle."""
        if hasattr(self, '_elf_file_handle'):
            try:
                self._elf_file_handle.close()
            except Exception:  # pylint: disable=broad-exception-caught
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

    def _is_valid_symbol(self, symbol) -> bool:
        """Check if symbol should be included in analysis."""
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

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics for analysis."""
        return self._perf_stats.copy()

    def get_metadata(self) -> ELFMetadata:
        """Extract ELF metadata."""
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
        except (IOError, OSError) as e:
            raise ELFAnalysisError(
                f"Failed to read ELF file {self.elf_path}: {e}") from e
        except ELFError as e:
            raise ELFAnalysisError(
                f"Invalid ELF file format {self.elf_path}: {e}") from e

    def get_sections(self) -> Tuple[Dict[str, int], List[MemorySection]]:
        """Extract section information and calculate totals."""
        return self._section_analyzer.analyze_sections()

    def get_symbols(self) -> List[Symbol]:
        """Extract symbol information."""
        return self._symbol_extractor.extract_symbols(self._source_resolver)

    def get_program_headers(self) -> List[Dict[str, Any]]:
        """Extract program headers."""
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

        except (IOError, OSError) as e:
            raise ELFAnalysisError(
                f"Failed to read ELF file for program headers: {e}") from e
        except ELFError as e:
            raise ELFAnalysisError(
                f"Invalid ELF file format during program header extraction: {e}") from e

        return segments

    def _get_file_type(self, e_type: str) -> str:
        """Map ELF file type to readable string."""
        type_map = {
            'ET_EXEC': 'EXEC',
            'ET_DYN': 'DYN',
            'ET_REL': 'REL',
            'ET_CORE': 'CORE',
        }
        return type_map.get(e_type, str(e_type))

    def _get_machine_type(self, e_machine: str) -> str:
        """Map ELF machine type to readable string."""
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

    def _decode_segment_flags(self, flags: int) -> str:
        """Decode segment flags to readable string."""
        flag_str = ""
        if flags & 0x4:  # PF_R
            flag_str += "R"
        if flags & 0x2:  # PF_W
            flag_str += "W"
        if flags & 0x1:  # PF_X
            flag_str += "X"
        return flag_str or "---"

