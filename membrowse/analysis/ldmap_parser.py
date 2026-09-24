#!/usr/bin/env python3
"""
GNU LD map file parser for symbol-to-object-file mapping.

Parses map files generated via ``-Wl,-Map=output.map`` (GCC, Clang, Rust).
"""

import re
from typing import List, Optional, Tuple

from .mapfilter import OutputSectionFilter


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

# Match an output section header, which starts in column 0 (input section
# lines are indented). Other column-0 lines (LOAD, OUTPUT(...), memory
# regions, common symbols, cross-reference entries) lack the
# "name address size" shape and are not headers:
#   .text           0x0000000008000000     0x5480
#   .debug_line     0x0000000000000000     0xbe47
#   .data           0x0000000020000000        0x4 load address 0x080002f4
_OUTPUT_ADDRESS_SIZE = (
    r'(0x[0-9a-fA-F]+)\s+'                    # address
    r'0x[0-9a-fA-F]+'                          # size
    r'(?:\s+load address\s+0x[0-9a-fA-F]+)?'   # LMA when it differs
    r'\s*$'
)
_OUTPUT_SECTION_RE = re.compile(r'^([^\s*]\S*)\s+' + _OUTPUT_ADDRESS_SIZE)

# GNU LD wraps long output section names like input section names; the
# address and size then follow on an indented line without a file field
# (a header with no address line at all is an empty section):
#   .ARM.attributes
#                   0x0000000000000000       0x2e
# Names need not start with '.' (Zephyr's ``_static_thread_data_area``);
# '(' is excluded so a bare ``OUTPUT(zephyr.elf)`` is not taken as one.
_OUTPUT_NAME_ONLY_RE = re.compile(r'^([^\s*(][^\s(]*)\s*$')
_OUTPUT_ADDRESS_ONLY_RE = re.compile(r'^\s+' + _OUTPUT_ADDRESS_SIZE)

# Match archive(object) pattern: libfoo.a(bar.o) or libfoo.a(bar.cpp.obj).
# CMake builds (especially on Windows hosts) emit objects with a .obj suffix.
_ARCHIVE_RE = re.compile(r'^(.+\.a)\((.+\.(?:o|obj))\)$')


class _OutputSectionState:
    """Track the current output section and whether its rows are dropped."""

    def __init__(self, section_filter: Optional[OutputSectionFilter]):
        self._filter = section_filter
        self._name: Optional[str] = None
        # True right after a wrapped header, whose address comes next.
        self._expect_address = False
        self.skip = False

    def _enter(self, name: str, address: Optional[int]) -> None:
        self._name = name
        self.skip = (self._filter is not None
                     and self._filter.skip(name, address))

    def column0(self, line: str) -> None:
        """Handle a column-0 line; only header-shaped ones change state."""
        self._expect_address = False
        header = _OUTPUT_SECTION_RE.match(line)
        if header:
            self._enter(header.group(1), int(header.group(2), 16))
            return
        name_only = _OUTPUT_NAME_ONLY_RE.match(line)
        if name_only:
            self._expect_address = True
            self._enter(name_only.group(1), None)

    def wrapped_address(self, line: str) -> bool:
        """Consume the address line of a wrapped header; True if it was one."""
        if not self._expect_address:
            return False
        self._expect_address = False
        match = _OUTPUT_ADDRESS_ONLY_RE.match(line)
        if not match:
            return False
        self._enter(self._name, int(match.group(1), 16))
        return True


class MapFileParser:  # pylint: disable=too-few-public-methods
    """Parse GNU LD map file content to extract address-to-object mappings."""

    def parse(self, content: str,
              section_filter: Optional[OutputSectionFilter] = None
              ) -> List[Tuple[int, int, str, str]]:
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

        Input sections of non-ALLOC output sections (``.debug_*``,
        ``.comment``, ``.ARM.attributes``) carry file offsets, not
        addresses, and overlap real address ranges. ``section_filter``
        decides per output section (from its name and header address)
        whether its input sections are dropped.

        Args:
            content: Full text content of a GNU LD map file.
            section_filter: Filter for non-ALLOC output sections; None
                keeps every input section.

        Returns:
            List of ``(start, end, archive, object_file)`` tuples sorted by
            ``start``. ``archive`` is "" for bare .o files. Zero-size and
            zero-address entries are skipped.
        """
        ranges: List[Tuple[int, int, str, str]] = []
        seen_starts = set()
        pending_section = None
        output = _OutputSectionState(section_filter)

        def emit(address: int, size: int, file_field: str) -> None:
            if address == 0 or size == 0:
                return
            if address in seen_starts:
                # First occurrence wins (GNU LD lists in link order).
                return
            archive, obj = self._parse_file_field(file_field.strip())
            if not obj:
                return
            seen_starts.add(address)
            ranges.append((address, address + size, archive, obj))

        for line in content.splitlines():
            if line and not line[0].isspace():
                # Column-0 lines are never input sections.
                pending_section = None
                output.column0(line)
                continue
            if output.wrapped_address(line) or output.skip:
                continue

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

        ranges.sort(key=lambda r: r[0])
        return ranges

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

        if field.endswith('.o') or field.endswith('.obj'):
            return ('', field)

        return ('', '')
