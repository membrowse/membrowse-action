#!/usr/bin/env python3
"""
ELF section analysis and categorization.

This module handles the analysis of ELF sections, including size calculation,
categorization, and memory allocation tracking.
"""

import re
import logging
from typing import List, Optional, Tuple
from elftools.common.exceptions import ELFError
import elftools.elf.constants
from ..core.models import MemorySection
from ..core.exceptions import SectionAnalysisError

logger = logging.getLogger(__name__)

SHF_ALLOC = elftools.elf.constants.SH_FLAGS.SHF_ALLOC
SHF_WRITE = elftools.elf.constants.SH_FLAGS.SHF_WRITE
SHF_EXECINSTR = elftools.elf.constants.SH_FLAGS.SHF_EXECINSTR

SHT_NOBITS = 'SHT_NOBITS'

# Section type constants
SECTION_TYPE_CODE = 'code'
SECTION_TYPE_DATA = 'data'
SECTION_TYPE_RODATA = 'rodata'
SECTION_TYPE_UNKNOWN = 'unknown'


_IAR_FILL_RE = re.compile(r'^Fill\d+$')


class SectionAnalyzer:  # pylint: disable=too-few-public-methods
    """Handles ELF section analysis and categorization"""

    def __init__(self, elffile):
        """Initialize with ELF file handle."""
        self.elffile = elffile
        self._toolchain: Optional[str] = None
        self._load_segments: Optional[List[Tuple[int, int, int]]] = None

    def _get_load_segments(self) -> List[Tuple[int, int, int]]:
        """Return cached list of (p_vaddr_start, p_vaddr_end, p_paddr) tuples
        for PT_LOAD segments, used to compute per-section LMA.
        """
        if self._load_segments is not None:
            return self._load_segments
        segs: List[Tuple[int, int, int]] = []
        try:
            for seg in self.elffile.iter_segments():
                if seg['p_type'] != 'PT_LOAD':
                    continue
                v_start = seg['p_vaddr']
                v_end = v_start + seg['p_memsz']
                segs.append((v_start, v_end, seg['p_paddr']))
        except (IOError, OSError, ELFError):
            segs = []
        self._load_segments = segs
        return segs

    def _compute_lma(self, section) -> Optional[int]:
        """Compute LMA for a section, or None if not applicable.

        Returns None when the section has no file image (SHT_NOBITS like
        .bss), when no containing PT_LOAD segment is found, or when the
        computed LMA equals the VMA (no meaningful split to track).
        """
        if section['sh_type'] == SHT_NOBITS:
            return None
        sh_addr = section['sh_addr']
        for v_start, v_end, p_paddr in self._get_load_segments():
            if v_start <= sh_addr < v_end:
                lma = p_paddr + (sh_addr - v_start)
                return lma if lma != sh_addr else None
        return None

    def _detect_toolchain(self) -> Optional[str]:
        """Detect the toolchain from the ELF .comment section."""
        if self._toolchain is not None:
            return self._toolchain
        try:
            comment = self.elffile.get_section_by_name('.comment')
            if comment and b'IAR' in comment.data():
                self._toolchain = 'iar'
                return self._toolchain
        except (IOError, OSError):
            pass
        self._toolchain = ''
        return None

    def analyze_sections(self) -> List[MemorySection]:
        """Extract section information.

        Returns:
            List of MemorySection objects for all loaded (SHF_ALLOC) sections.
        """
        sections = []

        try:
            for section in self.elffile.iter_sections():
                if not section.name:
                    continue

                # Only include sections that are loaded into memory
                if not section['sh_flags'] & SHF_ALLOC:
                    continue

                # Skip IAR linker fill sections (Fill1, Fill2, etc.)
                # These are padding inserted by ielftool --fill, not real
                # code/data
                if (self._detect_toolchain() == 'iar'
                        and _IAR_FILL_RE.match(section.name)):
                    logger.debug(
                        "Skipping IAR fill section '%s' (%d bytes)",
                        section.name, section['sh_size'])
                    continue

                section_type = self._categorize_section(section)
                size = section['sh_size']

                sections.append(MemorySection(
                    name=section.name,
                    address=section['sh_addr'],
                    size=size,
                    type=section_type,
                    lma=self._compute_lma(section),
                ))

        except (IOError, OSError) as e:
            raise SectionAnalysisError(
                f"Failed to read ELF file for sections: {e}") from e
        except ELFError as e:
            raise SectionAnalysisError(
                f"Invalid ELF file format during section analysis: {e}") from e

        return sections

    def _categorize_section(self, section: MemorySection) -> str:
        """Categorize section based on sh_flags.

        Args:
            section: MemorySection object

        Returns:
            type: SECTION_TYPE_CODE, SECTION_TYPE_DATA, SECTION_TYPE_RODATA,
                  or SECTION_TYPE_UNKNOWN
        """
        flags = section['sh_flags']
        if flags & SHF_ALLOC:
            if flags & SHF_WRITE:
                return SECTION_TYPE_DATA
            if flags & SHF_EXECINSTR:
                return SECTION_TYPE_CODE
            return SECTION_TYPE_RODATA
        return SECTION_TYPE_UNKNOWN
