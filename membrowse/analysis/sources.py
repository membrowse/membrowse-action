#!/usr/bin/env python3
"""
Source file resolution for symbols using DWARF debug information.

This module handles the complex logic of mapping symbols to their source files
using DWARF debug information, with optimizations for performance and accuracy.
"""

import os
import posixpath
import re
import bisect
import logging
from typing import Any, Dict, Iterable, Optional

from .paths import case_insensitive, is_abs, to_posix
from .symbols import strip_compiler_suffix

logger = logging.getLogger(__name__)

# Rust Codegen Unit hash filenames (e.g. "defmt_rtt.2465299265768a95-cgu.0")
# These are compiler internals, not real source files.
_CGU_HASH_PATTERN = re.compile(r'^.+\.[0-9a-f]+-cgu\.\d+$')


def _under(path: str, root: str) -> bool:
    """Whether normalized `path` lies under the slash-terminated `root`,
    ignoring case when either comes from a Windows file system."""
    if case_insensitive(path, root):
        return path.lower().startswith(root.lower())
    return path.startswith(root)


def _source_roots(source_root: Optional[str]) -> tuple:
    """The prefixes a DWARF path is matched against, slash-terminated: the
    root as given and, when it exists, as resolved, since the compiler
    records the path it was invoked with, which may go through a symlink
    (or a short name on Windows) the root does not."""
    if not source_root:
        return ()
    given = to_posix(source_root)
    if not is_abs(given):
        given = to_posix(os.path.abspath(source_root))
    candidates = [given]
    if os.path.exists(source_root):
        candidates.append(to_posix(os.path.realpath(source_root)))
    roots = []
    for candidate in candidates:
        prefix = posixpath.normpath(candidate).rstrip('/') + '/'
        if prefix not in roots:
            roots.append(prefix)
    return tuple(roots)


def relative_source_path(path: str, roots: Iterable[str]) -> Optional[str]:
    """The path a source file is reported under when a source root applies:
    relative to the first of `roots` (slash-terminated prefixes) that
    contains it, or as recorded when the compiler already recorded it
    relative to the build (``-ffile-prefix-map=/path/repo=.`` and similar,
    where no root can match). None when no root applies, so the caller
    falls back to the basename and toolchain and system files stay short
    and build-location independent."""
    normalized = posixpath.normpath(to_posix(path))
    for root in roots:
        if _under(normalized, root):
            return normalized[len(root):]
    if roots and not is_abs(normalized) and not normalized.startswith('../'):
        return normalized
    return None


class SourceFileResolver:  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """Handles source file resolution logic for symbols using DWARF debug information"""

    def __init__(self, dwarf_data: Dict[str, Any],
                 system_header_cache: Dict[str, bool],
                 source_root: Optional[str] = None):
        """Initialize with DWARF data dictionaries and system header cache.

        Args:
            dwarf_data: Dictionaries from DWARFProcessor
            system_header_cache: Cache shared with the analyzer
            source_root: Directory that resolved source files are reported
                relative to; files outside it, or all files when None, are
                reported by basename
        """
        self.dwarf_data = dwarf_data
        self.system_header_cache = system_header_cache
        self.used_static_mappings = {}  # Track which static mappings have been used

        # Pre-build static symbol mappings lookup for O(1) access
        self._static_symbol_lookup = {}
        self._basename_cache = {}  # Cache basename computations
        self.source_root = source_root
        self._source_roots = _source_roots(source_root)
        self._source_name_cache = {}  # DWARF path -> reported name
        self._paths_under_root = 0  # distinct DWARF paths the root matched
        self._paths_outside_root = 0  # distinct absolute DWARF paths it missed
        # Lazily built by _find_nearby_address
        self._sorted_addresses = None
        self._sequences = []  # (start, end, CU offset) by start
        self._sequence_starts = []
        self._by_end = []  # the same sequences by end
        self._sequence_ends = []
        if 'static_symbol_mappings' in dwarf_data:
            for mapping in dwarf_data['static_symbol_mappings']:
                symbol_name = mapping[0]
                self._static_symbol_lookup.setdefault(symbol_name, []).append(mapping)

    def _get_basename(self, source_file: str) -> str:
        """Get basename with caching to avoid repeated os.path.basename calls."""
        if source_file not in self._basename_cache:
            self._basename_cache[source_file] = os.path.basename(source_file)
        return self._basename_cache[source_file]

    def _source_name(self, source_file: str) -> str:
        """The name a resolved DWARF path is reported under (cached): relative
        to the source root when inside it, else its basename."""
        name = self._source_name_cache.get(source_file)
        if name is None:
            name = relative_source_path(source_file, self._source_roots)
            if name is not None:
                self._paths_under_root += 1
            else:
                normalized = posixpath.normpath(to_posix(source_file))
                name = posixpath.basename(normalized)
                if self._source_roots and is_abs(normalized):
                    self._paths_outside_root += 1
            self._source_name_cache[source_file] = name
        return name

    def log_source_root_coverage(self) -> None:
        """Warn when a source root was configured but no resolved DWARF path
        lay under it: the firmware was built from another checkout (a
        container mount such as /app or /__w, or a path-mapped build), and
        every symbol has fallen back to its basename."""
        if self._source_roots and self._paths_outside_root and not self._paths_under_root:
            logger.warning(
                "No source file lies under the source root %s (%d distinct DWARF "
                "paths); symbols are reported by basename. Pass --source-root with "
                "the directory the firmware was built from.",
                self.source_root, self._paths_outside_root)

    def extract_source_file(
            self,
            symbol_name: str,
            symbol_type: str,
            symbol_address: int = None) -> str:
        """Extract source file using pre-built DWARF dictionaries.

        This method uses fast dictionary lookups instead of parsing DWARF data.
        The dictionaries are populated once during initialization for maximum performance.

        Args:
            symbol_name: Name of the symbol
            symbol_type: Type of the symbol (FUNC, OBJECT, etc.)
            symbol_address: Address of the symbol (optional)

        Returns:
            The source file relative to the source root (its basename when
            outside the root or no root is set), or empty string if not found
        """
        result = self._resolve_source_file(symbol_name, symbol_type, symbol_address)
        if result and _CGU_HASH_PATTERN.match(result):
            return ""
        return result

    def extract_source_line(self, symbol_address: Optional[int],
                            symbol_name: Optional[str] = None,
                            source_file: Optional[str] = None) -> int:
        """Return the source line of a symbol, a line in source_file.

        The line of the line program row covering the address, the same
        answer ``nm -l`` gives, when that row is in source_file (the name
        extract_source_file reported). Otherwise, as for data, code without
        line rows, or a function whose first row is inlined from another
        file, the DW_AT_decl_line of the symbol's DIE when it declares the
        symbol in source_file. 0 when neither is known, and when source_file
        is empty (no file found). When source_file is None the row's line is
        returned whatever its file.
        """
        if not self.dwarf_data or symbol_address is None:
            return 0
        row = self._line_row(symbol_address)
        if row is not None:
            row_file, row_line = row
            if row_line and (source_file is None
                             or self._source_name(row_file) == source_file):
                return row_line
        if symbol_name and source_file:
            decl = self._symbol_decl(symbol_name, symbol_address)
            if decl is not None and self._source_name(decl[0]) == source_file:
                return decl[1]
        return 0

    def _line_row(self, address: int) -> Optional[tuple]:
        """(file, line) of the line row covering address, None if no row does."""
        addr_to_line = self.dwarf_data.get('address_to_line')
        if not addr_to_line:
            return None
        if address not in addr_to_line:
            address = self._covering_row(address)
            if address is None:
                return None
        return self.dwarf_data['address_to_file'].get(address), addr_to_line.get(address, 0)

    def _symbol_decl(self, symbol_name: str, symbol_address: int) -> Optional[tuple]:
        """(DW_AT_decl_file, DW_AT_decl_line) of the symbol's DIE, None if unknown.

        The DIE at the symbol's address, else a defining DIE without an
        address (stored under address 0), such as a weak stub's.
        """
        symbol_to_decl = self.dwarf_data.get('symbol_to_decl')
        if not symbol_to_decl:
            return None
        names = (symbol_name, strip_compiler_suffix(symbol_name))
        for address in (symbol_address, 0):
            for name in names:
                decl = symbol_to_decl.get((name, address))
                if decl is not None:
                    return decl
        return None

    def _resolve_source_file(  # pylint: disable=too-many-return-statements,too-many-branches
            self,
            symbol_name: str,
            symbol_type: str,
            symbol_address: int = None) -> str:
        """Internal source file resolution with priority-based fallback chain."""
        # Use dictionary-based lookups for maximum performance
        if not self.dwarf_data:
            return ""  # No DWARF data available

        # Priority 1: Direct symbol lookup from DWARF dictionaries (DIE-based,
        # most reliable)
        # DWARF DIE names don't include compiler suffixes (.part.0, etc.),
        # so try the stripped name if the original key misses.
        symbol_key = (symbol_name, symbol_address or 0)
        if symbol_key not in self.dwarf_data['symbol_to_file']:
            stripped = strip_compiler_suffix(symbol_name)
            if stripped != symbol_name:
                symbol_key = (stripped, symbol_address or 0)

        if symbol_key in self.dwarf_data['symbol_to_file']:
            source_file = self.dwarf_data['symbol_to_file'][symbol_key]

            # For FUNC symbols, if DIE points to .c file, trust it over line program
            # This handles cases with inlined functions from headers
            if symbol_type == 'FUNC' and source_file.endswith('.c'):
                return self._source_name(source_file)

            # For .h files, check if we should prefer the CU source file
            if (source_file.endswith('.h')
                    and symbol_address is not None and symbol_address > 0):
                if symbol_address in self.dwarf_data['address_to_cu_file']:
                    cu_source_file = self.dwarf_data['address_to_cu_file'][symbol_address]
                    if cu_source_file and cu_source_file.endswith('.c'):
                        return self._source_name(cu_source_file)

            return self._source_name(source_file)

        # Priority 1c: For static variables, use CU-based matching from DWARF
        # processing
        static_lookup_name = symbol_name
        if static_lookup_name not in self._static_symbol_lookup:
            stripped = strip_compiler_suffix(symbol_name)
            if stripped != symbol_name:
                static_lookup_name = stripped
        if symbol_type == 'OBJECT' and static_lookup_name in self._static_symbol_lookup:
            result = self._resolve_static_symbol(static_lookup_name, symbol_address)
            if result:
                return result

        # Priority 2: Address-based lookup for FUNC symbols (fallback)
        # A function linked at 0 has rows only when a code symbol is there
        # (see is_dead_sequence), so address 0 is looked up as well.
        if symbol_address is not None and symbol_type == 'FUNC':
            return self._resolve_by_address(symbol_address)

        # Priority 3: Fallback lookups for OBJECT symbols and edge cases
        return self._resolve_fallback(symbol_name, symbol_address)

    def _resolve_static_symbol(self, symbol_name: str, symbol_address: int) -> str:
        """Resolve static symbols with duplicate names using CU-based matching.

        Args:
            symbol_name: Name of the static symbol
            symbol_address: Address of the symbol

        Returns:
            The reported source file name, or empty string if not found
        """
        static_mappings = self._static_symbol_lookup[symbol_name]
        if not static_mappings:
            return ""

        # If we have an address, try CU-based matching first
        if symbol_address is not None and symbol_address > 0:
            symbol_cu = self.dwarf_data['address_to_cu_file'].get(symbol_address)
            if symbol_cu:
                # Find mapping with matching CU
                symbol_cu_basename = self._get_basename(symbol_cu)
                for mapping in static_mappings:
                    mapping_cu = mapping[1]  # cu_source_file
                    if mapping_cu and self._get_basename(mapping_cu) == symbol_cu_basename:
                        source_file = mapping[2]  # best_source_file
                        return self._source_name(source_file)

            # If no CU match, fall back to sequential matching
            if symbol_name not in self.used_static_mappings:
                self.used_static_mappings[symbol_name] = 0

            index = self.used_static_mappings[symbol_name]
            if index < len(static_mappings):
                mapping = static_mappings[index]
                self.used_static_mappings[symbol_name] += 1
                source_file = mapping[2]
                return self._source_name(source_file)

        # Fallback to first mapping if we have mappings but no address
        source_file = static_mappings[0][2]
        return self._source_name(source_file)

    def _resolve_by_address(self, symbol_address: int) -> str:
        """Resolve source file by symbol address."""
        # Exact address lookup
        if symbol_address in self.dwarf_data['address_to_file']:
            return self._prefer_cu_source(
                self.dwarf_data['address_to_file'][symbol_address], symbol_address)

        # Proximity search using optimized algorithm
        nearby_addr = self._find_nearby_address(symbol_address)
        if nearby_addr is not None:
            return self._prefer_cu_source(
                self.dwarf_data['address_to_file'][nearby_addr],
                symbol_address, nearby_addr)

        return ""

    def _prefer_cu_source(self, source_file: str, *addresses: int) -> str:
        """The reported name of a line-program file, preferring the CU .c
        file of the first of addresses that has one over a header (inlined
        code). The symbol's own address goes first, then the row's."""
        if source_file.endswith('.h'):
            address_to_cu_file = self.dwarf_data['address_to_cu_file']
            for address in addresses:
                cu_source_file = address_to_cu_file.get(address)
                if cu_source_file:
                    if cu_source_file.endswith('.c'):
                        return self._source_name(cu_source_file)
                    break
        return self._source_name(source_file)

    def _resolve_fallback(self, symbol_name: str, symbol_address: int) -> str:
        """Fallback resolution methods for edge cases."""
        # Try address-based CU mapping
        if symbol_address is not None and symbol_address > 0:
            if symbol_address in self.dwarf_data['address_to_cu_file']:
                source_file = self.dwarf_data['address_to_cu_file'][symbol_address]
                return self._source_name(source_file)

        # Try symbol with address=0 fallback
        fallback_key = (symbol_name, 0)
        if fallback_key not in self.dwarf_data['symbol_to_file']:
            stripped = strip_compiler_suffix(symbol_name)
            if stripped != symbol_name:
                fallback_key = (stripped, 0)
        if fallback_key in self.dwarf_data['symbol_to_file']:
            source_file = self.dwarf_data['symbol_to_file'][fallback_key]
            return self._source_name(source_file)

        # No source file information found
        return ""

    def _build_address_index(self) -> None:
        """Sorted row addresses and line sequences for the address lookups."""
        if self._sorted_addresses is not None:
            return
        self._sorted_addresses = sorted(self.dwarf_data['address_to_file'])
        self._sequences = sorted(self.dwarf_data.get('line_sequences', ()))
        self._sequence_starts = [seq[0] for seq in self._sequences]
        self._by_end = sorted(self._sequences, key=lambda seq: seq[1])
        self._sequence_ends = [seq[1] for seq in self._by_end]

    def _row_at_or_before(self, address: int, floor: int) -> Optional[int]:
        """The last row address in [floor, address], None if there is none."""
        j = bisect.bisect_right(self._sorted_addresses, address) - 1
        if j < 0 or self._sorted_addresses[j] < floor:
            return None
        return self._sorted_addresses[j]

    def _covering_row(self, target_address: int) -> Optional[int]:
        """Address of the line row that covers target_address, None if no row does.

        That is the last row of the line sequence containing the address,
        at or before it. The stored sequences do not overlap (see
        select_live_sequences), so the one starting last at or before the
        address is the only one that can contain it. A sequence whose first
        rows name no known file has no row at its start, and a row before
        its start is another sequence's, often another CU's: none is used.
        """
        self._build_address_index()
        i = bisect.bisect_right(self._sequence_starts, target_address) - 1
        if i < 0 or target_address >= self._sequences[i][1]:
            return None
        return self._row_at_or_before(target_address, self._sequences[i][0])

    def _find_nearby_address(
            self,
            target_address: int,
            max_distance: int = 100) -> Optional[int]:
        """Address of a line row whose file can stand for target_address.

        The covering row when a line sequence contains the address. In a gap
        between two sequences of the same CU (functions without line rows,
        such as empty weak handlers), the last row of the sequence ending
        before the gap, if that sequence ends within max_distance of the
        address. The neighbours are the sequence ending last at or before
        the address and the one starting first after it. Past the end of a
        CU's code, or before its start, the nearest row belongs to other
        code and is not used.
        """
        row = self._covering_row(target_address)
        if row is not None:
            return row
        i = bisect.bisect_right(self._sequence_ends, target_address) - 1
        j = bisect.bisect_right(self._sequence_starts, target_address)
        if i < 0 or j >= len(self._sequences):
            return None
        before, after = self._by_end[i], self._sequences[j]
        if before[2] != after[2] or target_address - before[1] > max_distance:
            return None
        return self._row_at_or_before(before[1] - 1, before[0])
