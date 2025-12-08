#!/usr/bin/env python3
# pylint: disable=duplicate-code
"""
MemBrowse - Memory analysis for embedded firmware.

This package provides tools for analyzing ELF files and generating
comprehensive memory reports from embedded firmware.
"""

from .core.generator import ReportGenerator
from .core.analyzer import ELFAnalyzer
from .core.models import Symbol, MemoryRegion, MemorySection, ELFMetadata
from .linker.parser import parse_linker_scripts

__version__ = "1.0.1"

__all__ = [
    'ReportGenerator',
    'ELFAnalyzer',
    'Symbol',
    'MemoryRegion',
    'MemorySection',
    'ELFMetadata',
    'parse_linker_scripts',
]
