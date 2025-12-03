#!/usr/bin/env python3
"""
Test cases for static variable source file mapping in DWARF debug information.

This module tests various scenarios where static variables are defined in different
locations and ensures they are correctly mapped to their source files.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from membrowse.core.generator import ReportGenerator

# Add shared module to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestStaticVariableSourceMapping(unittest.TestCase):
    """Test cases for static variable source file mapping scenarios"""

    def setUp(self):
        """Set up test environment"""
        self.test_dir = Path(__file__).parent / "static_test"
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        """Clean up test environment"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def _compile_test_case(
            self,
            source_dir: Path,
            output_name: str = "a.out",
            compiler: str = "gcc",
            extra_flags: list = None) -> Path:
        """
        Compile a test case using gcc or other compiler with debug information.

        Args:
            source_dir: Directory containing source files
            output_name: Name of output executable
            compiler: Compiler to use (default: gcc)
            extra_flags: Additional compiler flags (e.g., ["-gdwarf-2"])

        Returns:
            Path to compiled executable
        """
        # Copy source files to temp directory
        temp_source_dir = self.temp_dir / source_dir.name
        shutil.copytree(source_dir, temp_source_dir)

        # Find all .c files
        c_files = list(temp_source_dir.glob("*.c"))
        if not c_files:
            raise ValueError(f"No .c files found in {source_dir}")

        # Compile with debug information
        output_path = temp_source_dir / output_name
        cmd = [compiler, "-g"]
        if extra_flags:
            cmd.extend(extra_flags)
        cmd.extend(["-o", str(output_path)] + [str(f) for f in c_files])

        result = subprocess.run(
            cmd,
            cwd=temp_source_dir,
            capture_output=True,
            text=True,
            check=False)
        if result.returncode != 0:
            raise RuntimeError(f"Compilation failed: {result.stderr}")

        return output_path

    def _generate_memory_report(self, elf_path: Path) -> Dict[str, Any]:
        """
        Generate memory report using the ReportGenerator.

        Args:
            elf_path: Path to ELF file

        Returns:
            Memory report as dictionary
        """
        # Generate report directly using ReportGenerator
        # No memory regions needed for these tests (only testing symbol extraction)
        generator = ReportGenerator(
            str(elf_path),
            memory_regions_data=None,
            skip_line_program=False
        )
        report = generator.generate_report()
        return report

    def _find_foo_symbols(
            self, report: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Find all foo symbols in the memory report.

        Args:
            report: Memory report dictionary

        Returns:
            List of foo symbol dictionaries
        """
        symbols = report.get('symbols', [])
        foo_symbols = [s for s in symbols if s.get('name') == 'foo']
        return foo_symbols

    def test_01_header_static_variable_mapping(self):
        """
        Test Case 1: Static variable defined in header file

        Setup:
        - c.h: static int foo = 42;
        - a.c: #include "c.h", uses foo
        - b.c: #include "c.h", uses foo

        Expected: Both foo symbols should map to "c.h"
        """
        source_dir = self.test_dir / "header_static"

        # Compile test case
        elf_path = self._compile_test_case(source_dir)

        # Generate report
        report = self._generate_memory_report(elf_path)

        # Find foo symbols
        foo_symbols = self._find_foo_symbols(report)

        # Verify results
        self.assertEqual(
            len(foo_symbols),
            2,
            "Should have 2 foo symbols (one per compilation unit)")

        for symbol in foo_symbols:
            self.assertEqual(
                symbol['source_file'],
                'c.h',
                f"foo symbol should be mapped to c.h, got {symbol['source_file']}")
            self.assertEqual(
                symbol['type'],
                'OBJECT',
                "foo should be an OBJECT type symbol")
            self.assertEqual(
                symbol['binding'],
                'LOCAL',
                "static variable should have LOCAL binding")

    def test_02_separate_static_variable_mapping(self):
        """
        Test Case 2: Static variables with same name in different source files

        Setup:
        - a.c: static int foo = 0;
        - b.c: static int foo = 0;

        Expected: First foo maps to "a.c", second foo maps to "b.c"
        """
        source_dir = self.test_dir / "c_static"

        # Compile test case
        elf_path = self._compile_test_case(source_dir)

        # Generate report
        report = self._generate_memory_report(elf_path)

        # Find foo symbols
        foo_symbols = self._find_foo_symbols(report)

        # Verify results
        self.assertEqual(
            len(foo_symbols),
            2,
            "Should have 2 foo symbols (one per source file)")

        # Verify both source files are present (order-independent)
        source_files = {s['source_file'] for s in foo_symbols}
        self.assertEqual(
            source_files,
            {'a.c', 'b.c'},
            f"Should have foo from both a.c and b.c, got {source_files}")

        for symbol in foo_symbols:
            self.assertEqual(
                symbol['type'],
                'OBJECT',
                "foo should be an OBJECT type symbol")
            self.assertEqual(
                symbol['binding'],
                'LOCAL',
                "static variable should have LOCAL binding")

    def test_03_header_declaration_vs_definition_mapping(self):
        """
        Test Case 3: Variable declared in header but defined in source file

        Setup:
        - c.h: extern int foo; (declaration only)
        - a.c: int foo = 0; (definition)
        - b.c: #include "c.h", uses foo

        Expected: foo symbol should map to "a.c" (where it's defined),
        not "c.h" (where it's declared)
        """
        source_dir = self.test_dir / "header_declaration_static"

        # Compile test case
        elf_path = self._compile_test_case(source_dir)

        # Generate report
        report = self._generate_memory_report(elf_path)

        # Find foo symbols
        foo_symbols = self._find_foo_symbols(report)

        # Verify results
        self.assertEqual(
            len(foo_symbols),
            1,
            "Should have 1 foo symbol (global variable)")

        symbol = foo_symbols[0]
        self.assertEqual(
            symbol['source_file'],
            'a.c',
            f"foo should be mapped to a.c (definition), not c.h "
            f"(declaration). Got {symbol['source_file']}")
        self.assertEqual(
            symbol['type'],
            'OBJECT',
            "foo should be an OBJECT type symbol")
        self.assertEqual(
            symbol['binding'],
            'GLOBAL',
            "global variable should have GLOBAL binding")

    def test_04_static_function_mapping(self):
        """
        Test Case 4: Static functions with same name in different source files

        Setup:
        - a.c: static int helper_function(int x) { return x * 2; }
        - b.c: static int helper_function(int x) { return x * 3; }

        Expected: First helper_function maps to "a.c", second maps to "b.c"
        """
        source_dir = self.test_dir / "c_static_functions"

        # Compile test case
        elf_path = self._compile_test_case(source_dir)

        # Generate report
        report = self._generate_memory_report(elf_path)

        # Find helper_function symbols
        symbols = report.get('symbols', [])
        helper_symbols = [s for s in symbols if s.get(
            'name') == 'helper_function']

        # Verify results
        self.assertEqual(
            len(helper_symbols),
            2,
            "Should have 2 helper_function symbols (one per source file)")

        # Verify both source files are present (order-independent)
        source_files = {s['source_file'] for s in helper_symbols}
        self.assertEqual(
            source_files,
            {'a.c', 'b.c'},
            f"Should have helper_function from both a.c and b.c, got {source_files}")

        for symbol in helper_symbols:
            self.assertEqual(
                symbol['type'],
                'FUNC',
                "helper_function should be a FUNC type symbol")
            self.assertEqual(
                symbol['binding'],
                'LOCAL',
                "static function should have LOCAL binding")

    def test_05_comprehensive_symbol_verification(self):
        """
        Test Case 5: Comprehensive verification of all test cases

        Runs all test cases and verifies that the symbol extraction and mapping
        works correctly across different scenarios.
        """
        test_cases = [
            {
                'name': 'header_static',
                'expected_count': 2,
                'expected_mapping': ['c.h', 'c.h'],
                'expected_binding': 'LOCAL'
            },
            {
                'name': 'c_static',
                'expected_count': 2,
                'expected_mapping': ['a.c', 'b.c'],
                'expected_binding': 'LOCAL'
            },
            {
                'name': 'header_declaration_static',
                'expected_count': 1,
                'expected_mapping': ['a.c'],
                'expected_binding': 'GLOBAL'
            }
        ]

        for test_case in test_cases:
            with self.subTest(case=test_case['name']):
                source_dir = self.test_dir / test_case['name']

                # Compile test case
                elf_path = self._compile_test_case(source_dir)

                # Generate report
                report = self._generate_memory_report(elf_path)

                # Find foo symbols
                foo_symbols = self._find_foo_symbols(report)

                # Verify count
                self.assertEqual(
                    len(foo_symbols),
                    test_case['expected_count'],
                    f"Case {test_case['name']}: Expected {test_case['expected_count']} foo symbols")

                # Verify mappings (order-independent using Counter for multisets)
                actual_sources = [s['source_file'] for s in foo_symbols]
                expected_sources = test_case['expected_mapping']
                self.assertEqual(
                    Counter(actual_sources),
                    Counter(expected_sources),
                    f"Case {test_case['name']}: Expected sources "
                    f"{expected_sources}, got {actual_sources}")

                # Verify binding for all symbols
                for symbol in foo_symbols:
                    self.assertEqual(
                        symbol['binding'],
                        test_case['expected_binding'],
                        f"Case {test_case['name']}: Symbol should have "
                        f"{test_case['expected_binding']} binding")

    def test_06_compilation_prerequisite_check(self):
        """
        Test Case 6: Verify GCC compilation prerequisites

        Ensures that GCC is available and can compile the test cases.
        """
        # Check if gcc is available
        result = subprocess.run(['gcc', '--version'],
                                capture_output=True, text=True, check=False)
        self.assertEqual(
            result.returncode,
            0,
            "GCC compiler must be available for tests")

        # Verify we can compile a simple test case
        simple_source = self.temp_dir / "test.c"
        with open(simple_source, 'w', encoding='utf-8') as f:
            f.write("int main() { return 0; }")

        output = self.temp_dir / "test"
        result = subprocess.run(['gcc',
                                 '-g',
                                 '-o',
                                 str(output),
                                 str(simple_source)],
                                capture_output=True,
                                text=True,
                                check=False)
        self.assertEqual(
            result.returncode,
            0,
            f"Simple compilation should succeed: {result.stderr}")
        self.assertTrue(output.exists(), "Compiled output should exist")

    def test_09_bss_section_static_variable_mapping(self):
        """
        Test Case 9: Static variables in .bss section (uninitialized)

        Verifies that uninitialized static variables in the .bss section
        are correctly mapped to their source files.

        Setup:
        - a.c: static int uninitialized_var; static char buffer[256];
        - b.c: static int uninitialized_var; static char buffer[256];

        Expected: All static BSS variables correctly map to their source files
        """
        source_dir = self.test_dir / "bss_static"

        # Compile test case
        elf_path = self._compile_test_case(source_dir)

        # Generate report
        report = self._generate_memory_report(elf_path)

        # Find uninitialized_var symbols in .bss section
        symbols = report.get('symbols', [])
        uninit_symbols = [
            s for s in symbols
            if s.get('name') == 'uninitialized_var'
            and s.get('binding') == 'LOCAL'
            and '.bss' in s.get('section', '')
        ]

        # Verify results
        self.assertEqual(
            len(uninit_symbols),
            2,
            "Should have 2 uninitialized_var symbols in .bss section")

        # Sort symbols by address for consistent ordering
        uninit_symbols.sort(key=lambda s: s['address'])

        # Verify both are mapped to correct source files
        source_files = [s['source_file'] for s in uninit_symbols]
        self.assertIn(
            'a.c',
            source_files,
            "Should have uninitialized_var from a.c")
        self.assertIn(
            'b.c',
            source_files,
            "Should have uninitialized_var from b.c")

        # Find buffer symbols in .bss section
        buffer_symbols = [
            s for s in symbols
            if s.get('name') == 'buffer'
            and s.get('binding') == 'LOCAL'
            and '.bss' in s.get('section', '')
        ]

        # Verify buffer symbols
        self.assertEqual(
            len(buffer_symbols),
            2,
            "Should have 2 buffer symbols in .bss section")

        buffer_symbols.sort(key=lambda s: s['address'])
        buffer_source_files = [s['source_file'] for s in buffer_symbols]
        self.assertIn(
            'a.c',
            buffer_source_files,
            "Should have buffer from a.c")
        self.assertIn(
            'b.c',
            buffer_source_files,
            "Should have buffer from b.c")

        # Verify all BSS symbols have correct properties
        for symbol in uninit_symbols + buffer_symbols:
            self.assertEqual(
                symbol['type'],
                'OBJECT',
                f"{symbol['name']} should be an OBJECT type symbol")
            self.assertEqual(
                symbol['binding'],
                'LOCAL',
                f"{symbol['name']} should have LOCAL binding")
            self.assertIn(
                '.bss',
                symbol['section'],
                f"{symbol['name']} should be in .bss section")
            self.assertIn(
                symbol['source_file'],
                ['a.c', 'b.c'],
                f"{symbol['name']} should be mapped to a.c or b.c")

    def test_14_report_schema_validation(self):
        """
        Test Case 7: Validate that generated reports have correct schema

        Ensures that the memory reports contain all expected fields and structure.
        """
        source_dir = self.test_dir / "c_static"

        # Compile test case
        elf_path = self._compile_test_case(source_dir)

        # Generate report
        report = self._generate_memory_report(elf_path)

        # Verify top-level structure
        required_fields = [
            'file_path',
            'architecture',
            'entry_point',
            'file_type',
            'machine',
            'symbols',
            'program_headers',
            'memory_layout']
        for field in required_fields:
            self.assertIn(
                field,
                report,
                f"Report should contain {field} field")

        # Verify symbols structure
        self.assertIsInstance(
            report['symbols'],
            list,
            "symbols should be a list")

        # Find foo symbols and verify their structure
        foo_symbols = self._find_foo_symbols(report)
        self.assertGreater(
            len(foo_symbols),
            0,
            "Should find at least one foo symbol")

        for symbol in foo_symbols:
            symbol_fields = ['name', 'address', 'size', 'type', 'binding',
                             'section', 'source_file', 'visibility']
            for field in symbol_fields:
                self.assertIn(
                    field, symbol, f"Symbol should contain {field} field")

            # Verify field types
            self.assertIsInstance(symbol['name'], str)
            self.assertIsInstance(symbol['address'], int)
            self.assertIsInstance(symbol['size'], int)
            self.assertIsInstance(symbol['type'], str)
            self.assertIsInstance(symbol['binding'], str)
            self.assertIsInstance(symbol['source_file'], str)


if __name__ == '__main__':
    unittest.main()
