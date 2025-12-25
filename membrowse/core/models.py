#!/usr/bin/env python3
"""
Data models for memory analysis.

This module contains all the data classes used throughout the memory analysis system,
including TypedDict definitions for structured return types.
"""

from dataclasses import dataclass
from typing import Any, Dict, List
try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict


@dataclass
class MemoryRegion:
    """Represents a memory region from linker scripts"""
    address: int
    limit_size: int
    type: str = "UNKNOWN"  # Type detection removed from parser, defaulting to UNKNOWN
    used_size: int = 0
    free_size: int = 0
    utilization_percent: float = 0.0
    sections: List[Dict[str, Any]] = None

    def __post_init__(self):
        if self.sections is None:
            self.sections = []
        self.free_size = self.limit_size - self.used_size
        self.utilization_percent = (self.used_size / self.limit_size *
                                    100) if self.limit_size > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for JSON serialization"""
        return {
            'address': self.address,
            'limit_size': self.limit_size,
            'type': self.type,
            'used_size': self.used_size,
            'free_size': self.free_size,
            'utilization_percent': self.utilization_percent,
            'sections': self.sections
        }


@dataclass
class MemorySection:
    """Represents a section from the ELF file"""
    name: str
    address: int
    size: int
    type: str
    end_address: int = 0

    def __post_init__(self):
        self.end_address = self.address + self.size


@dataclass
class Symbol:  # pylint: disable=too-many-instance-attributes
    """Represents a symbol from the ELF file"""
    name: str
    address: int
    size: int
    type: str
    binding: str
    section: str
    source_file: str = ""
    visibility: str = ""


@dataclass
class ELFMetadata:
    """Represents ELF file metadata"""
    architecture: str
    file_type: str
    machine: str
    entry_point: int
    bit_width: int
    endianness: str


# TypedDict definitions for structured return types
# These provide better IDE support and type checking for report data

class SymbolDict(TypedDict):
    """Type definition for symbol data in reports.

    This matches the dictionary representation of :class:`Symbol` objects
    as returned in :meth:`ReportGenerator.generate_report`.
    """
    name: str
    address: int
    size: int
    type: str
    binding: str
    section: str
    source_file: str
    visibility: str


class ProgramHeaderDict(TypedDict):
    """Type definition for ELF program header/segment data."""
    type: str
    offset: int
    virt_addr: int
    phys_addr: int
    file_size: int
    mem_size: int
    flags: str
    align: int


class MemoryRegionDict(TypedDict):
    """Type definition for memory region data in reports.

    This matches the dictionary returned by :meth:`MemoryRegion.to_dict`.
    """
    address: int
    limit_size: int
    type: str
    used_size: int
    free_size: int
    utilization_percent: float
    sections: List[Dict[str, Any]]


class MemoryReport(TypedDict):
    """Type definition for the complete memory report.

    This is the return type of :meth:`ReportGenerator.generate_report`.
    Use this for type hints in your code::

        from membrowse import ReportGenerator, MemoryReport

        def analyze_firmware(elf_path: str) -> MemoryReport:
            generator = ReportGenerator(elf_path)
            return generator.generate_report()

        report: MemoryReport = analyze_firmware("firmware.elf")
        print(report['architecture'])  # IDE knows this is a str
        for sym in report['symbols']:  # IDE knows sym is SymbolDict
            print(sym['name'], sym['size'])
    """
    file_path: str
    architecture: str
    entry_point: int
    file_type: str
    machine: str
    symbols: List[SymbolDict]
    program_headers: List[ProgramHeaderDict]
    memory_layout: Dict[str, MemoryRegionDict]
