#!/usr/bin/env python3

"""
base.py - Abstract base for linker script format parsers.

Defines the LinkerScriptFormatParser protocol and LinkerFormatDetector
for content-based format identification.
"""

import re

from abc import ABC, abstractmethod
from typing import Dict


class LinkerScriptFormatParser(ABC):
    """Abstract base class for format-specific linker script parsers.

    Subclasses handle one linker script dialect each. The orchestrating
    LinkerScriptParser selects the appropriate subclass via detect().
    """

    @abstractmethod
    def parse(self, script_path: str) -> Dict:
        """Parse a single script file.

        Returns:
            Dict mapping region name (str) to MemoryRegion objects.
        """

    @staticmethod
    @abstractmethod
    def detect(content: str) -> bool:
        """Return True if content matches this parser's format."""


class LinkerFormatDetector:  # pylint: disable=too-few-public-methods
    """Content-based detection of linker script dialects."""

    # IAR ICF keywords that cannot appear in GNU LD scripts
    _ICF_MARKERS = (
        "define symbol",
        "define memory",
        "define region",
        "define block",
        "place in",
        "place at address",
    )

    @classmethod
    def is_icf(cls, content: str) -> bool:
        """Detect IAR EWARM ICF format from content.

        Requires at least 2 marker matches to prevent false positives on
        GNU LD scripts that happen to contain 'define' as a symbol name.
        Rejects files containing GNU LD MEMORY blocks to prevent false
        positives from ICF-like comments in LD scripts.
        """
        # GNU LD scripts with MEMORY { } blocks are never ICF
        if re.search(r'\bMEMORY\s*\{', content, re.IGNORECASE):
            return False
        # SEGGER .emProject XML files contain ICF markers in comments/attrs
        # — exclude them so they route to the dedicated XML parser.
        if cls.is_emproject(content):
            return False
        content_lower = content.lower()
        matches = sum(1 for m in cls._ICF_MARKERS if m in content_lower)
        return matches >= 2

    @classmethod
    def is_emproject(cls, content: str) -> bool:
        """Detect a SEGGER Embedded Studio ``.emProject`` XML file.

        Matches the CrossStudio DOCTYPE or a <solution> root element near
        the start of the file. Whole-file scan is bounded so this remains
        cheap on large files.
        """
        head = content.lstrip()[:512]
        if "CrossStudio_Project_File" in head:
            return True
        return head.startswith("<solution") or "<solution " in head
