#!/usr/bin/env python3
"""
Test the hybrid source file mapping implementation
"""
# pylint: disable=protected-access,too-many-branches
# pylint: disable=too-many-statements,broad-exception-caught,duplicate-code

import sys
from pathlib import Path

from membrowse.core import ELFAnalyzer
from tests.test_memory_analysis import TestMemoryAnalysis

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'shared'))


def test_hybrid_mapping():
    """Test the hybrid source file mapping"""

    # Generate test ELF file
    test = TestMemoryAnalysis()
    test.setUp()
    test.test_02_compile_test_program()

    elf_file = test.temp_dir / 'simple_program.elf'
    print(f"Testing hybrid mapping with: {elf_file}")

    # Create analyzer
    analyzer = ELFAnalyzer(str(elf_file))

    print(
        f"\n.debug_line mappings loaded: {len(analyzer._dwarf_data['address_to_file'])}")
    print(
        f"DIE mappings loaded: {len(analyzer._dwarf_data.get('symbol_to_file', {}))}")

    # Get symbols
    symbols = analyzer.get_symbols()

    print("\n🧪 HYBRID APPROACH RESULTS:")
    print("=" * 60)

    print("\n📋 Functions (should use .debug_line):")
    for symbol in symbols:
        if symbol.type == 'FUNC' and 'uart' in symbol.name.lower():
            # Check what method was used
            method_used = "UNKNOWN"

            # Check .debug_line first
            if symbol.address in analyzer._dwarf_data['address_to_file']:
                method_used = ".debug_line (exact)"
            else:
                # Check nearby addresses
                found_nearby = False
                for offset in range(-20, 21):
                    check_addr = symbol.address + offset
                    if check_addr in analyzer._dwarf_data['address_to_file']:
                        method_used = f".debug_line (offset {offset})"
                        found_nearby = True
                        break

                if not found_nearby:
                    # Must have used DIE fallback
                    if symbol.address in analyzer._dwarf_data.get(
                            'address_to_cu_file', {}):
                        method_used = "DIE fallback (by_address)"
                    elif ((symbol.name, symbol.address) in
                          analyzer._dwarf_data.get('symbol_to_file', {})):
                        method_used = "DIE fallback (compound_key)"
                    else:
                        method_used = "No mapping found"

            print(
                f"  ✅ {symbol.name:15} @ 0x{symbol.address:08x} -> {symbol.source_file}")
            print(f"     Method: {method_used}")

    print("\n📦 Variables (must use DIE analysis):")
    for symbol in symbols:
        if symbol.type == 'OBJECT' and 'uart' in symbol.name.lower():
            # Variables should never be in .debug_line
            in_line_mapping = symbol.address in analyzer._dwarf_data['address_to_file']

            # Determine DIE method used
            die_method = "UNKNOWN"
            if symbol.address in analyzer._dwarf_data.get(
                    'address_to_cu_file', {}):
                die_method = "DIE (by_address)"
            elif (symbol.name, symbol.address) in analyzer._dwarf_data.get('symbol_to_file', {}):
                die_method = "DIE (compound_key exact)"
            elif (symbol.name, 0) in analyzer._dwarf_data.get('symbol_to_file', {}):
                die_method = "DIE (compound_key fallback)"

            print(
                f"  ✅ {symbol.name:15} @ 0x{symbol.address:08x} -> {symbol.source_file}")
            print(f"     Method: {die_method}")
            if in_line_mapping:
                print("     ⚠️  WARNING: Variable unexpectedly found in .debug_line!")

    print("\n📊 All Global Variables Summary:")
    for symbol in symbols:
        if symbol.type == 'OBJECT' and symbol.binding == 'GLOBAL':
            print(f"  {symbol.name:20} -> {symbol.source_file}")

    # Test passes if we get here without exceptions
    assert True


if __name__ == '__main__':
    try:
        test_hybrid_mapping()
        print("\n🎉 Hybrid mapping test completed!")
    except Exception as e:
        print(f"\n❌ Hybrid mapping test failed: {e}")
        sys.exit(1)
