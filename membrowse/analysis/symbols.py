#!/usr/bin/env python3
# pylint: disable=duplicate-code
"""
Symbol extraction and analysis from ELF files.

This module handles the extraction and analysis of symbols from ELF files,
including symbol filtering, type mapping, and source file resolution.
"""

import re
from typing import Dict, List, Tuple
from itanium_demangler import parse as cpp_demangle
from rust_demangler import demangle as rust_demangle
from elftools.common.exceptions import ELFError
from ..core.models import Symbol
from ..core.exceptions import SymbolExtractionError
from . import _cpp_demangle  # pylint: disable=unused-import  # import installs the missing-production patch for itanium_demangler


# GCC/LLVM compiler-generated suffixes appended to mangled symbol names.
# These are added by optimizations like partial inlining (.part), constant
# propagation (.constprop), interprocedural SRA (.isra), cold path splitting
# (.cold), and LTO (.lto_priv). They must be stripped before demangling.
_COMPILER_SUFFIX_RE = re.compile(
    r'(\.(part|constprop|isra|cold|lto_priv|llvm)\.\d+|\.(cold))$'
)

# Trailing v0 disambiguator like "[7d1f2a]" appended to Rust path segments
# when rust-demangler runs in verbose mode. The hash is meaningless for
# attribution.
_V0_DISAMBIG_RE = re.compile(r'\[[0-9a-f]+\]$')

# rustc's legacy mangling always appends a 16-hex-digit hash as the final
# path component, encoded as "17h<16 hex>E" in the mangled form. This is
# the disambiguator between otherwise identical C++ and legacy-Rust _ZN
# encodings: rust-demangler's legacy mode otherwise accepts any _ZN...E
# prefix and ignores trailing C++ arg bytes, which would misclassify a
# C++ symbol like _ZN3foo3barEv as Rust with crate "foo".
_RUST_LEGACY_HASH_RE = re.compile(r'17h[0-9a-f]{16}E')

# rustc emits each Rust crate as ``lib<name>-<hash>.rlib``; the 16-hex hash
# is deterministic but uninteresting for attribution. Accept both POSIX and
# Windows path separators — the LLD parser passes archive paths through
# as-is, so Windows toolchains produce backslashed paths.
_RLIB_NAME_RE = re.compile(
    r'(?:^|[\\/])lib([A-Za-z_][A-Za-z0-9_]*)-[0-9a-f]+\.rlib$')


def _crate_from_rlib_path(path: str) -> str:
    """Return the crate name encoded in a ``lib<crate>-<hash>.rlib`` archive.

    Non-Rust symbols (C/asm) linked from an .rlib lose the mangled-name
    attribution path, so we recover the owning crate from the archive
    filename. Returns '' for anything that isn't an .rlib.
    """
    if not path or not path.endswith('.rlib'):
        return ''
    match = _RLIB_NAME_RE.search(path)
    return match.group(1) if match else ''


def strip_compiler_suffix(name: str) -> str:
    """Strip GCC/LLVM compiler-generated suffixes from a symbol name.

    Returns the name without the suffix. If no suffix is present, returns
    the original name unchanged.
    """
    return _COMPILER_SUFFIX_RE.sub('', name)


def _extract_rust_crate(demangled: str) -> str:  # pylint: disable=too-many-return-statements,too-many-branches
    """Return the first path segment (owning crate) of a demangled Rust symbol.

    Rust monomorphizes generic code into the *consuming* crate's object file,
    so file-path attribution lumps dependency code into the root crate's
    ``<root>-<hash>.<cguN>.rcgu.o``. The true owner is the first path segment
    of the demangled name.

    Handles:
      - plain paths:       ``moka::common::deques::Deques::push`` → ``moka``
      - impl block:        ``<alloc::vec::Vec<T>>::push`` → ``alloc``
      - as-trait impl:     ``<alloc::vec::Vec<T> as core::ops::Drop>::drop``
                           → ``alloc``
      - generic as-trait:  ``<Func as minijinja::...::Function<Rv,(A,)>>::invoke``
                           → ``minijinja`` (type side is a bare generic, fall
                           through to the trait side)
      - v0 disambiguator:  ``alloc[7d1f2a]::raw_vec::...`` → ``alloc``

    Returns '' for anything that does not look like a fully-qualified Rust
    path. A bare identifier (``Func``) or a reference (``&T``) is rejected
    because it's not a crate — only paths containing ``::`` qualify.
    """
    if not demangled:
        return ''

    s = demangled.strip()

    # Impl block: <Inner>::method or <Inner as Trait>::method.
    if s.startswith('<'):
        depth = 0
        end = -1
        for i, ch in enumerate(s):
            if ch == '<':
                depth += 1
            elif ch == '>':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end < 0:
            return ''
        inner = s[1:end]

        # Locate " as " at depth 0 within inner — nested impls contain their
        # own ` as ` inside <...> which must be ignored.
        depth = 0
        as_pos = -1
        for i, ch in enumerate(inner):
            if ch == '<':
                depth += 1
            elif ch == '>':
                depth -= 1
            elif depth == 0 and inner[i:i + 4] == ' as ':
                as_pos = i
                break

        if as_pos >= 0:
            # Prefer the type side (left of " as ") when it resolves to a
            # real crate — this picks `alloc` from `<alloc::vec::Vec<T> as
            # core::ops::Drop>`. Fall back to the trait side for impls
            # whose type is a bare generic or reference (`Func`, `&T`) —
            # in that case the trait's crate is the meaningful attribution.
            type_crate = _extract_rust_crate(inner[:as_pos])
            if type_crate:
                return type_crate
            return _extract_rust_crate(inner[as_pos + 4:])
        return _extract_rust_crate(inner)

    # Plain path: require at least one "::" — a bare identifier or reference
    # is a generic/primitive, not a crate.
    sep = s.find('::')
    if sep < 0:
        return ''
    head = _V0_DISAMBIG_RE.sub('', s[:sep])

    if not head or any(c in head for c in ' \t\n<>()&*,'):
        return ''
    return head


class SymbolExtractor:  # pylint: disable=too-few-public-methods
    """Handles symbol extraction and analysis from ELF files"""

    def __init__(self, elffile):
        """Initialize with ELF file handle."""
        self.elffile = elffile

    def _demangle_symbol_name(self, name: str) -> str:
        """Demangle a C++ or Rust symbol name. See :meth:`_demangle_with_kind`.

        Returns only the demangled string — the ``kind`` is discarded. Callers
        that need to know which demangler succeeded (e.g. to extract a Rust
        crate) should use :meth:`_demangle_with_kind` directly.
        """
        demangled, _ = self._demangle_with_kind(name)
        return demangled

    def _demangle_with_kind(  # pylint: disable=too-many-return-statements
            self, name: str) -> Tuple[str, str]:
        """Demangle and also report which demangler handled the name.

        Supports:
        - C++ symbols (Itanium ABI, ``_Z`` prefix) via ``itanium_demangler``
        - Rust v0 symbols (``_R`` prefix) via ``rust_demangler``
        - Rust legacy symbols (``_ZN`` prefix) via ``rust_demangler``

        Args:
            name: Symbol name (potentially mangled).

        Returns:
            ``(demangled, kind)`` where ``kind`` is ``"rust"``, ``"cpp"``, or
            ``"none"``. For unmangled names, the original string is returned
            with kind ``"none"``. The kind is needed downstream to decide
            whether to run Rust-specific crate extraction — a C++ namespace
            like ``std::vector<int>::push_back`` would otherwise be
            mis-extracted as crate "std".
        """
        if not name:
            return name, 'none'

        # Strip compiler-generated suffixes (e.g. .part.0, .constprop.1)
        # before demangling, then re-append to the result.
        suffix_match = _COMPILER_SUFFIX_RE.search(name)
        if suffix_match:
            base_name = name[:suffix_match.start()]
            suffix = suffix_match.group()
        else:
            base_name = name
            suffix = ''

        # Rust v0 mangling (starts with _R).
        if base_name.startswith('_R'):
            rust_result = self._demangle_rust(base_name)
            if rust_result != base_name:
                return rust_result + suffix, 'rust'
            return name, 'none'

        # Could be C++ or legacy Rust (both use _ZN prefix). Only prefer
        # Rust when the mangled name carries the 17h<hash>E signature —
        # without that, a C++ symbol with trailing arg bytes like
        # _ZN3foo3barEv would demangle as legacy-Rust "foo::bar" and be
        # mis-attributed to a crate "foo".
        if base_name.startswith('_ZN'):
            if _RUST_LEGACY_HASH_RE.search(base_name):
                rust_result = self._demangle_rust(base_name)
                if rust_result != base_name:
                    return rust_result + suffix, 'rust'
            cpp_result = self._demangle_cpp(base_name)
            if cpp_result != base_name:
                return cpp_result + suffix, 'cpp'
            return name, 'none'

        # Standard C++ mangling (_Z but not _ZN).
        if base_name.startswith('_Z'):
            cpp_result = self._demangle_cpp(base_name)
            if cpp_result != base_name:
                return cpp_result + suffix, 'cpp'
            return name, 'none'

        return name, 'none'

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

    def extract_symbols(  # pylint: disable=too-many-locals,too-many-branches
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

                symbol_name, demangle_kind = self._demangle_with_kind(
                    symbol.name)
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

                # Attribute by crate for Rust projects. The demangled name is
                # the best source for Rust-mangled symbols (covers monomorph-
                # ized generics placed in the root crate's .rcgu.o); for C/asm
                # symbols linked from an .rlib we fall back to the crate name
                # encoded in the .rlib filename. Either way, object_file is
                # kept intact so raw provenance isn't lost.
                if demangle_kind == 'rust':
                    crate = _extract_rust_crate(symbol_name)
                    if crate:
                        archive = crate
                elif archive.endswith('.rlib'):
                    rlib_crate = _crate_from_rlib_path(archive)
                    if rlib_crate:
                        archive = rlib_crate

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
