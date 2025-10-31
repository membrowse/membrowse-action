#!/usr/bin/env python3
# pylint: disable=protected-access
"""
Unit tests for C++ symbol demangling functionality
"""

import unittest
from unittest.mock import Mock
from membrowse.analysis.symbols import SymbolExtractor


class TestSymbolDemangling(unittest.TestCase):
    """Test C++ symbol name demangling"""

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


if __name__ == '__main__':
    unittest.main()
