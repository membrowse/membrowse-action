#!/usr/bin/env python3
"""
Linker script parsing for MemBrowse.

This package provides tools for parsing GNU LD linker scripts and
extracting memory region definitions.
"""

from .parser import parse_linker_scripts, LinkerScriptParser
from .elf_info import get_architecture_info, get_linker_parsing_strategy

__all__ = [
    'parse_linker_scripts',
    'LinkerScriptParser',
    'get_architecture_info',
    'get_linker_parsing_strategy',
]
