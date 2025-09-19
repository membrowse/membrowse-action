#!/usr/bin/env python3
"""
ELF section analysis and categorization.

This module handles the analysis of ELF sections, including size calculation,
categorization, and memory allocation tracking.
"""

from typing import Dict, List, Tuple
from elftools.common.exceptions import ELFError
from .models import MemorySection
from .exceptions import SectionAnalysisError


class SectionAnalyzer:
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
        totals = {
            'text_size': 0,
            'data_size': 0,
            'bss_size': 0,
            'rodata_size': 0,
            'debug_size': 0,
            'other_size': 0,
            'total_file_size': 0
        }

        try:
            for section in self.elffile.iter_sections():
                if not section.name:
                    continue

                # Only include sections with SHF_ALLOC flag (0x2) - sections loaded into memory
                if not (section['sh_flags'] & 0x2):
                    continue

                section_type = self._categorize_section(section.name)
                size = section['sh_size']

                # Update totals
                totals[f'{section_type}_size'] += size
                totals['total_file_size'] += size

                sections.append(MemorySection(
                    name=section.name,
                    address=section['sh_addr'],
                    size=size,
                    type=section_type
                ))

        except (IOError, OSError) as e:
            raise SectionAnalysisError(f"Failed to read ELF file for sections: {e}") from e
        except ELFError as e:
            raise SectionAnalysisError(f"Invalid ELF file format during section analysis: {e}") from e

        return totals, sections

    def _categorize_section(self, section_name: str) -> str:
        """Categorize section based on name.

        Args:
            section_name: Name of the ELF section

        Returns:
            Category string: 'text', 'data', 'bss', 'rodata', 'debug', or 'other'
        """
        name_lower = section_name.lower()

        if name_lower.startswith('.text') or name_lower in ['.init', '.fini']:
            return 'text'
        if name_lower.startswith('.data') or name_lower in ['.sdata', '.tdata']:
            return 'data'
        if name_lower.startswith('.bss') or name_lower in ['.sbss', '.tbss']:
            return 'bss'
        if name_lower.startswith('.rodata') or name_lower.startswith('.const'):
            return 'rodata'
        if name_lower.startswith('.debug') or name_lower.startswith('.stab'):
            return 'debug'
        return 'other'