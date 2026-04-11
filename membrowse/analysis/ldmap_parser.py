#!/usr/bin/env python3
"""
GNU LD map file parser for symbol-to-object-file mapping.

Parses map files generated via ``-Wl,-Map=output.map`` (GCC, Clang, Rust).
"""

import re
from typing import Dict, Tuple


# Match input section contribution lines (indented):
#   .text          0x0000000008000010       0xac path/to/file.o
#   .text          0x0000000008000010       0xac libfoo.a(bar.o)
#   COMMON         0x20001ee0        0x4 main.o
_SECTION_CONTRIB_RE = re.compile(
    r'^\s+(\.\S+|COMMON)\s+'    # group 1: section name (indented), or COMMON
    r'(0x[0-9a-fA-F]+)\s+'      # group 2: address
    r'(0x[0-9a-fA-F]+)\s+'      # group 3: size
    r'(.+)$'                     # group 4: file/archive path
)

# Match section-name-only lines (GNU LD wraps long section names to next line):
#  .text.Reset_Handler
#  .text.some_very_long_function_name
_SECTION_NAME_ONLY_RE = re.compile(
    r'^\s+(\.\S+|COMMON)\s*$'
)

# Match continuation lines (address + size + file, no section name):
#                 0x0000000008000188        0x4 build-PYBV10/lib/oofatfs/ff.o
_CONTINUATION_RE = re.compile(
    r'^\s+'
    r'(0x[0-9a-fA-F]+)\s+'      # group 1: address
    r'(0x[0-9a-fA-F]+)\s+'      # group 2: size
    r'(.+)$'                     # group 3: file/archive path
)

# Match archive(object) pattern: libfoo.a(bar.o)
_ARCHIVE_RE = re.compile(r'^(.+\.a)\((.+\.o)\)$')


class MapFileParser:  # pylint: disable=too-few-public-methods
    """Parse GNU LD map file content to extract address-to-object mappings."""

    def parse(self, content: str) -> Dict[int, Tuple[str, str]]:
        """Parse map file content and return address->(archive, object_file) mapping.

        Handles both single-line and two-line continuation formats.
        GNU LD wraps long section names to the next line::

            .text.short   0x08000000  0x10 file.o       (single line)

            .text.very_long_section_name                 (section name only)
                          0x08000000  0x10 file.o        (continuation)

        Args:
            content: Full text content of a GNU LD map file.

        Returns:
            Dict mapping integer addresses to (archive, object_file) tuples.
            Archive is empty string when symbol comes from a bare .o file.
        """
        mappings: Dict[int, Tuple[str, str]] = {}
        pending_section = None

        for line in content.splitlines():
            # Try single-line format first (section + address + size + file)
            match = _SECTION_CONTRIB_RE.match(line)
            if match:
                pending_section = None
                address = int(match.group(2), 16)
                if address == 0:
                    continue

                file_field = match.group(4).strip()
                archive, obj = self._parse_file_field(file_field)
                if obj:
                    # First occurrence wins (GNU LD lists in link order)
                    if address not in mappings:
                        mappings[address] = (archive, obj)
                continue

            # Check for section-name-only line (start of two-line entry)
            name_match = _SECTION_NAME_ONLY_RE.match(line)
            if name_match:
                pending_section = name_match.group(1)
                continue

            # Check for continuation line (address + size + file)
            if pending_section is not None:
                cont_match = _CONTINUATION_RE.match(line)
                if cont_match:
                    address = int(cont_match.group(1), 16)
                    pending_section = None
                    if address == 0:
                        continue

                    file_field = cont_match.group(3).strip()
                    archive, obj = self._parse_file_field(file_field)
                    if obj:
                        if address not in mappings:
                            mappings[address] = (archive, obj)
                    continue
                # Line didn't match continuation — reset pending state
                pending_section = None

        return mappings

    @staticmethod
    def _parse_file_field(field: str) -> Tuple[str, str]:
        """Parse the file/archive field from a map file line.

        Returns:
            (archive, object_file) tuple. Archive is "" for bare .o files.
            Both are ("", "") for linker-synthetic entries.
        """
        if not field or field == 'linker stubs' or field.startswith('*fill*'):
            return ('', '')

        archive_match = _ARCHIVE_RE.match(field)
        if archive_match:
            return (archive_match.group(1), archive_match.group(2))

        if field.endswith('.o'):
            return ('', field)

        return ('', '')
