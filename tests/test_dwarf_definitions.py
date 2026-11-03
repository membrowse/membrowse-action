#!/usr/bin/env python3
"""
DIEs without an address that a symbol may be matched to by name alone.
"""

import unittest
from types import SimpleNamespace

from membrowse.analysis.dwarf import _is_file_scope_definition


def die(tag, parent_tag='DW_TAG_compile_unit', **attributes):
    """A DIE with a parent of parent_tag (None: no parent)."""
    parent = SimpleNamespace(tag=parent_tag) if parent_tag else None
    return SimpleNamespace(tag=tag, attributes=attributes, get_parent=lambda: parent)


class TestFileScopeDefinition(unittest.TestCase):
    """_is_file_scope_definition"""

    def test_file_scope_variable_and_function(self):
        """Variables and functions at CU or namespace scope"""
        self.assertTrue(_is_file_scope_definition(die('DW_TAG_variable'), None))
        self.assertTrue(_is_file_scope_definition(die('DW_TAG_subprogram'), None))
        self.assertTrue(_is_file_scope_definition(
            die('DW_TAG_variable', 'DW_TAG_namespace'), None))
        self.assertTrue(_is_file_scope_definition(die('DW_TAG_variable', None), None))

    def test_locals_and_parameters(self):
        """A local or a parameter names no symbol"""
        self.assertFalse(_is_file_scope_definition(
            die('DW_TAG_variable', 'DW_TAG_subprogram'), None))
        self.assertFalse(_is_file_scope_definition(
            die('DW_TAG_variable', 'DW_TAG_lexical_block'), None))
        self.assertFalse(_is_file_scope_definition(
            die('DW_TAG_formal_parameter', 'DW_TAG_subprogram'), None))

    def test_members(self):
        """A member of a structure or class"""
        self.assertFalse(_is_file_scope_definition(
            die('DW_TAG_variable', 'DW_TAG_structure_type'), None))

    def test_cpp_definitions(self):
        """Named through a specification, or with a linkage name"""
        spec = die('DW_TAG_subprogram', 'DW_TAG_class_type')
        self.assertFalse(_is_file_scope_definition(die('DW_TAG_subprogram'), spec))
        self.assertFalse(_is_file_scope_definition(
            die('DW_TAG_subprogram', DW_AT_linkage_name='_ZNSs3endEv'), None))
        self.assertFalse(_is_file_scope_definition(
            die('DW_TAG_variable', DW_AT_MIPS_linkage_name='_ZN1a1bE'), None))


if __name__ == '__main__':
    unittest.main()
