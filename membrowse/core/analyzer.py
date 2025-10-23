#!/usr/bin/env python3
# pylint: disable=duplicate-code
"""
ELF file analysis and data extraction.

This module provides the main ELFAnalyzer class that coordinates the analysis
of ELF files using specialized component classes for symbols, sections, and DWARF data.
"""

import os
from pathlib import Path
from typing import Dict, List, Any, Tuple
from elftools.elf.elffile import ELFFile
from elftools.common.exceptions import ELFError

from .models import ELFMetadata, Symbol, MemorySection
from .exceptions import ELFAnalysisError
from ..analysis.dwarf import DWARFProcessor
from ..analysis.sources import SourceFileResolver
from ..analysis.symbols import SymbolExtractor
from ..analysis.sections import SectionAnalyzer


class ELFAnalyzer:  # pylint: disable=too-many-instance-attributes
    """Handles ELF file analysis and data extraction with performance optimizations"""

    def __init__(self, elf_path: str, skip_line_program: bool = False):
        """Initialize ELF analyzer with file path and component setup.

        Args:
            elf_path: Path to the ELF file to analyze
            skip_line_program: Skip DWARF line program processing for faster analysis
        """
        self.elf_path = Path(elf_path)
        self.skip_line_program = skip_line_program
        self._validate_elf_file()

        # Open ELF file once and reuse throughout
        # pylint: disable=consider-using-with
        self._elf_file_handle = open(self.elf_path, 'rb')
        self.elffile = ELFFile(self._elf_file_handle)

        # Cache for expensive string operations and file paths
        self._system_header_cache = {}

        # Get symbol addresses we need to map
        symbol_addresses = self._get_symbol_addresses_to_map(self.elffile)

        # Detect architecture for address tolerance
        machine = self.elffile.header['e_machine']

        # Process DWARF information
        dwarf_processor = DWARFProcessor(
            self.elffile,
            symbol_addresses,
            skip_line_program=skip_line_program,
            machine=machine
        )
        self._dwarf_data = dwarf_processor.process_dwarf_info()

        # Initialize specialized analyzers
        self._source_resolver = SourceFileResolver(
            self._dwarf_data, self._system_header_cache)
        self._symbol_extractor = SymbolExtractor(self.elffile)
        self._section_analyzer = SectionAnalyzer(self.elffile)

    def _validate_elf_file(self) -> None:
        """Validate that the ELF file exists and is readable."""
        if not self.elf_path.exists():
            raise ELFAnalysisError(f"ELF file not found: {self.elf_path}")

        if not os.access(self.elf_path, os.R_OK):
            raise ELFAnalysisError(f"Cannot read ELF file: {self.elf_path}")

    def __del__(self):
        """Clean up file handle."""
        if hasattr(self, '_elf_file_handle'):
            self._elf_file_handle.close()

    def _get_symbol_addresses_to_map(self, elffile) -> set:
        """Get set of symbol addresses that we actually need to map."""
        symbol_addresses = set()

        symbol_table_section = elffile.get_section_by_name('.symtab')
        if not symbol_table_section:
            return symbol_addresses

        for symbol in symbol_table_section.iter_symbols():
            if self._is_valid_symbol(symbol):
                symbol_addresses.add(symbol['st_value'])

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

    def get_metadata(self) -> ELFMetadata:
        """Extract ELF metadata."""

        header = self.elffile.header

        return ELFMetadata(
            architecture=f"ELF{self.elffile.elfclass}",
            file_type=header['e_type'],
            machine=header['e_machine'],
            entry_point=header['e_entry'],
            bit_width=self.elffile.elfclass,
            endianness='little' if self.elffile.little_endian else 'big'
        )

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
            for segment in self.elffile.iter_segments():
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
