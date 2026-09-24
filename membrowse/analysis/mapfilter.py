#!/usr/bin/env python3
"""
Decide which linker map output sections carry real addresses.

Non-``SHF_ALLOC`` output sections (``.debug_*``, ``.comment``,
``.ARM.attributes``, ``(INFO)`` sections) are placed at address 0 by the
linker, so the map file lists their input sections at file offsets. Those
offsets overlap real low addresses and would steal symbol attribution.

The ELF cannot be the sole authority: a stripped ELF no longer contains
the debug sections the map still lists. The map cannot be either: an
ALLOC section in flash at address 0 (``.isr_vector`` on nRF, Kinetis,
RP2040) looks exactly like a debug section. :class:`OutputSectionFilter`
combines both, so it works for stripped and unstripped ELFs alike.
"""

from typing import Mapping, Optional


class OutputSectionFilter:  # pylint: disable=too-few-public-methods
    """Skip map output sections whose input sections hold file offsets."""

    def __init__(self, alloc_by_name: Mapping[str, bool]):
        """Initialize from the ELF's section table.

        Args:
            alloc_by_name: Section name -> whether it is ``SHF_ALLOC``, for
                every section in the ELF (see
                :meth:`SectionAnalyzer.section_alloc_flags`).
        """
        self._alloc_by_name = alloc_by_name

    def skip(self, name: str, address: Optional[int]) -> bool:
        """Return True if the output section's input sections must be ignored.

        - ELF says non-ALLOC: skip, whatever address the map shows (a
          script may place ``.comment`` at the location counter).
        - ELF says ALLOC: keep, even at address 0 (flash-at-0 targets).
        - Not in the ELF (stripped debug info, ``.zdebug_*`` renamed by
          compression): trust the map, and skip at address 0.

        Args:
            name: Output section name as the map prints it.
            address: Output section address from the map, or None when
                the map does not print one (empty section).
        """
        is_alloc = self._alloc_by_name.get(name)
        if is_alloc is None:
            return address == 0
        return not is_alloc
