#!/usr/bin/env python3
"""
Analysis components for MemBrowse.

This package contains specialized analyzers for extracting information
from ELF files including DWARF debug info, symbols, sections, and source files.
"""

from .dwarf import DWARFProcessor
from .symbols import SymbolExtractor
from .sections import SectionAnalyzer
from .sources import SourceFileResolver
from .mapper import MemoryMapper

__all__ = [
    'DWARFProcessor',
    'SymbolExtractor',
    'SectionAnalyzer',
    'SourceFileResolver',
    'MemoryMapper',
]
