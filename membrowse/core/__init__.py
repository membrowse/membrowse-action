#!/usr/bin/env python3
# pylint: disable=duplicate-code
"""
Core analysis components for MemBrowse.

This package contains the main coordination logic for ELF analysis
and memory report generation.
"""

from .generator import ReportGenerator
from .analyzer import ELFAnalyzer
from .models import Symbol, MemoryRegion, MemorySection, ELFMetadata
from .exceptions import (
    ELFAnalysisError,
    DWARFParsingError,
    DWARFCUProcessingError,
    DWARFAttributeError,
    SymbolExtractionError,
    SectionAnalysisError,
)

__all__ = [
    'ReportGenerator',
    'ELFAnalyzer',
    'Symbol',
    'MemoryRegion',
    'MemorySection',
    'ELFMetadata',
    'ELFAnalysisError',
    'DWARFParsingError',
    'DWARFCUProcessingError',
    'DWARFAttributeError',
    'SymbolExtractionError',
    'SectionAnalysisError',
]
