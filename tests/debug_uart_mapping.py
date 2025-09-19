#!/usr/bin/env python3
"""
Debug script to understand why uart_tx_count maps to stdint-uintn.h
"""

import sys
from pathlib import Path

from shared.elf_analyzer import ELFAnalyzer
from test_memory_analysis import TestMemoryAnalysis

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'shared'))


def debug_source_mapping():
    """Debug the source file mapping for uart_tx_count"""

    # Generate test ELF file
    test = TestMemoryAnalysis()
    test.setUp()
    test.test_02_compile_test_program()

    elf_file = test.temp_dir / 'simple_program.elf'
    print(f"Analyzing ELF file: {elf_file}")

    # Create analyzer with debug output
    analyzer = ELFAnalyzer(str(elf_file))

    # Look at the source file mapping that was built
    print("\nBy-address mapping:")
    for addr, source in analyzer._source_file_mapping['by_address'].items():  # pylint: disable=protected-access
        print(f"  0x{addr:08x} -> {source}")

    print("\nBy-compound-key mapping:")
    # pylint: disable=protected-access
    for key, source in analyzer._source_file_mapping['by_compound_key'].items():
        symbol_name, addr = key
        if 'uart' in symbol_name.lower():
            print(f"  ({symbol_name}, 0x{addr:08x}) -> {source}")

    # Get all symbols and check uart_tx_count specifically
    symbols = analyzer.get_symbols()

    print("\nUART-related symbols:")
    for symbol in symbols:
        if 'uart' in symbol.name.lower():
            print(f"  {symbol.name} @ 0x{symbol.address:08x}")
            print(f"    Type: {symbol.type}, Binding: {symbol.binding}")
            source_result = analyzer._extract_source_file(
                symbol.name, symbol.type, symbol.address)  # pylint: disable=protected-access
            print(f"    Source extraction result: '{source_result}'")
            print("    Extracted via: ", end="")

            # Show which method found the source file
            # pylint: disable=protected-access
            if symbol.address in analyzer._source_file_mapping['by_address']:
                print("by_address")
            elif (symbol.name, symbol.address) in analyzer._source_file_mapping['by_compound_key']:  # pylint: disable=protected-access
                print("by_compound_key (exact)")
            elif (symbol.name, 0) in analyzer._source_file_mapping['by_compound_key']:  # pylint: disable=protected-access
                print("by_compound_key (fallback)")
            else:
                print("not found")
            print()


if __name__ == '__main__':
    debug_source_mapping()
