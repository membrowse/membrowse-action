#!/usr/bin/env python3
"""
Find the padding that explicit ``. = ALIGN(n)`` statements add to sections.

A linker script that ends a section with ``. = ALIGN(512)`` grows the
section by up to 511 bytes. Counted as used memory, that padding overstates
usage and turns a PR's real size change into steps of the alignment.

Sources, in order of preference:

- **GNU LD map file** (exact): each ``*fill*`` line directly below a
  ``. = ALIGN (...)`` line (see :meth:`MapFileParser.alignment_fill`).
- **LLD map file** (exact): the size column of each ``. = ALIGN ( ... )``
  row (see :meth:`LLDMapFileParser.alignment_fill`).
- **ELF** (estimate): the uniform bytes between the end of a section's last
  symbol and the end of the section, when that end is aligned. Content
  without a symbol (string literals, some constant tables) can end up
  counted as padding, so this is used only without a GNU LD or LLD map.

IAR has no in-section ALIGN statement: ICF ``alignment`` only aligns a
block's start (a gap between sections, never counted), and ``ielftool
--fill`` padding lands in ``FillN`` sections that are already skipped. IAR
builds, recognized by their map file or toolchain, have nothing to exclude.
"""

import logging
from dataclasses import replace
from typing import Dict, Iterable, List, Optional, Tuple

from elftools.common.exceptions import ELFError

from .ldmap_parser import MapFileParser
from .lldmap_parser import LLDMapFileParser
from .mapfile import _detect_map_format

logger = logging.getLogger(__name__)

SHF_ALLOC = 0x2

# A section end aligned to less than this is ordinary object alignment,
# not an explicit ALIGN statement.
_MIN_ELF_ALIGNMENT = 16


def detect_alignment_padding(elffile, map_file_path: Optional[str],
                             toolchain: Optional[str] = None
                             ) -> Dict[str, int]:
    """Return section name -> alignment padding bytes.

    Reads a GNU LD or LLD map file when one is given. An IAR map, or an
    IAR toolchain, means there is no such padding. Otherwise (no map, or
    one that cannot be read) falls back to the ELF estimate with a warning.

    Args:
        elffile: Open pyelftools ``ELFFile``.
        map_file_path: Path to the linker map file, or None.
        toolchain: Toolchain detected from the ELF (``'iar-9.40.1'``), or
            None.
    """
    reason = 'no map file given'
    if map_file_path:
        try:
            with open(map_file_path, 'r', encoding='utf-8',
                      errors='replace') as f:
                content = f.read()
        except OSError as e:
            reason = f'cannot read map file: {e}'
        else:
            fmt = _detect_map_format(content)
            if fmt == 'gnu_ld':
                return MapFileParser.alignment_fill(content)
            if fmt == 'lld':
                return LLDMapFileParser.alignment_fill(content)
            return _iar_padding()

    if toolchain and toolchain.startswith('iar'):
        return _iar_padding()

    logger.warning(
        "--exclude-alignment: %s; estimating alignment padding from ELF "
        "symbols. Pass a GNU LD or LLD map file (--map-file) for exact "
        "values.", reason)
    return estimate_alignment_padding(elffile)


def _iar_padding() -> Dict[str, int]:
    """IAR places no ALIGN padding inside sections; see the module doc."""
    logger.info("--exclude-alignment: IAR links have no in-section "
                "alignment padding; nothing to exclude")
    return {}


def estimate_alignment_padding(elffile) -> Dict[str, int]:
    """Estimate per-section trailing alignment padding from the ELF alone.

    For each allocated section with content markers, the gap between the
    end of its last content and the end of the section counts as padding
    when:

    - the section end is aligned to at least 16 bytes and the gap is smaller
      than that alignment (a larger gap is a reservation or unlabelled
      content, not alignment), and
    - for sections with file contents, only the trailing run of one repeated
      byte (the fill value) counts, which keeps unlabelled string data out.

    Content is marked by sized symbols (their end) and, in sections with
    file contents, zero-size labels inside the section (their address)
    that the symbol table assigns to it. A label at the very start or end
    marks a boundary, not content, and is ignored.

    Args:
        elffile: Open pyelftools ``ELFFile``.

    Returns:
        Section name -> estimated padding bytes, for sections with any.
    """
    symtab = elffile.get_section_by_name('.symtab')
    if symtab is None:
        logger.warning("--exclude-alignment: ELF has no symbol table; "
                       "no alignment padding excluded")
        return {}

    clear_thumb = elffile.header['e_machine'] == 'EM_ARM'
    by_section: Dict[int, List[Tuple[int, int]]] = {}
    for symbol in symtab.iter_symbols():
        index = symbol['st_shndx']
        if not isinstance(index, int) or index == 0:
            continue
        value = symbol['st_value']
        if clear_thumb and symbol['st_info']['type'] == 'STT_FUNC':
            value &= ~1
        by_section.setdefault(index, []).append((value, symbol['st_size']))

    padding: Dict[str, int] = {}
    for index, section in enumerate(elffile.iter_sections()):
        if not section.name or not section['sh_flags'] & SHF_ALLOC:
            continue
        pad = _section_padding(section, by_section.get(index, ()))
        if pad:
            padding[section.name] = pad
    return padding


def _section_padding(section, symbols: Iterable) -> int:
    """Estimated trailing alignment padding of one section."""
    start = section['sh_addr']
    end = start + section['sh_size']
    if end <= 0:
        return 0
    nobits = section['sh_type'] == 'SHT_NOBITS'
    last = None
    for value, size in symbols:
        if not start <= value <= end:
            continue
        if size:
            last = max(last or start, min(value + size, end))
        elif start < value < end and not nobits:
            # A label marks where content ends (``kernel_end = .``). In a
            # NOBITS section a reservation sits behind it (``_sstack``),
            # with no bytes to tell it from padding, so only sized
            # symbols count there.
            last = max(last or start, value)
    if last is None:
        return 0
    gap = end - last
    alignment = end & -end
    if gap <= 0 or alignment < _MIN_ELF_ALIGNMENT or gap >= alignment:
        return 0
    return gap if nobits else _trailing_fill(section, gap)


def _trailing_fill(section, gap: int) -> int:
    """Length of the run of one repeated byte ending the section, within
    its last ``gap`` bytes."""
    try:
        tail = section.data()[-gap:]
    except (IOError, OSError, ELFError):
        return 0
    if len(tail) != gap:
        return 0
    return len(tail) - len(tail.rstrip(bytes([tail[-1]])))


def exclude_padding(sections, padding: Dict[str, int]):
    """Return ``sections`` with each one's padding taken off its size.

    Args:
        sections: List of :class:`MemorySection`.
        padding: Section name -> padding bytes.

    Returns:
        (sections, excluded) where ``excluded`` maps each section that
        shrank to the bytes removed.
    """
    result = []
    excluded: Dict[str, int] = {}
    for section in sections:
        pad = min(padding.get(section.name, 0), section.size)
        if pad > 0:
            excluded[section.name] = pad
            section = replace(section, size=section.size - pad)
        result.append(section)
    return result, excluded
