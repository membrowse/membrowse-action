#!/usr/bin/env python3
"""
Debug why .debug_line parsing isn't working
"""

import sys
import traceback
from pathlib import Path

from elftools.elf.elffile import ELFFile
from test_memory_analysis import TestMemoryAnalysis

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'shared'))


def debug_line_parsing():  # pylint: disable=too-many-locals,too-many-statements
    """Debug the .debug_line parsing"""

    # Generate test ELF file
    test = TestMemoryAnalysis()
    test.setUp()
    test.test_02_compile_test_program()

    elf_file = test.temp_dir / 'simple_program.elf'
    print(f"Debugging line parsing for: {elf_file}")

    try:
        with open(elf_file, 'rb') as f:
            elffile = ELFFile(f)

            if not elffile.has_dwarf_info():
                print("❌ No DWARF info found")
                return

            print("✅ DWARF info found")
            dwarfinfo = elffile.get_dwarf_info()

            cu_count = 0
            for cu in dwarfinfo.iter_CUs():  # pylint: disable=too-many-nested-blocks
                cu_count += 1
                top_die = cu.get_top_DIE()

                # Check compilation directory
                comp_dir_attr = top_die.attributes.get('DW_AT_comp_dir')
                comp_dir = comp_dir_attr.value.decode(
                    'utf-8', errors='ignore') if comp_dir_attr else ""
                print(f"\nCU {cu_count}: comp_dir = '{comp_dir}'")

                # Check line program
                lineprog = dwarfinfo.line_program_for_CU(cu)
                if not lineprog:
                    print("  ❌ No line program for this CU")
                    continue

                print("  ✅ Line program found")

                # Debug file and directory access
                try:
                    file_entries = (lineprog['file_entry']
                                   if 'file_entry' in lineprog
                                   else lineprog.header.file_entry)
                    include_dirs = (lineprog['include_directory']
                                   if 'include_directory' in lineprog
                                   else lineprog.header.include_directory)

                    print(f"    Files: {len(file_entries)}")
                    print(f"    Include dirs: {len(include_dirs)}")

                    # Show file entries
                    for i, file_entry in enumerate(file_entries):
                        filename = file_entry.name
                        if isinstance(filename, bytes):
                            filename = filename.decode(
                                'utf-8', errors='ignore')
                        dir_index = getattr(file_entry, 'dir_index', 'N/A')
                        print(f"      File {i+1}: {filename} (dir_index: {dir_index})")

                    # Process line program entries
                    entry_count = 0
                    valid_entries = 0

                    for entry in lineprog.get_entries():
                        entry_count += 1
                        if entry.state is None:
                            continue

                        state = entry.state

                        # Check what we have
                        has_address = hasattr(
                            state, 'address') and state.address is not None
                        has_file = hasattr(
                            state, 'file') and state.file is not None and state.file > 0
                        is_end_seq = getattr(state, 'end_sequence', False)

                        if not is_end_seq and has_address and has_file:
                            valid_entries += 1
                            if valid_entries <= 5:  # Show first 5
                                file_entry = file_entries[state.file - 1]
                                filename = file_entry.name
                                if isinstance(filename, bytes):
                                    filename = filename.decode(
                                        'utf-8', errors='ignore')
                                print(
                                    f"      Entry: addr=0x{state.address:x}, "
                                    f"file={state.file} ({filename})")

                    print(
                        f"    Total entries: {entry_count}, Valid: {valid_entries}")

                except (OSError, IOError, AttributeError, ValueError) as e:
                    print(f"    ❌ Error processing entries: {e}")
                    traceback.print_exc()

    except (OSError, IOError, AttributeError) as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()


if __name__ == '__main__':
    debug_line_parsing()
