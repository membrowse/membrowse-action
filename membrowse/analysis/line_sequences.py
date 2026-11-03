#!/usr/bin/env python3
"""
DWARF line program rows grouped into sequences.

A line sequence covers [start, end_sequence row). The end_sequence row is
the first address after the sequence (DWARF 5 section 6.2.2) and often the
start of another CU's code, so it does not map an address. Neither does a
row at the end address, which covers zero bytes.

Sequences of code the linker discarded keep their line programs, relocated
to 0 plus the function's offset in its input section (ld.bfd) or to the
tombstone -1 (LLD). Such a sequence starts outside the image's code, or on
top of a live sequence. CodeLayout holds what the ELF says about where code
is, and select_live_sequences keeps the sequences that fit it.
"""

import bisect
import logging
from typing import Dict, Iterable, Iterator, List, NamedTuple, Optional, Tuple

logger = logging.getLogger(__name__)

Row = Tuple[int, str, int]  # address, file path, line (0: none)

SHF_ALLOC = 0x2
SHF_EXECINSTR = 0x4


class Sequence(NamedTuple):
    """A line sequence of one CU: rows maps address -> (file, line)."""
    start: int
    end: int
    cu_offset: int
    rows: Dict[int, Tuple[str, int]]


def line_sequences(entries, file_paths: Dict[int, str]
                   ) -> Iterator[Tuple[int, List[Row], int]]:
    """(start, rows, end address) of each sequence in a CU's line program entries.

    start is the address of the sequence's first row, whatever its file.
    Rows whose file number is not in file_paths are left out of rows. A
    sequence the entries leave unterminated ends just past its last row.
    """
    start = None
    last = None
    rows = []
    for entry in entries:
        state = getattr(entry, 'state', None)
        address = getattr(state, 'address', None)
        if address is None:
            continue
        if getattr(state, 'end_sequence', False):
            if start is not None:
                yield start, rows, address
            start, last, rows = None, None, []
            continue
        if start is None:
            start = address
        last = address
        filename = file_paths.get(getattr(state, 'file', None))
        if filename:
            rows.append((address, filename, getattr(state, 'line', 0) or 0))
    if start is not None:
        yield start, rows, last + 1


def rows_by_address(rows: List[Row], end: int) -> Dict[int, Tuple[str, int]]:
    """address -> (file, line) of a sequence's rows below end.

    The last row at an address describes the instruction there; earlier ones
    cover zero bytes.
    """
    return {address: (filename, line)
            for address, filename, line in rows if address < end}


def _is_mapping_symbol(name: str) -> bool:
    """ARM/AArch64/RISC-V mapping symbols ($a, $t, $d, $x, ...) mark no code start."""
    return name.startswith('$')


class CodeLayout:
    """Where the ELF image has code.

    code_ranges: [start, end) of allocated executable sections with
    contents, None when the ELF has no section headers to tell.
    code_starts: addresses of defined FUNC and NOTYPE symbols in those
    ranges (Thumb bit cleared), None without a symbol table.
    """

    def __init__(self, code_ranges: Optional[List[Tuple[int, int]]] = None,
                 code_starts: Optional[Iterable[int]] = None):
        self.code_ranges = sorted(code_ranges) if code_ranges is not None else None
        self._range_starts = [start for start, _ in self.code_ranges or ()]
        self.code_starts = set(code_starts) if code_starts is not None else None

    @classmethod
    def from_elf(cls, elffile) -> 'CodeLayout':
        """The layout of an open pyelftools ELFFile (None: nothing known)."""
        if elffile is None or not hasattr(elffile, 'iter_sections'):
            return cls()
        code_ranges = []
        symtab = None
        try:
            for section in elffile.iter_sections():
                if section.name == '.symtab':
                    symtab = section
                flags = section['sh_flags']
                if (flags & SHF_ALLOC and flags & SHF_EXECINSTR
                        and section['sh_type'] != 'SHT_NOBITS'
                        and section['sh_size'] > 0):
                    start = section['sh_addr']
                    code_ranges.append((start, start + section['sh_size']))
        except (TypeError, KeyError, AttributeError) as e:
            logger.debug("No section layout for dead line sequences: %s", e)
            return cls()
        if not code_ranges:
            return cls()
        layout = cls(code_ranges)
        if symtab is not None:
            layout.code_starts = {
                sym['st_value'] & ~1 for sym in symtab.iter_symbols()
                if sym['st_info']['type'] in ('STT_FUNC', 'STT_NOTYPE')
                and sym['st_shndx'] not in ('SHN_UNDEF', 'SHN_ABS')
                and sym.name and not _is_mapping_symbol(sym.name)
                and layout.is_code(sym['st_value'] & ~1)}
        return layout

    def is_code(self, address: int) -> bool:
        """Whether address lies in a code section (True when unknown)."""
        if self.code_ranges is None:
            return True
        i = bisect.bisect_right(self._range_starts, address) - 1
        return i >= 0 and address < self.code_ranges[i][1]

    def starts_code(self, address: int) -> Optional[bool]:
        """Whether a code symbol starts at address, None when unknown."""
        if self.code_starts is None:
            return None
        return address in self.code_starts


def is_dead_sequence(start: int, address_size: int, layout: CodeLayout) -> bool:
    """Whether a sequence starting at start describes code the linker discarded.

    LLD tombstones (all ones) and starts outside every code section are
    dead. A start at 0, where ld.bfd puts discarded functions, needs a code
    symbol there as well; without a symbol table it counts as dead.
    """
    if start >= (1 << (8 * address_size)) - 1:
        return True
    if not layout.is_code(start):
        return True
    return start == 0 and not layout.starts_code(0)


def _overlap_clusters(sequences: List[Sequence]) -> Iterator[List[Sequence]]:
    """Groups of sequences, sorted by start, whose ranges overlap in a chain."""
    cluster = []
    cluster_end = None
    for seq in sorted(sequences, key=lambda s: (s.start, s.end, s.cu_offset)):
        if cluster and seq.start < cluster_end:
            cluster.append(seq)
            cluster_end = max(cluster_end, seq.end)
            continue
        if cluster:
            yield cluster
        cluster, cluster_end = [seq], seq.end
    if cluster:
        yield cluster


def _disjoint(sequences: List[Sequence]) -> bool:
    """Whether sequences sorted by start do not overlap each other."""
    return all(a.end <= b.start for a, b in zip(sequences, sequences[1:]))


def _one_per_range(sequences: Iterable[Sequence]) -> List[Sequence]:
    """The first (lowest CU offset) of each run of sequences with one range."""
    unique = []
    for seq in sequences:
        if not unique or (unique[-1].start, unique[-1].end) != (seq.start, seq.end):
            unique.append(seq)
    return unique


def select_live_sequences(sequences: List[Sequence], layout: CodeLayout) -> List[Sequence]:
    """The sequences that describe the image's code, sorted by start.

    Live code does not overlap, so overlapping sequences include discarded
    code that landed on live code (ld.bfd: 0 plus an offset). Sequences
    with the same range are one function: ld.bfd points the debug info of a
    discarded COMDAT copy (a C++ inline function) at the copy it kept, and
    the one of the first CU stands for both. Of the overlapping ones, the
    ones starting where a code symbol starts are kept if they do not
    overlap each other; otherwise none is kept, since which one is live
    cannot be told and a wrong file is worse than none. The result does not
    depend on the order the CUs were read in.
    """
    live = []
    for cluster in _overlap_clusters(sequences):
        if len(cluster) == 1:
            live.extend(cluster)
            continue
        kept = _one_per_range(seq for seq in cluster if layout.starts_code(seq.start))
        if kept and _disjoint(kept):
            live.extend(kept)
        else:
            logger.debug("Dropping %d overlapping line sequences at 0x%x",
                         len(cluster), cluster[0].start)
    return live


def store_live_sequences(dwarf_data: dict, sequences: List[Sequence],
                         layout: CodeLayout) -> None:
    """Store the rows and ranges of the live sequences in dwarf_data.

    Run once every CU is read, so that sequences of discarded code that
    landed on live code are told apart whatever the CU order.
    """
    address_to_file = dwarf_data['address_to_file']
    address_to_line = dwarf_data['address_to_line']
    for seq in select_live_sequences(sequences, layout):
        for address, (filename, line) in seq.rows.items():
            address_to_file[address] = filename
            if line:
                address_to_line[address] = line
        dwarf_data['line_sequences'].append((seq.start, seq.end, seq.cu_offset))
    metrics = dwarf_data.get('coverage_metrics')
    if metrics is not None:
        metrics['line_program_addresses'] = len(address_to_file)
