#!/usr/bin/env python3
# pylint: disable=missing-function-docstring,protected-access
"""
Unit tests for C++ and Rust symbol demangling functionality
"""

import unittest
from unittest.mock import Mock
from membrowse.analysis.symbols import (
    SymbolExtractor, _extract_rust_crate, _crate_from_rlib_path)
from membrowse.analysis.sources import SourceFileResolver
from membrowse.analysis.mapfile import MapFileResolver


class TestSymbolDemangling(unittest.TestCase):  # pylint: disable=too-many-public-methods
    """Test C++ and Rust symbol name demangling"""

    def setUp(self):
        """Set up test fixtures"""
        # Create a mock ELF file for SymbolExtractor initialization
        self.mock_elffile = Mock()
        self.extractor = SymbolExtractor(self.mock_elffile)

    def test_demangle_cpp_function(self):
        """Test demangling of a simple C++ function"""
        mangled = "_Z3foov"
        demangled = self.extractor._demangle_symbol_name(mangled)
        self.assertEqual(demangled, "foo()")

    def test_demangle_cpp_function_with_args(self):
        """Test demangling of C++ function with arguments"""
        mangled = "_Z3addii"
        demangled = self.extractor._demangle_symbol_name(mangled)
        self.assertEqual(demangled, "add(int, int)")

    def test_demangle_cpp_namespace_function(self):
        """Test demangling of C++ namespaced function"""
        mangled = "_ZN9MyClass6methodEv"
        demangled = self.extractor._demangle_symbol_name(mangled)
        # Expected format: MyClass::method()
        self.assertIn("MyClass", demangled)
        self.assertIn("method", demangled)

    def test_c_symbol_unchanged(self):
        """Test that C symbols remain unchanged"""
        c_symbol = "my_c_function"
        result = self.extractor._demangle_symbol_name(c_symbol)
        self.assertEqual(result, c_symbol)

    def test_already_demangled_unchanged(self):
        """Test that already demangled names remain unchanged"""
        demangled = "foo()"
        result = self.extractor._demangle_symbol_name(demangled)
        self.assertEqual(result, demangled)

    def test_invalid_mangled_returns_original(self):
        """Test that invalid mangled symbols return the original name"""
        invalid = "_ZQQ"  # Invalid mangled name
        result = self.extractor._demangle_symbol_name(invalid)
        self.assertEqual(result, invalid)

    def test_empty_string(self):
        """Test handling of empty string"""
        result = self.extractor._demangle_symbol_name("")
        self.assertEqual(result, "")

    def test_special_characters(self):
        """Test handling of symbols with special characters"""
        symbol = "$special_symbol"
        result = self.extractor._demangle_symbol_name(symbol)
        self.assertEqual(result, symbol)

    def test_demangle_cpp_constructor(self):
        """Test demangling of C++ constructor"""
        mangled = "_ZN9MyClassC1Ev"
        demangled = self.extractor._demangle_symbol_name(mangled)
        # Should contain MyClass and constructor indication
        self.assertIn("MyClass", demangled)

    def test_demangle_cpp_destructor(self):
        """Test demangling of C++ destructor"""
        mangled = "_ZN9MyClassD1Ev"
        demangled = self.extractor._demangle_symbol_name(mangled)
        # Should contain MyClass and destructor indication
        self.assertIn("MyClass", demangled)

    # Rust symbol demangling tests

    def test_demangle_rust_v0_simple(self):
        """Test demangling of Rust v0 mangled symbol"""
        # Rust v0 mangling starts with _R
        mangled = "_RNvC6_123foo3bar"
        demangled = self.extractor._demangle_symbol_name(mangled)
        # Should demangle to something readable
        self.assertNotEqual(demangled, mangled)
        self.assertIn("bar", demangled)

    def test_demangle_rust_legacy_simple(self):
        """Test demangling of legacy Rust mangled symbol"""
        # Legacy Rust mangling uses _ZN prefix like C++
        mangled = "_ZN3foo3barE"
        demangled = self.extractor._demangle_symbol_name(mangled)
        # Should demangle to foo::bar
        self.assertEqual(demangled, "foo::bar")

    def test_demangle_rust_legacy_nested(self):
        """Test demangling of legacy Rust symbol with nested modules"""
        # Legacy Rust symbol with nested modules
        mangled = "_ZN4core3ptr13drop_in_placeE"
        demangled = self.extractor._demangle_symbol_name(mangled)
        # Should demangle to core::ptr::drop_in_place
        self.assertEqual(demangled, "core::ptr::drop_in_place")

    def test_demangle_rust_v0_function(self):
        """Test demangling of Rust v0 function symbol"""
        # Example v0 mangled name
        mangled = "_RNvNtCs123_4core3ptr13drop_in_place"
        demangled = self.extractor._demangle_symbol_name(mangled)
        # Should start with _R prefix and be demangled
        self.assertNotEqual(demangled, mangled)

    def test_rust_invalid_returns_original(self):
        """Test that invalid Rust-like symbols return original"""
        # Invalid _R prefixed symbol
        invalid = "_Rinvalid"
        result = self.extractor._demangle_symbol_name(invalid)
        # Should return original if demangling fails
        self.assertEqual(result, invalid)

    def test_rust_and_cpp_coexist(self):
        """Test that both Rust and C++ symbols can be demangled"""
        # C++ symbol
        cpp_mangled = "_Z3foov"
        cpp_demangled = self.extractor._demangle_symbol_name(cpp_mangled)
        self.assertEqual(cpp_demangled, "foo()")

        # Rust legacy symbol
        rust_mangled = "_ZN3foo3barE"
        rust_demangled = self.extractor._demangle_symbol_name(rust_mangled)
        self.assertEqual(rust_demangled, "foo::bar")

    # Compiler suffix stripping tests

    def test_demangle_cpp_with_part_suffix(self):
        """Test demangling C++ symbol with GCC .part.N suffix"""
        mangled = "_ZN6matrix6MatrixIfLj3ELj1EEaSERKS1_.part.0"
        demangled = self.extractor._demangle_symbol_name(mangled)
        self.assertIn("matrix::Matrix", demangled)
        self.assertIn("operator=", demangled)
        self.assertTrue(demangled.endswith(".part.0"))

    def test_demangle_cpp_with_constprop_suffix(self):
        """Test demangling C++ symbol with GCC .constprop.N suffix"""
        mangled = "_Z3foov.constprop.0"
        demangled = self.extractor._demangle_symbol_name(mangled)
        self.assertEqual(demangled, "foo().constprop.0")

    def test_demangle_cpp_with_isra_suffix(self):
        """Test demangling C++ symbol with GCC .isra.N suffix"""
        mangled = "_Z3addii.isra.0"
        demangled = self.extractor._demangle_symbol_name(mangled)
        self.assertEqual(demangled, "add(int, int).isra.0")

    def test_demangle_cpp_with_cold_suffix(self):
        """Test demangling C++ symbol with .cold suffix (no number)"""
        mangled = "_Z3foov.cold"
        demangled = self.extractor._demangle_symbol_name(mangled)
        self.assertEqual(demangled, "foo().cold")

    def test_demangle_cpp_with_lto_priv_suffix(self):
        """Test demangling C++ symbol with .lto_priv.N suffix"""
        mangled = "_Z3foov.lto_priv.0"
        demangled = self.extractor._demangle_symbol_name(mangled)
        self.assertEqual(demangled, "foo().lto_priv.0")

    def test_demangle_rust_with_compiler_suffix(self):
        """Test demangling Rust symbol with compiler suffix"""
        mangled = "_ZN3foo3barE.part.0"
        demangled = self.extractor._demangle_symbol_name(mangled)
        self.assertEqual(demangled, "foo::bar.part.0")

    def test_c_symbol_with_dot_unchanged(self):
        """Test that C symbols with dots are not mangled and stay unchanged"""
        c_symbol = "my_c_function.cold"
        result = self.extractor._demangle_symbol_name(c_symbol)
        self.assertEqual(result, c_symbol)


class TestRustCrateExtraction(unittest.TestCase):
    """Unit tests for _extract_rust_crate()."""

    def test_plain_path(self):
        self.assertEqual(
            _extract_rust_crate(
                'moka::common::deques::Deques::push_back'),
            'moka')

    def test_bare_identifier_rejected(self):
        """A path with no '::' is not a crate (likely a generic param).

        Real Rust symbols always have fully-qualified paths (``crate::path``).
        A bare identifier like ``Func`` or ``&T`` appearing in an impl block's
        type position is a generic type parameter or primitive — rejecting it
        lets the caller fall back to the trait side for attribution.
        """
        self.assertEqual(_extract_rust_crate('Func'), '')
        self.assertEqual(_extract_rust_crate('&T'), '')

    def test_legacy_trailing_hash_irrelevant(self):
        """Legacy Rust trailing ::h<hash> sits at the end; head still wins."""
        self.assertEqual(
            _extract_rust_crate('core::cell::RefCell::borrow::h0123abcdef'),
            'core')

    def test_impl_block(self):
        self.assertEqual(
            _extract_rust_crate('<alloc::vec::Vec<u8>>::push'),
            'alloc')

    def test_impl_block_as_trait(self):
        """Qualified type side wins over trait side: the Drop impl lives in
        the type's crate per Rust's orphan rules."""
        self.assertEqual(
            _extract_rust_crate(
                '<alloc::vec::Vec<T> as core::ops::Drop>::drop'),
            'alloc')

    def test_impl_block_generic_type_falls_back_to_trait(self):
        """When the type is a bare generic (no '::'), the trait's crate wins.

        Seen in real Rust binaries: ``<Func as minijinja::functions::Function
        <Rv,(A,)>>::invoke`` — ``Func`` is the user's type parameter, not a
        crate, so attribution belongs to ``minijinja`` (the trait source).
        """
        self.assertEqual(
            _extract_rust_crate(
                '<Func as minijinja::functions::Function<Rv,(A,)>>::invoke'),
            'minijinja')

    def test_impl_block_reference_falls_back_to_trait(self):
        """References (``&T``, ``&mut T``) aren't crates — take the trait."""
        self.assertEqual(
            _extract_rust_crate('<&T as core::fmt::Display>::fmt'),
            'core')

    def test_v0_disambiguator_stripped(self):
        self.assertEqual(
            _extract_rust_crate(
                'alloc[7d1f2a]::raw_vec::RawVec::reserve'),
            'alloc')

    def test_nested_impl_blocks(self):
        """Nested <...<...>...> still picks the innermost crate."""
        self.assertEqual(
            _extract_rust_crate(
                '<<hashbrown::map::HashMap<K, V> as core::iter::IntoIterator>'
                '::IntoIter as core::iter::Iterator>::next'),
            'hashbrown')

    def test_empty_returns_empty(self):
        self.assertEqual(_extract_rust_crate(''), '')

    def test_malformed_unclosed_bracket(self):
        self.assertEqual(_extract_rust_crate('<<broken'), '')

    def test_head_with_parens_rejected(self):
        """A head segment containing '(' is not a valid crate identifier.

        The function's contract is that callers pass Rust-demangled names,
        but it still defends against obviously-invalid input like a C++
        free function ('foo()') that slipped through misclassification.
        """
        self.assertEqual(_extract_rust_crate('foo()'), '')


class TestDemangleKind(unittest.TestCase):
    """Unit tests for SymbolExtractor._demangle_with_kind()."""

    def setUp(self):
        self.extractor = SymbolExtractor(Mock())

    def test_rust_v0(self):
        _, kind = self.extractor._demangle_with_kind(
            '_RNvNtCs123_4core3ptr13drop_in_place')
        self.assertEqual(kind, 'rust')

    def test_rust_legacy(self):
        """Legacy Rust classification requires the 17h<hash>E signature."""
        _, kind = self.extractor._demangle_with_kind(
            '_ZN4core3ptr13drop_in_place17h0123456789abcdefE')
        self.assertEqual(kind, 'rust')

    def test_legacy_zn_without_hash_is_cpp(self):
        """_ZN without the Rust hash signature is treated as C++.

        Guards against mis-attributing a C++ symbol like ``_ZN3foo3barEv``
        (C++ ``foo::bar()``) as Rust crate ``foo`` — rust-demangler's
        legacy mode accepts that prefix and ignores the trailing ``v``.
        """
        _, kind = self.extractor._demangle_with_kind('_ZN3foo3barEv')
        self.assertEqual(kind, 'cpp')

    def test_cpp_plain(self):
        _, kind = self.extractor._demangle_with_kind('_Z3foov')
        self.assertEqual(kind, 'cpp')

    def test_cpp_template_method(self):
        """A real C++ template method must classify as cpp, not rust."""
        _, kind = self.extractor._demangle_with_kind(
            '_ZN3std6vectorIiE9push_backERi')
        self.assertEqual(kind, 'cpp')

    def test_c_symbol_none(self):
        _, kind = self.extractor._demangle_with_kind('my_c_function')
        self.assertEqual(kind, 'none')

    def test_empty_none(self):
        _, kind = self.extractor._demangle_with_kind('')
        self.assertEqual(kind, 'none')

    def test_invalid_mangled_none(self):
        _, kind = self.extractor._demangle_with_kind('_ZQQ')
        self.assertEqual(kind, 'none')


class TestCrateFromRlibPath(unittest.TestCase):
    """Unit tests for _crate_from_rlib_path()."""

    def test_absolute_path(self):
        self.assertEqual(
            _crate_from_rlib_path(
                '/tmp/rustc123/libring-2b451148a8a9a487.rlib'),
            'ring')

    def test_windows_path(self):
        """Backslash path separators must be recognized — the LLD parser
        preserves Windows archive paths verbatim."""
        self.assertEqual(
            _crate_from_rlib_path(
                r'C:\tmp\rustc123\libring-2b451148a8a9a487.rlib'),
            'ring')

    def test_bare_filename(self):
        self.assertEqual(
            _crate_from_rlib_path('libcompiler_builtins-abc123def456.rlib'),
            'compiler_builtins')

    def test_crate_with_underscore(self):
        self.assertEqual(
            _crate_from_rlib_path(
                '/deps/libserde_core-0123456789abcdef.rlib'),
            'serde_core')

    def test_dot_a_archive_rejected(self):
        self.assertEqual(_crate_from_rlib_path('libhal.a'), '')

    def test_empty_rejected(self):
        self.assertEqual(_crate_from_rlib_path(''), '')

    def test_malformed_rlib_rejected(self):
        """An .rlib without the standard ``lib<name>-<hash>`` pattern returns ''."""
        self.assertEqual(_crate_from_rlib_path('weird.rlib'), '')


class _FakeSymbol:  # pylint: disable=too-few-public-methods
    """Minimal pyelftools-Symbol stand-in for extract_symbols tests."""

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self, name, address, size, sym_type='STT_FUNC',
                 binding='STB_GLOBAL', shndx=1):
        self.name = name
        self._fields = {
            'st_info': {'type': sym_type, 'bind': binding},
            'st_value': address,
            'st_size': size,
            'st_shndx': shndx,
            'st_other': {'visibility': 'STV_DEFAULT'},
        }

    def __getitem__(self, key):
        return self._fields[key]


class TestExtractSymbolsRustAttribution(unittest.TestCase):
    """End-to-end check: Rust symbols get archive overwritten with crate."""

    def _build_extractor(self, fake_symbols, section_names=None):
        mock_elffile = Mock()
        # .symtab lookup
        symtab = Mock()
        symtab.iter_symbols = Mock(return_value=iter(fake_symbols))
        mock_elffile.get_section_by_name = Mock(return_value=symtab)
        # iter_sections → provides section index-to-name mapping
        sections = []
        for name in (section_names or ['', '.text']):
            sec = Mock()
            sec.name = name
            sections.append(sec)
        mock_elffile.iter_sections = Mock(return_value=iter(sections))
        return SymbolExtractor(mock_elffile)

    def _null_source_resolver(self):
        resolver = Mock(spec=SourceFileResolver)
        resolver.extract_source_file = Mock(return_value='')
        return resolver

    def test_rust_symbol_archive_overwritten_with_crate(self):
        """A Rust legacy-mangled symbol gets its archive set to the crate,
        while object_file from the map resolver is preserved."""
        # Hashed legacy form: demangles to
        # moka::common::deques::Deques::push_back → crate 'moka'.
        sym = _FakeSymbol(
            name='_ZN4moka6common6deques6Deques9push_back17h0123456789abcdefE',
            address=0x1000, size=64)
        map_resolver = MapFileResolver({
            0x1000: ('/some/santa-abc.rlib', 'santa-abc.1.rcgu.o'),
        })
        extractor = self._build_extractor([sym])
        symbols = extractor.extract_symbols(
            self._null_source_resolver(), map_resolver=map_resolver)
        self.assertEqual(len(symbols), 1)
        # Archive overwritten with crate name.
        self.assertEqual(symbols[0].archive, 'moka')
        # Raw object filename from the map is preserved.
        self.assertEqual(symbols[0].object_file, 'santa-abc.1.rcgu.o')

    def test_cpp_symbol_archive_untouched(self):
        """A C++ symbol keeps whatever archive the map resolver returned."""
        sym = _FakeSymbol(
            name='_ZN3std6vectorIiE9push_backERi',
            address=0x2000, size=32)
        map_resolver = MapFileResolver({
            0x2000: ('libhal.a', 'vec.o'),
        })
        extractor = self._build_extractor([sym])
        symbols = extractor.extract_symbols(
            self._null_source_resolver(), map_resolver=map_resolver)
        self.assertEqual(symbols[0].archive, 'libhal.a')
        self.assertEqual(symbols[0].object_file, 'vec.o')

    def test_cpp_namespace_not_attributed_as_rust_crate(self):
        """A C++ symbol like ``foo::bar()`` (``_ZN3foo3barEv``) must not be
        mis-classified as Rust and have its archive overwritten with 'foo'.

        rust-demangler's legacy mode would otherwise parse the ``_ZN3foo3barE``
        prefix and ignore the trailing ``v``. The guard is the requirement
        for a ``17h<hash>E`` signature.
        """
        sym = _FakeSymbol(name='_ZN3foo3barEv', address=0x2500, size=24)
        map_resolver = MapFileResolver({
            0x2500: ('libcore.a', 'foo.o'),
        })
        extractor = self._build_extractor([sym])
        symbols = extractor.extract_symbols(
            self._null_source_resolver(), map_resolver=map_resolver)
        self.assertEqual(symbols[0].archive, 'libcore.a')
        self.assertEqual(symbols[0].object_file, 'foo.o')

    def test_rust_symbol_without_crate_keeps_map_archive(self):
        """If crate extraction fails, archive falls back to the map row."""
        # _R prefix but malformed — rust_demangle fails → kind='none', archive kept.
        sym = _FakeSymbol(name='_Rinvalid', address=0x3000, size=16)
        map_resolver = MapFileResolver({
            0x3000: ('libfoo.rlib', 'foo.rcgu.o'),
        })
        extractor = self._build_extractor([sym])
        symbols = extractor.extract_symbols(
            self._null_source_resolver(), map_resolver=map_resolver)
        self.assertEqual(symbols[0].archive, 'libfoo.rlib')

    def test_c_symbol_unaffected(self):
        """Plain C symbols stay with their map-derived archive."""
        sym = _FakeSymbol(name='my_c_function', address=0x4000, size=48)
        map_resolver = MapFileResolver({
            0x4000: ('', 'main.o'),
        })
        extractor = self._build_extractor([sym])
        symbols = extractor.extract_symbols(
            self._null_source_resolver(), map_resolver=map_resolver)
        self.assertEqual(symbols[0].archive, '')
        self.assertEqual(symbols[0].object_file, 'main.o')

    def test_c_symbol_in_rlib_normalized_to_crate(self):
        """A C symbol linked from an .rlib gets its archive reduced to the
        crate name extracted from the rlib filename.

        This covers the ring/openssl/etc case where crypto primitives are
        C or assembly but are shipped as part of a Rust crate. Without
        this, those symbols land in a bucket named
        ``/tmp/rustc.../libring-<hash>.rlib`` that doesn't merge with the
        Rust symbols of the same crate.
        """
        sym = _FakeSymbol(name='fiat_25519_carry_mul',
                          address=0x5000, size=677)
        map_resolver = MapFileResolver({
            0x5000: (
                '/tmp/rustc123/libring-2b451148a8a9a487.rlib',
                '25ac62e5b3c53843-curve25519.o',
            ),
        })
        extractor = self._build_extractor([sym])
        symbols = extractor.extract_symbols(
            self._null_source_resolver(), map_resolver=map_resolver)
        self.assertEqual(symbols[0].archive, 'ring')
        self.assertEqual(
            symbols[0].object_file, '25ac62e5b3c53843-curve25519.o')


class TestCompilerSuffixSourceResolution(unittest.TestCase):
    """Test that suffixed demangled symbols still resolve source files via DWARF."""

    def _make_resolver(self, symbol_to_file, address_to_file=None,
                       address_to_cu_file=None, static_symbol_mappings=None):
        dwarf_data = {
            'symbol_to_file': symbol_to_file,
            'address_to_file': address_to_file or {},
            'address_to_cu_file': address_to_cu_file or {},
        }
        if static_symbol_mappings is not None:
            dwarf_data['static_symbol_mappings'] = static_symbol_mappings
        return SourceFileResolver(dwarf_data, system_header_cache={})

    def test_suffixed_symbol_resolves_via_stripped_name(self):
        """A demangled name with .part.0 should hit a DWARF entry keyed by the unsuffixed name."""
        resolver = self._make_resolver({
            ('foo()', 0x1000): '/src/foo.c',
        })
        # Exact match works
        self.assertEqual(resolver.extract_source_file('foo()', 'FUNC', 0x1000), 'foo.c')
        # Suffixed variant also resolves to the same file
        self.assertEqual(resolver.extract_source_file('foo().part.0', 'FUNC', 0x1000), 'foo.c')

    def test_suffixed_symbol_resolves_constprop(self):
        """A .constprop.N suffix should also fall back to the unsuffixed DWARF key."""
        resolver = self._make_resolver({
            ('add(int, int)', 0x2000): '/src/math.c',
        })
        self.assertEqual(
            resolver.extract_source_file('add(int, int).constprop.0', 'FUNC', 0x2000), 'math.c')

    def test_suffixed_symbol_fallback_with_address_zero(self):
        """Suffix stripping should also work in the address=0 fallback path."""
        resolver = self._make_resolver({
            ('my_global', 0): '/src/globals.c',
        })
        # No address match, falls through to (name, 0) fallback
        self.assertEqual(
            resolver.extract_source_file('my_global.part.0', 'OBJECT', 0x9999), 'globals.c')

    def test_exact_match_preferred_over_stripped(self):
        """If DWARF has an entry for the exact suffixed name, use it (no stripping needed)."""
        resolver = self._make_resolver({
            ('foo().part.0', 0x1000): '/src/foo_split.c',
            ('foo()', 0x1000): '/src/foo.c',
        })
        self.assertEqual(
            resolver.extract_source_file('foo().part.0', 'FUNC', 0x1000), 'foo_split.c')

    def test_unsuffixed_symbol_unaffected(self):
        """Normal symbols without compiler suffixes still resolve normally."""
        resolver = self._make_resolver({
            ('bar()', 0x3000): '/src/bar.c',
        })
        self.assertEqual(resolver.extract_source_file('bar()', 'FUNC', 0x3000), 'bar.c')

    def test_suffixed_static_object_resolves(self):
        """Static OBJECT symbols with compiler suffixes should resolve via stripped name."""
        resolver = self._make_resolver(
            symbol_to_file={},
            static_symbol_mappings=[
                # (symbol_name, cu_source_file, best_source_file)
                ('my_static_var', '/src/module.c', '/src/module.c'),
            ],
            address_to_cu_file={0x4000: '/src/module.c'},
        )
        self.assertEqual(
            resolver.extract_source_file('my_static_var.part.0', 'OBJECT', 0x4000), 'module.c')


if __name__ == '__main__':
    unittest.main()
