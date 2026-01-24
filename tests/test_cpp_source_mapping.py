#!/usr/bin/env python3
"""
Tests for C++ symbol source file mapping.

This test verifies that C++ symbols (including template instantiations
and methods in namespaces) get correctly mapped to their source files
via DWARF debug information.

The key challenge with C++ is:
1. DWARF DIEs may use DW_AT_abstract_origin for template instantiations
2. The name chain can be: concrete DIE -> abstract_origin -> specification -> name
3. Full range CUs (like <artificial>) must be processed to find C++ symbols
"""

import unittest
from pathlib import Path

from membrowse.core import ELFAnalyzer

# Tests need access to internal state for verification
# pylint: disable=protected-access


class TestCppSourceMapping(unittest.TestCase):
    """Test C++ symbol source file mapping"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        cls.test_dir = Path(__file__).parent
        cls.test_elf = cls.test_dir / 'test-sleep.elf'

        # Skip all tests if test ELF doesn't exist
        if not cls.test_elf.exists():
            raise unittest.SkipTest(
                f"Test ELF file not found: {cls.test_elf}. "
                "Copy a C++ ARM ELF with debug info to run these tests."
            )

    def test_cpp_symbols_have_source_mapping(self):
        """Test that C++ symbols get source file mappings"""
        analyzer = ELFAnalyzer(str(self.test_elf))
        symbols = analyzer.get_symbols()

        # Find C++ symbols (contain ::)
        cpp_symbols = [s for s in symbols if '::' in s.name and s.type == 'FUNC']

        self.assertGreater(
            len(cpp_symbols), 0,
            "Expected to find C++ symbols in test ELF"
        )

        # Count how many have source mappings
        mapped_symbols = [s for s in cpp_symbols if s.source_file]
        coverage = len(mapped_symbols) / len(cpp_symbols) * 100

        print(f"\nC++ symbol coverage: {len(mapped_symbols)}/{len(cpp_symbols)} "
              f"({coverage:.1f}%)")

        # We should have high coverage (>80%) for C++ symbols
        self.assertGreater(
            coverage, 80,
            f"C++ source mapping coverage too low: {coverage:.1f}%"
        )

    def test_template_instantiation_source_mapping(self):
        """Test that template instantiations map to correct source files"""
        analyzer = ELFAnalyzer(str(self.test_elf))
        symbols = analyzer.get_symbols()

        # Look for template symbols (contain < and >)
        template_symbols = [
            s for s in symbols
            if '<' in s.name and '>' in s.name and s.type == 'FUNC'
        ]

        if not template_symbols:
            self.skipTest("No template symbols found in test ELF")

        # Check that template symbols have source mappings
        mapped_templates = [s for s in template_symbols if s.source_file]

        print(f"\nTemplate symbols: {len(template_symbols)}")
        print(f"With source mapping: {len(mapped_templates)}")

        # Show some examples
        for sym in mapped_templates[:5]:
            print(f"  {sym.name[:60]}...")
            print(f"    -> {sym.source_file}")

        # Templates should have good coverage
        if template_symbols:
            coverage = len(mapped_templates) / len(template_symbols) * 100
            self.assertGreater(
                coverage, 70,
                f"Template source mapping coverage too low: {coverage:.1f}%"
            )

    def test_namespace_method_source_mapping(self):
        """Test that namespace methods map to correct source files"""
        analyzer = ELFAnalyzer(str(self.test_elf))
        symbols = analyzer.get_symbols()

        # Look for namespace methods (contain :: but no templates)
        namespace_symbols = [
            s for s in symbols
            if '::' in s.name and '<' not in s.name and s.type == 'FUNC'
        ]

        if not namespace_symbols:
            self.skipTest("No namespace symbols found in test ELF")

        mapped_ns = [s for s in namespace_symbols if s.source_file]

        print(f"\nNamespace symbols: {len(namespace_symbols)}")
        print(f"With source mapping: {len(mapped_ns)}")

        for sym in mapped_ns[:5]:
            print(f"  {sym.name}")
            print(f"    -> {sym.source_file}")

    def test_dwarf_abstract_origin_handling(self):
        """Test that DW_AT_abstract_origin references are followed correctly"""
        analyzer = ELFAnalyzer(str(self.test_elf))

        # Check that DWARF data was populated
        dwarf_data = analyzer._dwarf_data

        self.assertIn('symbol_to_file', dwarf_data)
        self.assertIn('address_to_file', dwarf_data)

        # DWARF data should have entries
        self.assertGreater(
            len(dwarf_data['symbol_to_file']), 0,
            "symbol_to_file should have entries"
        )

        # Look for short C++ method names (from DWARF DIEs)
        # These come from following abstract_origin -> specification chains
        short_method_names = ['GetSize', 'GetStack', 'IsStarted', 'Run']
        found_short_names = []

        for (name, _), _ in dwarf_data['symbol_to_file'].items():
            if name in short_method_names:
                found_short_names.append(name)

        print(f"\nFound short method names from DWARF: {set(found_short_names)}")

        # We should find at least some short method names
        # (these come from following DW_AT_abstract_origin)
        self.assertGreater(
            len(found_short_names), 0,
            "Should find short C++ method names from DWARF "
            "(indicates abstract_origin handling works)"
        )

    def test_full_range_cu_processing(self):
        """Test that full-range CUs (like <artificial>) are processed"""
        analyzer = ELFAnalyzer(str(self.test_elf))

        # Check that we have address mappings for C++ code region
        # C++ symbols in test-sleep.elf are around 0x8000xxx
        dwarf_data = analyzer._dwarf_data

        # Find addresses in the C++ code region
        cpp_region_addrs = [
            addr for addr in dwarf_data['address_to_cu_file']
            if 0x8000000 <= addr <= 0x8002000
        ]

        print(f"\nAddresses mapped in C++ region: {len(cpp_region_addrs)}")

        self.assertGreater(
            len(cpp_region_addrs), 0,
            "Should have address mappings in C++ code region"
        )

    def test_source_file_resolution_by_address(self):
        """Test that source files can be resolved by address for C++ symbols"""
        analyzer = ELFAnalyzer(str(self.test_elf))
        symbols = analyzer.get_symbols()

        # Find a C++ symbol with known address
        cpp_funcs = [s for s in symbols if '::' in s.name and s.type == 'FUNC']

        if not cpp_funcs:
            self.skipTest("No C++ functions found")

        # Check that symbols resolved their source files
        for sym in cpp_funcs[:3]:
            print(f"\n{sym.name}")
            print(f"  Address: 0x{sym.address:x}")
            print(f"  Source: {sym.source_file or '(not mapped)'}")

            # The source file should be resolved
            if sym.source_file:
                self.assertNotEqual(
                    sym.source_file, '<artificial>',
                    f"Source should not be '<artificial>' for {sym.name}"
                )
                # Should be a real source file
                self.assertTrue(
                    sym.source_file.endswith(('.cpp', '.c', '.h', '.hpp')),
                    f"Source should be a C/C++ file, got: {sym.source_file}"
                )


if __name__ == '__main__':
    unittest.main()
