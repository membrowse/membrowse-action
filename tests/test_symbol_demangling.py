#!/usr/bin/env python3
# pylint: disable=protected-access
"""
Unit tests for C++ and Rust symbol demangling functionality
"""

import unittest
from unittest.mock import Mock
from membrowse.analysis.symbols import SymbolExtractor
from membrowse.analysis.sources import SourceFileResolver


class TestSymbolDemangling(unittest.TestCase):
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
