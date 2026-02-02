#!/usr/bin/env python3
# pylint: disable=protected-access
"""
Unit tests for C++ and Rust symbol demangling functionality
"""

import unittest
from unittest.mock import Mock
from membrowse.analysis.symbols import SymbolExtractor


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


if __name__ == '__main__':
    unittest.main()
