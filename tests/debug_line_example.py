#!/usr/bin/env python3
# pylint: disable=import-error,too-many-nested-blocks,duplicate-code
"""
Example of how to use .debug_line section for more accurate source file mapping
"""

import sys
from pathlib import Path

from elftools.elf.elffile import ELFFile
from test_memory_analysis import TestMemoryAnalysis

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'shared'))


def extract_line_mapping(elf_path):
    """Extract address-to-source mapping from .debug_line section"""
    address_to_source = {}

    try:
        with open(elf_path, 'rb') as f:
            elffile = ELFFile(f)

            if not elffile.has_dwarf_info():
                return address_to_source

            dwarfinfo = elffile.get_dwarf_info()

            # Iterate through line programs
            for cu in dwarfinfo.iter_CUs(
            ):  # pylint: disable=too-many-nested-blocks
                line_program = dwarfinfo.line_program_for_CU(cu)
                if line_program is None:
                    continue

                # Decode the line program
                for entry in line_program.get_entries():
                    # We want entries that mark the beginning of statements
                    if entry.state and hasattr(
                            entry.state, 'address') and entry.state.address:
                        if hasattr(entry.state, 'file') and entry.state.file:
                            # Get filename from the file table
                            file_entry = line_program.header.file_entry[entry.state.file - 1]
                            if hasattr(file_entry, 'name'):
                                filename = file_entry.name
                                if isinstance(filename, bytes):
                                    filename = filename.decode(
                                        'utf-8', errors='ignore')

                                address_to_source[entry.state.address] = filename

    except (OSError, IOError) as e:
        print(f"Error parsing .debug_line: {e}")

    return address_to_source


def demo_line_mapping():
    """Demonstrate .debug_line based source mapping"""
    # Generate test ELF file
    test = TestMemoryAnalysis()
    test.setUp()
    test.test_02_compile_test_program()

    elf_file = test.temp_dir / 'simple_program.elf'

    # Extract line mapping
    line_mapping = extract_line_mapping(str(elf_file))

    print(
        f"Found {len(line_mapping)} address-to-source mappings from .debug_line")

    # Show some examples
    print("\nSample mappings:")
    for i, (addr, source) in enumerate(line_mapping.items()):
        if i < 10:  # Show first 10
            print(f"  0x{addr:08x} -> {source}")

    # Check specific addresses we know about
    print("\nUART function addresses from our earlier debug:")
    known_addresses = [
        (0x08000258, "uart_init"),
        (0x0800028d, "uart_transmit"),
        (0x080002f3, "uart_receive"),
        (0x08000378, "uart_get_status")
    ]

    for addr, func_name in known_addresses:
        if addr in line_mapping:
            print(f"  {func_name:15} @ 0x{addr:08x} -> {line_mapping[addr]}")
        else:
            print(f"  {func_name:15} @ 0x{addr:08x} -> NOT FOUND in .debug_line")


if __name__ == '__main__':
    demo_line_mapping()
