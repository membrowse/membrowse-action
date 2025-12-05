#!/usr/bin/env python3
"""
Exceptions for memory analysis.

This module contains all the custom exception classes used throughout
the memory analysis system.
"""


class ELFAnalysisError(Exception):
    """Base exception for ELF analysis errors"""


class DWARFParsingError(ELFAnalysisError):
    """Exception raised when DWARF debug info parsing fails"""


class DWARFCUProcessingError(DWARFParsingError):
    """Exception raised when processing a compilation unit fails"""


class DWARFAttributeError(DWARFParsingError):
    """Exception raised when extracting DWARF attribute value fails"""


class SymbolExtractionError(ELFAnalysisError):
    """Exception raised when symbol extraction fails"""


class SectionAnalysisError(ELFAnalysisError):
    """Exception raised when section analysis fails"""


class MemoryRegionMappingError(ELFAnalysisError):
    """Exception raised when memory region mapping fails"""


class AuthenticationError(Exception):
    """Base exception for authentication errors"""


class ForkPRContextError(AuthenticationError):
    """Exception raised when fork PR context cannot be determined"""
