#!/usr/bin/env python3
# pylint: disable=duplicate-code
"""
Symbol extraction and analysis from ELF files.

This module handles the extraction and analysis of symbols from ELF files,
including symbol filtering, type mapping, and source file resolution.
"""

from typing import Dict, List
import cxxfilt
from elftools.common.exceptions import ELFError
from ..core.models import Symbol
from ..core.exceptions import SymbolExtractionError


class SymbolExtractor:  # pylint: disable=too-few-public-methods
    """Handles symbol extraction and analysis from ELF files"""

    def __init__(self, elffile):
        """Initialize with ELF file handle."""
        self.elffile = elffile

    def _demangle_symbol_name(self, name: str) -> str:
        """
        Demangle C++ symbol names using cxxfilt.

        Returns the demangled name for C++ symbols, or the original name
        for C symbols or if demangling fails.

        Args:
            name: Symbol name (potentially mangled)

        Returns:
            Demangled symbol name, or original name if not mangled or on error
        """
        try:
            # cxxfilt.demangle with external_only=True (default) checks for _Z prefix
            # and returns the original name unchanged if it's not a mangled symbol
            return cxxfilt.demangle(name)
        except cxxfilt.InvalidName:
            # Return original name for malformed mangled symbols
            return name

    def extract_symbols(self, source_resolver) -> List[Symbol]:
        """Extract symbol information from ELF file with source file mapping."""
        symbols = []

        try:
            symbol_table_section = self.elffile.get_section_by_name('.symtab')
            if not symbol_table_section:
                return symbols

            # Build section name mapping for efficiency
            section_names = self._build_section_name_mapping()

            for symbol in symbol_table_section.iter_symbols():
                if not self._is_valid_symbol(symbol):
                    continue

                symbol_name = self._demangle_symbol_name(symbol.name)
                symbol_type = self._get_symbol_type(symbol['st_info']['type'])
                symbol_binding = self._get_symbol_binding(
                    symbol['st_info']['bind'])
                symbol_address = symbol['st_value']
                symbol_size = symbol['st_size']
                section_name = self._get_symbol_section_name(
                    symbol, section_names)

                # Get source file using the source resolver
                source_file = source_resolver.extract_source_file(
                    symbol_name, symbol_type, symbol_address
                )

                # Get symbol visibility
                visibility = 'DEFAULT'  # Default value
                try:
                    if hasattr(
                            symbol,
                            'st_other') and hasattr(
                            symbol['st_other'],
                            'visibility'):
                        visibility = symbol['st_other']['visibility'].replace(
                            'STV_', '')
                except (KeyError, AttributeError):
                    pass

                symbols.append(Symbol(
                    name=symbol_name,
                    address=symbol_address,
                    size=symbol_size,
                    type=symbol_type,
                    binding=symbol_binding,
                    section=section_name,
                    source_file=source_file,
                    visibility=visibility
                ))

        except (IOError, OSError) as e:
            raise SymbolExtractionError(
                f"Failed to read ELF file for symbol extraction: {e}") from e
        except ELFError as e:
            raise SymbolExtractionError(
                f"Invalid ELF file format during symbol extraction: {e}") from e

        return symbols

    def _build_section_name_mapping(self) -> Dict[int, str]:
        """Build mapping of section indices to section names for efficient lookup."""
        section_names = {}
        try:
            for i, section in enumerate(self.elffile.iter_sections()):
                section_names[i] = section.name
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        return section_names

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

    def _get_symbol_section_name(
            self, symbol, section_names: Dict[int, str]) -> str:
        """Get section name for a symbol."""
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
        """Map symbol type to readable string."""
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
        """Map symbol binding to readable string."""
        binding_map = {
            'STB_LOCAL': 'LOCAL',
            'STB_GLOBAL': 'GLOBAL',
            'STB_WEAK': 'WEAK'
        }
        return binding_map.get(symbol_binding, symbol_binding)

    def _get_symbol_visibility(self, st_other: int) -> str:
        """Map symbol visibility to readable string."""
        visibility = st_other & 0x3  # Lower 2 bits contain visibility
        visibility_map = {
            0: 'DEFAULT',  # STV_DEFAULT
            1: 'INTERNAL',  # STV_INTERNAL
            2: 'HIDDEN',   # STV_HIDDEN
            3: 'PROTECTED'  # STV_PROTECTED
        }
        return visibility_map.get(visibility, 'DEFAULT')
