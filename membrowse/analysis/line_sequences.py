#!/usr/bin/env python3
"""
DWARF line program rows grouped into sequences.

A line sequence covers [first row, end_sequence row). The end_sequence row is
the first address after the sequence (DWARF 5 section 6.2.2) and often the
start of another CU's code, so it does not map an address. Neither does a
row at the end address, which covers zero bytes.
"""

from typing import Dict, Iterator, List, Tuple

Row = Tuple[int, str, int]  # address, file path, line (0: none)


def line_sequences(entries, file_paths: Dict[int, str]) -> Iterator[Tuple[List[Row], int]]:
    """(rows, end address) of each sequence in a CU's line program entries.

    Rows whose file number is not in file_paths are left out. A sequence the
    entries leave unterminated ends just past its last row.
    """
    rows = []
    for entry in entries:
        state = entry.state
        if state is None:
            continue
        if state.end_sequence:
            if rows:
                yield rows, state.address
            rows = []
            continue
        filename = file_paths.get(state.file)
        if filename:
            rows.append((state.address, filename, state.line or 0))
    if rows:
        yield rows, rows[-1][0] + 1


def rows_by_address(rows: List[Row], end: int) -> Dict[int, Tuple[str, int]]:
    """address -> (file, line) of a sequence's rows below end.

    The last row at an address describes the instruction there; earlier ones
    cover zero bytes.
    """
    return {address: (filename, line)
            for address, filename, line in rows if address < end}


def is_dead_sequence(start: int, address_size: int, function_at_zero: bool) -> bool:
    """Whether a sequence starting at start describes code the linker discarded.

    ld.bfd relocates the debug info of discarded sections to 0, LLD to the
    tombstone -1 (all ones). A sequence starting at 0 is kept when the image
    has a function there.
    """
    if start >= (1 << (8 * address_size)) - 1:
        return True
    return start == 0 and not function_at_zero


def has_function_at_zero(elffile) -> bool:
    """Whether a defined STT_FUNC symbol starts at address 0 (Thumb: 1)."""
    symtab = elffile.get_section_by_name('.symtab') if elffile is not None else None
    if symtab is None or not hasattr(symtab, 'iter_symbols'):
        return False
    return any(sym['st_info']['type'] == 'STT_FUNC'
               and sym['st_value'] in (0, 1)
               and sym['st_shndx'] != 'SHN_UNDEF'
               for sym in symtab.iter_symbols())
