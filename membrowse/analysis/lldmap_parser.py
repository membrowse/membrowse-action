#!/usr/bin/env python3
"""
LLD (LLVM linker) map file parser for symbol-to-object-file mapping.

Parses map files generated via ``-Wl,-Map=output.map`` with ld.lld
(Clang/LLVM toolchains, LLVM Embedded Toolchain for Arm, Zephyr, Rust).
"""

import re
from typing import Dict, Tuple


# LLD map file row:
#
#     <VMA-hex> <LMA-hex> <size-hex> <align-dec> <content>
#
# Addresses are lowercase hex with no "0x" prefix and are right-aligned
# within a fixed-width column.  Content is one of:
#
#     ".text"                    output section name
#     "file.o:(.section)"        input section entry (what we want)
#     "__abi_tag"                symbol row
#
# Input-section entries are identified semantically by the ":(" delimiter,
# which is unique to the "file:(.section)" syntax.  This is more robust
# than counting separator spaces — LLD's column widths vary by target.
_LLD_ROW_RE = re.compile(
    r'^\s*([0-9a-f]+)\s+'       # group 1: VMA
    r'[0-9a-f]+\s+'             # LMA (unused)
    r'[0-9a-f]+\s+'             # size (unused - ELF symtab has sizes)
    r'\d+ +'                    # align + separator
    r'(\S.*)$'                  # group 2: content
)

# Like GNU LD's _ARCHIVE_RE but also accepts .rlib (Rust crate archives,
# ar-format archives used by rustc).
_LLD_ARCHIVE_RE = re.compile(r'^(.+\.(?:a|rlib))\((.+\.o)\)$')


class LLDMapFileParser:  # pylint: disable=too-few-public-methods
    """Parse LLD map file content to extract address-to-object mappings."""

    def parse(self, content: str) -> Dict[int, Tuple[str, str]]:
        """Parse LLD map file content.

        Only input-section rows carry library attribution; output section
        and symbol rows are ignored.  Linker-synthetic sources (``<internal>``,
        ``<linker-created>``) are skipped.

        Args:
            content: Full text content of an ld.lld map file.

        Returns:
            Dict mapping integer addresses to (archive, object_file) tuples.
            Archive is empty string when the symbol comes from a bare .o file.
        """
        mappings: Dict[int, Tuple[str, str]] = {}

        for line in content.splitlines():
            match = _LLD_ROW_RE.match(line)
            if not match:
                continue

            content_field = match.group(2)
            # Strip trailing ":(.section)" or ":(.section+0xNN)" suffix.
            # Its presence also signals this is an input-section row —
            # output sections and symbol rows lack the ":(" delimiter.
            # rfind handles Windows-style paths ("C:\...") correctly.
            colon_paren = content_field.rfind(':(')
            if colon_paren < 0:
                continue

            address = int(match.group(1), 16)
            if address == 0:
                continue

            file_ref = content_field[:colon_paren]
            archive, obj = self._parse_file_field(file_ref)
            if obj and address not in mappings:
                mappings[address] = (archive, obj)

        return mappings

    @staticmethod
    def _parse_file_field(field: str) -> Tuple[str, str]:
        """Parse the file/archive field from an LLD input-section entry."""
        # LLD marks synthetic sources with angle brackets: <internal>,
        # <linker-created>.  They have no object file to attribute to.
        if field.startswith('<'):
            return ('', '')

        archive_match = _LLD_ARCHIVE_RE.match(field)
        if archive_match:
            return (archive_match.group(1), archive_match.group(2))

        if field.endswith('.o'):
            return ('', field)

        return ('', '')
