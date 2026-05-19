#!/usr/bin/env python3

"""
emproject_parser.py - SEGGER Embedded Studio .emProject XML parser.

In SES projects the IDE owns the memory map: regions like FLASH1/RAM1 are
defined on the project's <configuration> element via the
``linker_section_placements_segments`` attribute, while the .icf script only
references them by name. The .icf alone is therefore insufficient to produce
a memory report. This parser reads the regions directly from the XML so a
single .emProject file is enough input.

Segment grammar (semicolon-separated, trailing ';' optional):

    NAME ATTRS ORIGIN SIZE

  NAME    region name (e.g. FLASH1, RAM1)
  ATTRS   permission letters: any combination of R, W, X (e.g. RX, RWX)
  ORIGIN  start address (decimal or 0x-prefixed hex)
  SIZE    region length (decimal or 0x-prefixed hex)
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET  # nosec B405 - input is local file written by SES
from pathlib import Path
from typing import Dict, Optional

from .base import LinkerScriptFormatParser
from .parser import LinkerScriptError, MemoryRegion

logger = logging.getLogger(__name__)


class SEGGEREmProjectParser(LinkerScriptFormatParser):
    """Parser for SEGGER Embedded Studio ``.emProject`` XML files."""

    _LINKER_SEGMENTS_ATTR = "linker_section_placements_segments"

    @staticmethod
    def detect(content: str) -> bool:
        """Return True if content looks like a SEGGER ES .emProject file.

        The DOCTYPE is the strongest signal; the <solution> root tag is the
        fallback for files without it.
        """
        head = content.lstrip()[:512]
        return (
            "CrossStudio_Project_File" in head
            or head.startswith("<solution")
            or "<solution " in head
        )

    def parse(self, script_path: str) -> Dict[str, MemoryRegion]:
        """Parse an .emProject XML file and return MemoryRegion objects.

        Raises LinkerScriptError if the XML is malformed, the segments
        attribute is missing, or no valid segments were extracted.
        """
        path = Path(script_path).resolve()
        try:
            tree = ET.parse(str(path))  # nosec B314 - input is local trusted file
        except ET.ParseError as exc:
            raise LinkerScriptError(
                f"{path.name}: malformed .emProject XML: {exc}"
            ) from exc

        segments_attr = self._find_segments_attribute(tree.getroot())
        if segments_attr is None:
            raise LinkerScriptError(
                f"{path.name}: no <configuration> element carries "
                f"'{self._LINKER_SEGMENTS_ATTR}'"
            )

        regions = self._parse_segments(segments_attr, path.name)
        if not regions:
            raise LinkerScriptError(
                f"{path.name}: '{self._LINKER_SEGMENTS_ATTR}' yielded "
                "no valid memory regions"
            )

        logger.debug(".emProject parser extracted %d memory regions from %s",
                     len(regions), path.name)
        return regions

    def _find_segments_attribute(self, root: ET.Element) -> Optional[str]:
        """Return the first non-empty linker_section_placements_segments
        attribute found on any <configuration> element, or None.

        SES typically puts memory regions on the project-level Common
        configuration, but per-config overrides are also valid.
        """
        for config in root.iter("configuration"):
            value = config.get(self._LINKER_SEGMENTS_ATTR)
            if value and value.strip():
                return value
        return None

    def _parse_segments(
        self, segments_attr: str, source_name: str
    ) -> Dict[str, MemoryRegion]:
        regions: Dict[str, MemoryRegion] = {}
        for raw in segments_attr.split(";"):
            entry = raw.strip()
            if not entry:
                continue
            parts = entry.split()
            if len(parts) != 4:
                logger.warning(
                    "%s: skipping malformed segment '%s' "
                    "(expected 'NAME ATTRS ORIGIN SIZE')",
                    source_name, entry,
                )
                continue
            name, attrs, origin_s, size_s = parts
            try:
                address = self._parse_int(origin_s)
                limit_size = self._parse_int(size_s)
            except ValueError as exc:
                logger.warning(
                    "%s: cannot parse addresses in segment '%s': %s",
                    source_name, entry, exc,
                )
                continue
            if limit_size <= 0:
                logger.warning(
                    "%s: skipping segment '%s' with non-positive size",
                    source_name, entry,
                )
                continue
            if name in regions:
                logger.warning(
                    "%s: duplicate region '%s'; later definition wins",
                    source_name, name,
                )
            regions[name] = MemoryRegion(
                name=name,
                attributes=attrs.lower(),
                address=address,
                limit_size=limit_size,
            )
        return regions

    @staticmethod
    def _parse_int(value: str) -> int:
        """Parse decimal, 0x-hex, 0o-octal, or 0b-binary integer literal."""
        v = value.strip()
        if not v:
            raise ValueError("empty integer literal")
        return int(v, 0)
