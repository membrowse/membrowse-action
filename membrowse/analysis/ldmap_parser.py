#!/usr/bin/env python3
"""
GNU LD map file parser for symbol-to-object-file mapping.

Parses map files generated via ``-Wl,-Map=output.map`` (GCC, Clang, Rust).
"""

import re
from typing import List, Tuple

from ._maprange import RangeAccumulator, resolve_archive_object


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

# Match archive(object) pattern: libfoo.a(bar.o) or libfoo.a(bar.cpp.obj).
# CMake builds (especially on Windows hosts) emit objects with a .obj suffix.
_ARCHIVE_RE = re.compile(r'^(.+\.a)\((.+\.(?:o|obj))\)$')


class MapFileParser:  # pylint: disable=too-few-public-methods
    """Parse GNU LD map file content to extract address-to-object mappings."""

    def parse(self, content: str) -> List[Tuple[int, int, str, str]]:
        """Parse map file content into half-open address ranges.

        GNU LD emits one entry per linker INPUT section (e.g. ``.text.foo``
        for a single function), each carrying an address, size, and source
        file. Multiple ELF symbols can live inside a single input section —
        compiler-generated tables (``CSWTCH.*``), constants pools, and
        anonymous-namespace helpers all share the section's address window.
        Range-based lookup attributes every byte in the section, not just
        the first symbol.

        Handles both single-line and two-line continuation formats. GNU LD
        wraps long section names to the next line::

            .text.short   0x08000000  0x10 file.o       (single line)

            .text.very_long_section_name                 (section name only)
                          0x08000000  0x10 file.o        (continuation)

        Args:
            content: Full text content of a GNU LD map file.

        Returns:
            List of ``(start, end, archive, object_file)`` tuples sorted by
            ``start``. ``archive`` is "" for bare .o files. Zero-size and
            zero-address entries are skipped.
        """
        acc = RangeAccumulator()
        pending_section = None

        def emit(address: int, size: int, file_field: str) -> None:
            archive, obj = self._parse_file_field(file_field.strip())
            acc.add(address, size, archive, obj)

        for line in content.splitlines():
            # Try single-line format first (section + address + size + file)
            match = _SECTION_CONTRIB_RE.match(line)
            if match:
                pending_section = None
                emit(int(match.group(2), 16),
                     int(match.group(3), 16),
                     match.group(4))
                continue

            # Check for continuation line (address + size + file) for an
            # already-pending wrapped section name.
            if pending_section is not None:
                cont_match = _CONTINUATION_RE.match(line)
                if cont_match:
                    pending_section = None
                    emit(int(cont_match.group(1), 16),
                         int(cont_match.group(2), 16),
                         cont_match.group(3))
                    continue
                # Line didn't continue the pending section. Fall through so
                # the current line still gets a chance to be recognized as
                # the start of a new wrapped entry.
                pending_section = None

            # Check for section-name-only line (start of two-line entry)
            name_match = _SECTION_NAME_ONLY_RE.match(line)
            if name_match:
                pending_section = name_match.group(1)
                continue

        return acc.finalize()

    @staticmethod
    def _parse_file_field(field: str) -> Tuple[str, str]:
        """Parse the file/archive field from a map file line.

        Returns:
            (archive, object_file) tuple. Archive is "" for bare .o files.
            Both are ("", "") for linker-synthetic entries.
        """
        if not field or field == 'linker stubs' or field.startswith('*fill*'):
            return ('', '')
        return resolve_archive_object(field, _ARCHIVE_RE)
