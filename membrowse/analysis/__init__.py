#!/usr/bin/env python3
"""
Analysis components for MemBrowse.

This package contains specialized analyzers for extracting information
from ELF files including DWARF debug info, symbols, sections, and source files.
"""

from .dwarf import DWARFProcessor
from .symbols import SymbolExtractor
from .sections import (
    SectionAnalyzer,
    SECTION_TYPE_CODE,
    SECTION_TYPE_DATA,
    SECTION_TYPE_RODATA,
    SECTION_TYPE_UNKNOWN,
)
from .sources import SourceFileResolver
from .mapper import MemoryMapper
from .defaults import (
    create_default_memory_regions,
    map_sections_to_default_regions,
    DEFAULT_CODE_REGION,
    DEFAULT_DATA_REGION,
)

__all__ = [
    'DWARFProcessor',
    'SymbolExtractor',
    'SectionAnalyzer',
    'SECTION_TYPE_CODE',
    'SECTION_TYPE_DATA',
    'SECTION_TYPE_RODATA',
    'SECTION_TYPE_UNKNOWN',
    'SourceFileResolver',
    'MemoryMapper',
    'create_default_memory_regions',
    'map_sections_to_default_regions',
    'DEFAULT_CODE_REGION',
    'DEFAULT_DATA_REGION',
]
