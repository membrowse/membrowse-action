#!/usr/bin/env python3
"""
Data models for memory analysis.

This module contains all the data classes used throughout the memory analysis system.
"""

from dataclasses import dataclass
from typing import Any, Dict, List


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
