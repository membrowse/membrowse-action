#!/usr/bin/env python3
# pylint: disable=duplicate-code
"""
Symbol extraction and analysis from ELF files.

This module handles the extraction and analysis of symbols from ELF files,
including symbol filtering, type mapping, and source file resolution.
"""

import re
from typing import Dict, List
from itanium_demangler import parse as cpp_demangle
from rust_demangler import demangle as rust_demangle
from elftools.common.exceptions import ELFError
from ..core.models import Symbol
from ..core.exceptions import SymbolExtractionError


# GCC/LLVM compiler-generated suffixes appended to mangled symbol names.
# These are added by optimizations like partial inlining (.part), constant
# propagation (.constprop), interprocedural SRA (.isra), cold path splitting
# (.cold), and LTO (.lto_priv). They must be stripped before demangling.
_COMPILER_SUFFIX_RE = re.compile(
    r'(\.(part|constprop|isra|cold|lto_priv|llvm)\.\d+|\.(cold))$'
)


class SymbolExtractor:  # pylint: disable=too-few-public-methods
    """Handles symbol extraction and analysis from ELF files"""

    def __init__(self, elffile):
        """Initialize with ELF file handle."""
        self.elffile = elffile

    def _demangle_symbol_name(self, name: str) -> str:
        """
        Demangle C++ and Rust symbol names.

        Supports:
        - C++ symbols (Itanium ABI, _Z prefix) via itanium_demangler
        - Rust v0 symbols (_R prefix) via rust_demangler
        - Rust legacy symbols (_ZN prefix) via rust_demangler

        Returns the demangled name, or the original name for C symbols
        or if demangling fails.

        Args:
            name: Symbol name (potentially mangled)

        Returns:
            Demangled symbol name, or original name if not mangled or on error
        """
        if not name:
            return name

        # Strip compiler-generated suffixes (e.g. .part.0, .constprop.1)
        # before demangling, then re-append to the result
        suffix_match = _COMPILER_SUFFIX_RE.search(name)
        if suffix_match:
            base_name = name[:suffix_match.start()]
            suffix = suffix_match.group()
        else:
            base_name = name
            suffix = ''

        # Rust v0 mangling (starts with _R)
        if base_name.startswith('_R'):
            return self._demangle_rust(base_name) + suffix

        # Could be C++ or legacy Rust (both use _ZN prefix)
        if base_name.startswith('_ZN'):
            # Try Rust first (legacy Rust uses _ZN prefix)
            rust_result = self._demangle_rust(base_name)
            if rust_result != base_name:
                return rust_result + suffix
            # Fall back to C++
            return self._demangle_cpp(base_name) + suffix

        # Standard C++ mangling (_Z but not _ZN)
        if base_name.startswith('_Z'):
            return self._demangle_cpp(base_name) + suffix

        return name

    def _demangle_rust(self, name: str) -> str:
        """Demangle Rust symbol names using rust_demangler."""
        try:
            result = rust_demangle(name)
            return result if result else name
        except Exception:  # pylint: disable=broad-exception-caught
            return name

    def _demangle_cpp(self, name: str) -> str:
        """Demangle C++ symbol names using itanium_demangler (pure Python)."""
        try:
            result = cpp_demangle(name)
            return str(result) if result is not None else name
        except Exception:  # pylint: disable=broad-exception-caught
            return name

    def extract_symbols(  # pylint: disable=too-many-locals
        self, source_resolver, map_resolver=None
    ) -> List[Symbol]:
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

                # Get archive/object file from map file resolver
                if map_resolver is not None:
                    archive, object_file = map_resolver.resolve(
                        symbol_address)
                else:
                    archive, object_file = '', ''


                symbols.append(Symbol(
                    name=symbol_name,
                    address=symbol_address,
                    size=symbol_size,
                    type=symbol_type,
                    binding=symbol_binding,
                    section=section_name,
                    source_file=source_file,
                    visibility=visibility,
                    archive=archive,
                    object_file=object_file
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
