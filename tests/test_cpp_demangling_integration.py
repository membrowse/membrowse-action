#!/usr/bin/env python3
"""
Integration test for C++ symbol demangling

This test:
1. Compiles a real C++ program
2. Extracts symbols from the ELF file
3. Verifies that C++ symbols are properly demangled
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from elftools.elf.elffile import ELFFile
from membrowse.analysis.symbols import SymbolExtractor
from membrowse.analysis.sources import SourceFileResolver
from tests.test_helpers import run_compilation


class TestCppDemanglingIntegration(unittest.TestCase):
    """Integration test for C++ symbol demangling with real compiled code"""

    def setUp(self):
        """Set up test environment"""
        self.test_dir = Path(__file__).parent
        self.temp_dir = Path(tempfile.mkdtemp())

        # Paths to test files
        self.cpp_file = self.test_dir / 'cpp_program.cpp'
        self.ld_file = self.test_dir / 'simple_program.ld'
        self.elf_file = self.temp_dir / 'cpp_program.elf'

        # Check for C++ compiler
        self.gxx_command = None
        for gxx_cmd in ['g++', 'arm-none-eabi-g++']:
            try:
                subprocess.run([gxx_cmd, '--version'],
                             capture_output=True, check=True)
                self.gxx_command = gxx_cmd
                break
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue

        # Ensure test files exist
        self.assertTrue(self.cpp_file.exists(),
                       f"Test C++ file not found: {self.cpp_file}")
        self.assertTrue(self.ld_file.exists(),
                       f"Test linker script not found: {self.ld_file}")

    def tearDown(self):
        """Clean up test environment"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_01_check_prerequisites(self):
        """Test that required tools are available"""
        self.assertIsNotNone(self.gxx_command,
                            "No suitable C++ compiler found (g++ or arm-none-eabi-g++)")
        print(f"Found C++ compiler: {self.gxx_command}")

    def test_02_compile_cpp_program(self):
        """Test compilation of the C++ test program"""
        if not self.gxx_command:
            self.skipTest("C++ compiler not available")

        # Compile the test program
        compile_cmd = [
            self.gxx_command,
            '-nostdlib',           # Don't link standard libraries
            '-nostartfiles',       # Don't use standard startup files
            '-fno-exceptions',     # Disable exceptions for embedded
            '-fno-rtti',          # Disable RTTI for embedded
            '-g',                  # Generate debug information
            '-T', str(self.ld_file),  # Use linker script
            '-o', str(self.elf_file),  # Output file
            str(self.cpp_file)     # Input file
        ]

        try:
            run_compilation(compile_cmd, "C++ compilation successful")
        except subprocess.CalledProcessError as e:
            self.fail(f"C++ compilation failed: {e.stderr}")

        # Verify ELF file was created
        self.assertTrue(self.elf_file.exists(), "ELF file was not created")

    def test_03_extract_and_verify_demangled_symbols(self):
        """Test that C++ symbols are properly demangled"""
        if not self.gxx_command:
            self.skipTest("C++ compiler not available")

        # Ensure compilation has happened
        if not self.elf_file.exists():
            self.test_02_compile_cpp_program()

        # Extract symbols from ELF file
        with open(self.elf_file, 'rb') as f:
            elffile = ELFFile(f)

            # Create symbol extractor
            extractor = SymbolExtractor(elffile)

            # Create a minimal source resolver
            source_resolver = SourceFileResolver({}, {})

            # Extract symbols
            symbols = extractor.extract_symbols(source_resolver)

        # Verify we got symbols
        self.assertGreater(len(symbols), 0, "No symbols extracted from ELF file")

        # Find specific demangled C++ symbols we expect
        symbol_names = [s.name for s in symbols]

        # Test cases: (expected_substring, description)
        expected_symbols = [
            # Classes and methods
            ('UART', 'UART class name should appear'),
            ('Hardware', 'Hardware namespace should appear'),
            ('Peripherals', 'Peripherals namespace should appear'),
            ('transmit', 'transmit method should appear'),
            ('getStatus', 'getStatus method should appear'),

            # Overloaded functions (at least one version)
            ('add', 'add function should appear'),

            # Math namespace
            ('Math', 'Math namespace should appear'),

            # Timer class
            ('Timer', 'Timer class should appear'),
            ('increment', 'increment method should appear'),

            # C-style function (should NOT be mangled)
            ('c_style_function', 'C-style function should appear unmangled'),
            ('main', 'main function should appear'),
        ]

        print("\n=== Demangled C++ Symbols ===")
        cpp_symbols = [name for name in symbol_names
                      if '::' in name or  # C++ scope resolution
                         'UART' in name or
                         'Buffer' in name or
                         'Timer' in name or
                         'Hardware' in name or
                         'Math' in name]

        for sym in cpp_symbols[:20]:  # Show first 20 C++ symbols
            print(f"  {sym}")

        # Verify expected symbols
        found_count = 0
        for expected, description in expected_symbols:
            found = any(expected in name for name in symbol_names)
            if found:
                found_count += 1
                print(f"✓ Found: {expected} ({description})")
            else:
                print(f"✗ Missing: {expected} ({description})")

        # We should find most of the expected symbols
        # (some may be optimized away, so we don't require 100%)
        self.assertGreater(found_count, len(expected_symbols) * 0.6,
                          f"Only found {found_count}/{len(expected_symbols)} expected symbols")

    def test_04_verify_no_mangled_symbols(self):
        """Verify that symbols are demangled (no _Z prefixes in display names)"""
        if not self.gxx_command:
            self.skipTest("C++ compiler not available")

        # Ensure compilation has happened
        if not self.elf_file.exists():
            self.test_02_compile_cpp_program()

        # Extract symbols
        with open(self.elf_file, 'rb') as f:
            elffile = ELFFile(f)
            extractor = SymbolExtractor(elffile)
            source_resolver = SourceFileResolver({}, {})
            symbols = extractor.extract_symbols(source_resolver)

        # Check for mangled symbols
        mangled_symbols = [s.name for s in symbols if s.name.startswith('_Z')]

        if mangled_symbols:
            print("\n=== WARNING: Found mangled symbols (these should be demangled) ===")
            for sym in mangled_symbols[:10]:
                print(f"  {sym}")

        # There should be NO mangled symbols in the output
        self.assertEqual(
            len(mangled_symbols), 0,
            f"Found {len(mangled_symbols)} mangled symbols "
            f"that should have been demangled")

    def test_05_verify_c_symbols_unchanged(self):
        """Verify that C-style symbols remain unchanged"""
        if not self.gxx_command:
            self.skipTest("C++ compiler not available")

        # Ensure compilation has happened
        if not self.elf_file.exists():
            self.test_02_compile_cpp_program()

        # Extract symbols
        with open(self.elf_file, 'rb') as f:
            elffile = ELFFile(f)
            extractor = SymbolExtractor(elffile)
            source_resolver = SourceFileResolver({}, {})
            symbols = extractor.extract_symbols(source_resolver)

        symbol_names = [s.name for s in symbols]

        # C-style functions declared with extern "C" should not be mangled
        c_style_symbols = ['main', 'c_style_function']

        for sym in c_style_symbols:
            self.assertIn(sym, symbol_names,
                         f"C-style symbol '{sym}' should be present and unmangled")
            print(f"✓ Found C-style symbol: {sym}")


if __name__ == '__main__':
    unittest.main()
