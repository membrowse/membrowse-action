#!/usr/bin/env python3
"""
Find the padding that explicit ``. = ALIGN(n)`` statements add to sections.

A linker script that ends a section with ``. = ALIGN(512)`` grows the
section by up to 511 bytes. Counted as used memory, that padding overstates
usage and turns a PR's real size change into steps of the alignment.

Sources, in order of preference:

- **GNU LD map file** (exact): each ``*fill*`` line directly below a
  ``. = ALIGN (...)`` line at the end of an output section (see
  :meth:`MapFileParser.alignment_fill`).
- **LLD map file** (exact): the size column of each ``. = ALIGN ( ... )``
  row at the end of an output section (see
  :meth:`LLDMapFileParser.alignment_fill`).
- **ELF** (estimate): the uniform bytes between the end of a section's last
  symbol and the end of the section, when that end is aligned. Content
  without a symbol (string literals, some constant tables) can end up
  counted as padding, so this is used only without a GNU LD or LLD map
  (or with a map file in a format that is not recognized).

Only padding at the end of a section is taken: an ALIGN followed by more
content leaves that content at addresses past a shrunken section end.

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
from .sections import SHF_ALLOC
from .symtab import symtab_symbols

logger = logging.getLogger(__name__)

# Every GNU LD map has this heading; a map with neither it nor an LLD or
# IAR marker is in a format this module cannot read.
_GNU_LD_MAP_MARKER = 'Linker script and memory map'

# A section end aligned to less than this is ordinary object alignment,
# not an explicit ALIGN statement.
_MIN_ELF_ALIGNMENT = 16


def map_alignment_padding(content: str, fmt: str
                          ) -> Optional[Dict[str, int]]:
    """Return section name -> alignment padding read from a map file.

    Args:
        content: Full text of the map file.
        fmt: Its format, as detected by ``mapfile._detect_map_format``
            (``'gnu_ld'``, ``'lld'`` or ``'iar'``).

    Returns:
        The exact padding for GNU LD and LLD maps, ``{}`` for IAR, and
        None when the content is not a map this module can read (TI,
        armlink or SEGGER maps, empty or truncated files), so the caller
        falls back to the ELF estimate.
    """
    if fmt == 'iar':
        return _iar_padding()
    if fmt == 'lld':
        return LLDMapFileParser.alignment_fill(content)
    if _GNU_LD_MAP_MARKER in content:
        return MapFileParser.alignment_fill(content)
    return None


def detect_alignment_padding(elffile,
                             map_padding: Optional[Dict[str, int]] = None,
                             toolchain: Optional[str] = None,
                             map_given: bool = False) -> Dict[str, int]:
    """Return section name -> alignment padding bytes.

    Uses the padding read from the map file when there is one (see
    :func:`map_alignment_padding`). An IAR toolchain means there is no
    such padding. Otherwise (no map, or one in a format that is not
    recognized) falls back to the ELF estimate with a warning.

    Args:
        elffile: Open pyelftools ``ELFFile``.
        map_padding: Result of :func:`map_alignment_padding`, or None.
        toolchain: Toolchain detected from the ELF (``'iar-9.40.1'``), or
            None.
        map_given: Whether a map file was given; only changes the warning.
    """
    if map_padding is not None:
        return map_padding
    if toolchain and toolchain.startswith('iar'):
        return _iar_padding()

    reason = ('map file format not recognized' if map_given
              else 'no map file given')
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
    - only the trailing run of one repeated byte (the fill value) counts,
      which keeps unlabelled string data out.

    NOBITS sections (``.bss``, stacks, heaps) are left alone: they have no
    bytes to tell a reservation (``. = . + 0x800``) from padding, and one
    ending at a round address such as the top of RAM would pass the
    alignment check with any gap. A map file gives their padding exactly.

    Content is marked by sized symbols (their end) and zero-size labels
    inside the section (their address) that the symbol table assigns to
    it. A label at the very start or end
    marks a boundary, not content, and is ignored.

    Args:
        elffile: Open pyelftools ``ELFFile``.

    Returns:
        Section name -> estimated padding bytes, for sections with any.
    """
    symbols = symtab_symbols(elffile)
    if symbols is None:
        logger.warning("--exclude-alignment: ELF has no symbol table; "
                       "no alignment padding excluded")
        return {}

    clear_thumb = elffile.header['e_machine'] == 'EM_ARM'
    by_section: Dict[int, List[Tuple[int, int]]] = {}
    for symbol in symbols:
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
    if section['sh_type'] == 'SHT_NOBITS':
        return 0
    start = section['sh_addr']
    end = start + section['sh_size']
    if end <= 0:
        return 0
    last = None
    for value, size in symbols:
        if not start <= value <= end:
            continue
        if size:
            last = max(last or start, min(value + size, end))
        elif start < value < end:
            # A label marks where content ends (``kernel_end = .``).
            last = max(last or start, value)
    if last is None:
        return 0
    gap = end - last
    alignment = end & -end
    if gap <= 0 or alignment < _MIN_ELF_ALIGNMENT or gap >= alignment:
        return 0
    return _trailing_fill(section, gap)


def _trailing_fill(section, gap: int) -> int:
    """Length of the run of one repeated byte ending the section, within
    its last ``gap`` bytes (read from the file, not the whole section)."""
    try:
        section.stream.seek(section['sh_offset'] + section['sh_size'] - gap)
        tail = section.stream.read(gap)
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
    unknown = set(padding) - {section.name for section in sections}
    if unknown:
        logger.debug("--exclude-alignment: padding for sections not in the "
                     "report ignored: %s", ", ".join(sorted(unknown)))
    for section in sections:
        pad = min(padding.get(section.name, 0), section.size)
        if pad > 0:
            excluded[section.name] = pad
            section = replace(section, size=section.size - pad)
        result.append(section)
    return result, excluded
