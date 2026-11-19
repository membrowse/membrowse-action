#!/usr/bin/env python3
# pylint: disable=missing-function-docstring,protected-access
"""
C++ symbols that the demangler currently leaves mangled.

Collected from an EdgeTX firmware build (radio TX16S, arm-none-eabi-gcc 14,
-Os): 1852 of its 10377 C++ function symbols failed to demangle. Each test
below covers one missing production of the Itanium ABI grammar and uses
real symbols from that build, plus a minimal hand-written one where useful.
The expected substrings come from ``c++filt``; whole strings are not
compared because membrowse renders some names in its own style
(``{ctor}``, ``{lambda(void)#1}``).
"""

import unittest
from unittest.mock import Mock

from membrowse.analysis.symbols import SymbolExtractor


class TestCppDemanglingGaps(unittest.TestCase):
    """Itanium ABI productions missing from the C++ demangler."""

    def setUp(self):
        self.extractor = SymbolExtractor(Mock())

    def assert_demangles(self, mangled, *parts):
        demangled = self.extractor._demangle_symbol_name(mangled)
        self.assertNotEqual(demangled, mangled, "symbol was left mangled")
        for part in parts:
            self.assertIn(part, demangled)

    # -- GCC "unified" constructor/destructor (C4 / D4) -------------------
    # GCC emits C4/D4 when the complete and base object variants are
    # identical (common at -Os). 968 EdgeTX symbols use them, mostly
    # std::function handlers for lambdas defined in constructors.

    def test_unified_constructor(self):
        # c++filt: Foo::Foo()
        self.assert_demangles("_ZN3FooC4Ev", "Foo::")

    def test_unified_destructor(self):
        # c++filt: Foo::~Foo()
        self.assert_demangles("_ZN3FooD4Ev", "Foo::")

    def test_lambda_in_unified_constructor(self):
        # c++filt: std::_Function_handler<void (), ViewMain::ViewMain()::
        #          {lambda()#1}>::_M_invoke(std::_Any_data const&)
        self.assert_demangles(
            "_ZNSt17_Function_handlerIFvvEZN8ViewMainC4EvEUlvE_E9_M_invoke"
            "ERKSt9_Any_data",
            "std::_Function_handler", "ViewMain::", "_M_invoke")

    def test_lambda_in_unified_constructor_with_args(self):
        # c++filt: std::_Function_handler<void (), Keyboard::Keyboard(int)::
        #          {lambda()#1}>::_M_invoke(std::_Any_data const&)
        self.assert_demangles(
            "_ZNSt17_Function_handlerIFvvEZN8KeyboardC4EiEUlvE_E9_M_invoke"
            "ERKSt9_Any_data",
            "Keyboard::", "_M_invoke")

    # -- Closure type scoped to a variable (M <closure>) -------------------
    # Lambdas in the initializer of a namespace-scope static variable are
    # mangled as <data-member-prefix> "M" followed by the closure type.
    # 875 EdgeTX symbols (Lua binding tables).

    def test_lambda_in_static_variable(self):
        # c++filt: lvgllib_entries::{lambda(lua_State*)#1}::_FUN(lua_State*)
        self.assert_demangles(
            "_ZNL15lvgllib_entriesMUlP9lua_StateE_4_FUNES1_",
            "lvgllib_entries::", "lua_State*", "_FUN")

    def test_lambda_in_static_variable_numbered(self):
        # c++filt: lvgllib_entries::{lambda(lua_State*)#8}::_FUN(lua_State*)
        self.assert_demangles(
            "_ZNL15lvgllib_entriesMUlP9lua_StateE6_4_FUNES1_",
            "lvgllib_entries::", "#8", "_FUN")

    def test_lambda_in_static_variable_call_operator(self):
        # c++filt: toolsMenuItems::{lambda()#1}::operator()() const
        self.assert_demangles(
            "_ZNKL14toolsMenuItemsMUlvE_clEv", "toolsMenuItems::", "operator()")

    # -- Array types -------------------------------------------------------

    def test_array_bound_from_template_param(self):
        # c++filt: char* getSourceString<16u>(char (&) [16u], long, bool)
        self.assert_demangles(
            "_Z15getSourceStringILj16EEPcRAT__clb", "getSourceString", "char")

    def test_array_of_unknown_bound_with_pack_expansion(self):
        # c++filt: void std::vector<std::__cxx11::basic_string<...>, ...>
        #          ::_M_realloc_append<char const (&) []>(char const (&) [])
        self.assert_demangles(
            "_ZNSt6vectorINSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE"
            "SaIS5_EE17_M_realloc_appendIJRA_KcEEEvDpOT_",
            "std::vector", "_M_realloc_append")

    # A template parameter inside an expression (array bound, X...E) is not
    # a substitution candidate; registering it shifts every later S<n>_.
    # Symbols from g++; the argument lists match c++filt's.

    def test_array_bound_template_param_not_substitutable(self):
        # c++filt: void f<16>(char (&) [16], double*, double*)
        self.assert_demangles(
            "_Z1fILi16EEvRAT__cPdS2_", "(&)[(int)16], double*, double*)")

    def test_array_bound_expression_not_substitutable(self):
        # c++filt: void h<16>(char (&) [(16)+(1)], double*, double*)
        self.assert_demangles(
            "_Z1hILi16EEvRAplT_Li1E_cPdS2_", "], double*, double*)")

    def test_template_arg_expression_not_substitutable(self):
        # c++filt: void g<1>(A<(1)+(1)>, double*, double*)
        self.assert_demangles(
            "_Z1gILi1EEv1AIXplT_Li1EEEPdS2_", ">, double*, double*)")

    def test_array_bound_and_element_template_params(self):
        # c++filt: void m<char, 16>(char (&) [16], char*, double*, double*)
        self.assert_demangles(
            "_Z1mIcLi16EEvRAT0__T_PS0_PdS4_",
            "char(&)[(int)16], char*, double*, double*)")

    # -- Pointer-to-member-function type (M <class> <function type>) -------

    def test_pointer_to_member_function_in_template_args(self):
        # c++filt: std::_Function_handler<unsigned char (), std::_Bind<
        #          unsigned char (pxx2::ReceiverButton::*(pxx2::ReceiverButton*))()>
        #          >::_M_manager(std::_Any_data&, std::_Any_data const&,
        #          std::_Manager_operation)
        self.assert_demangles(
            "_ZNSt17_Function_handlerIFhvESt5_BindIFMN4pxx214ReceiverButtonEFhvE"
            "PS3_EEE10_M_managerERSt9_Any_dataRKSA_St18_Manager_operation",
            "std::_Function_handler", "pxx2::ReceiverButton", "_M_manager")


if __name__ == '__main__':
    unittest.main()
