#!/usr/bin/env python3
"""
ELF section analysis and categorization.

This module handles the analysis of ELF sections, including size calculation,
categorization, and memory allocation tracking.
"""

from typing import Dict, List, Tuple
from elftools.common.exceptions import ELFError
import elftools.elf.constants
from ..core.models import MemorySection
from ..core.exceptions import SectionAnalysisError

SHF_ALLOC = elftools.elf.constants.SH_FLAGS.SHF_ALLOC
SHF_WRITE = elftools.elf.constants.SH_FLAGS.SHF_WRITE
SHF_EXECINSTR = elftools.elf.constants.SH_FLAGS.SHF_EXECINSTR


class SectionAnalyzer:  # pylint: disable=too-few-public-methods
    """Handles ELF section analysis and categorization"""

    def __init__(self, elffile):
        """Initialize with ELF file handle."""
        self.elffile = elffile

    def analyze_sections(self) -> Tuple[Dict[str, int], List[MemorySection]]:
        """Extract section information and calculate totals.

        Returns:
            Tuple of (totals_dict, sections_list) where totals_dict contains
            size totals by category and sections_list contains MemorySection objects.
        """
        sections = []

        try:
            for section in self.elffile.iter_sections():
                if not section.name:
                    continue

                # Only include sections that are loaded into memory
                if not section['sh_flags'] & SHF_ALLOC:
                    continue

                section_type = self._categorize_section(section)
                size = section['sh_size']

                sections.append(MemorySection(
                    name=section.name,
                    address=section['sh_addr'],
                    size=size,
                    type=section_type,
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
            type: 'code', 'data', 'rodata', or 'unknown'
        """
        flags = section['sh_flags']
        if flags & SHF_ALLOC:
            if flags & SHF_WRITE:
                return 'data'
            if flags & SHF_EXECINSTR:
                return 'code'
            return 'rodata'
        return 'unknown'
