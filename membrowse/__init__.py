#!/usr/bin/env python3
# pylint: disable=duplicate-code
"""
MemBrowse - Memory analysis for embedded firmware.

This package provides tools for analyzing ELF files and generating
comprehensive memory reports from embedded firmware.

Quick Start
-----------
Generate a memory report from an ELF file and linker scripts::

    import membrowse

    # Parse linker scripts to get memory regions
    regions = membrowse.parse_linker_scripts(
        ["memory.ld", "sections.ld"],
        elf_file="firmware.elf"  # optional, improves parsing accuracy
    )

    # Generate a full memory report
    generator = membrowse.ReportGenerator(
        elf_path="firmware.elf",
        memory_regions_data=regions
    )
    report = generator.generate_report()

    # Access report data
    print(f"Architecture: {report['architecture']}")
    for symbol in report['symbols']:
        print(f"{symbol['name']}: {symbol['size']} bytes")

Low-Level ELF Analysis
----------------------
For direct access to symbols, sections, and metadata::

    import membrowse

    analyzer = membrowse.ELFAnalyzer("firmware.elf")

    # Get metadata
    meta = analyzer.get_metadata()
    print(f"Architecture: {meta.architecture}, Machine: {meta.machine}")

    # Get all symbols sorted by size
    symbols = analyzer.get_symbols()
    largest = sorted(symbols, key=lambda s: s.size, reverse=True)[:10]
    for sym in largest:
        print(f"{sym.name}: {sym.size} bytes in {sym.section}")

    # Get sections
    section_totals, sections = analyzer.get_sections()

Parse Linker Scripts Only
-------------------------
Extract memory regions without ELF analysis::

    import membrowse

    regions = membrowse.parse_linker_scripts(["STM32F4.ld"])
    for name, region in regions.items():
        print(f"{name}: 0x{region['address']:08x}, {region['limit_size']} bytes")

Classes
-------
ReportGenerator
    Main entry point for generating memory reports from ELF files.
ELFAnalyzer
    Low-level ELF analysis for direct access to symbols, sections, and metadata.

Data Models
-----------
Symbol
    Represents a symbol (function, variable) from the ELF file.
MemoryRegion
    Represents a memory region (FLASH, RAM) from linker scripts.
MemorySection
    Represents an ELF section (.text, .data, .bss).
ELFMetadata
    ELF file metadata (architecture, entry point, etc.).

Type Hints
----------
For type checking and IDE support, use these TypedDict types::

    from membrowse import MemoryReport, SymbolDict

    def process_report(report: MemoryReport) -> None:
        for sym in report['symbols']:  # IDE knows sym is SymbolDict
            print(sym['name'], sym['size'])

MemoryReport
    Complete report structure from generate_report().
SymbolDict
    Symbol data as a dictionary.
MemoryRegionDict
    Memory region data as a dictionary.
ProgramHeaderDict
    ELF program header data.

Functions
---------
parse_linker_scripts(ld_scripts, elf_file=None)
    Parse GNU LD linker scripts to extract memory regions.
"""

from importlib.metadata import version, PackageNotFoundError

from .core.generator import ReportGenerator
from .core.analyzer import ELFAnalyzer
from .core.models import (
    Symbol,
    MemoryRegion,
    MemorySection,
    ELFMetadata,
    # TypedDict types for type hints
    MemoryReport,
    SymbolDict,
    MemoryRegionDict,
    ProgramHeaderDict,
)
from .linker.parser import parse_linker_scripts

try:
    __version__ = version('membrowse')
except PackageNotFoundError:
    __version__ = "0.0.0"  # Package not installed

__all__ = [
    # Classes
    'ReportGenerator',
    'ELFAnalyzer',
    # Data models
    'Symbol',
    'MemoryRegion',
    'MemorySection',
    'ELFMetadata',
    # Type hints (TypedDict)
    'MemoryReport',
    'SymbolDict',
    'MemoryRegionDict',
    'ProgramHeaderDict',
    # Functions
    'parse_linker_scripts',
]
