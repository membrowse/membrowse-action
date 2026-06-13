#!/usr/bin/env python3

"""
keil_parser.py - Keil/Arm armlink scatter file (.sct) parser.

Keil MDK (uVision) projects describe the memory map with a scatter file
instead of a GNU LD script. A scatter file declares load regions, each
containing execution regions:

    LR_IROM1 0x08000000 0x00080000 {     ; load region: base max_size
      ER_IROM1 0x08000000 0x00080000 {   ; execution region
        *.o (RESET, +First)
        *(InRoot$$Sections)
        .ANY (+RO)
      }
      RW_IRAM1 0x20000000 0x00010000 {
        .ANY (+RW +ZI)
      }
    }

Region header grammar (plain, non-preprocessed files):

    NAME (BASE | +OFFSET) [attr ...] [MAX_SIZE]

  NAME      region identifier (e.g. LR_IROM1, ER_IROM1, RW_IRAM1)
  BASE      absolute start address (0x-hex or decimal)
  +OFFSET   start relative to the end of the previous region
  attr      keywords like ABSOLUTE, UNINIT, EMPTY, ALIGN <n>, FILL <n>
  MAX_SIZE  region length; for EMPTY regions a leading '-' grows the
            region downwards from BASE (e.g. a descending stack)

Execution regions become MemoryRegion objects; load regions are emitted
only when they contain no execution regions (armlink's shorthand where
input section selectors sit directly in the load region). Region
attributes ("rx"/"rwx") are inferred from the input section selectors
(+RO/+XO vs +RW/+ZI) with a name-based fallback.

Scatter files that require the C preprocessor (``#! armclang -E`` with
``#define``/``#if`` blocks) are not evaluated; preprocessor lines are
stripped and parsing proceeds on the literal content, which works only
when region headers use plain numeric literals.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .base import LinkerScriptFormatParser, strip_scatter_comments
from .parser import LinkerScriptError, MemoryRegion

logger = logging.getLogger(__name__)

# Region attribute keywords that consume the following token as an argument
_ARG_KEYWORDS = frozenset({
    'ALIGN', 'ALIGNALL', 'PADVALUE', 'FILL', 'SORTTYPE', 'ANY_SIZE',
})

# Standalone region attribute keywords
_FLAG_KEYWORDS = frozenset({
    'ABSOLUTE', 'PI', 'RELOC', 'OVERLAY', 'FIXED', 'UNINIT', 'EMPTY',
    'ZEROPAD', 'NOCOMPRESS', 'AUTO_OVERLAY',
})

_NAME_RE = re.compile(r'^[A-Za-z_]\w*$')

# Selector patterns used to infer region attributes from its body
_CODE_SELECTOR_RE = re.compile(r'\(\s*[^)]*\+\s*(?:RO|XO|ENTRY|FIRST)\b'
                               r'|\bRESET\b|InRoot\$\$Sections',
                               re.IGNORECASE)
_DATA_SELECTOR_RE = re.compile(r'\(\s*[^)]*\+\s*(?:RW|ZI)\b', re.IGNORECASE)


class _RegionHeader:  # pylint: disable=too-few-public-methods
    """Parsed scatter region header line."""

    def __init__(self, name: str, base: Optional[int], relative: bool,
                 max_size: Optional[int]):
        self.name = name
        self.base = base          # absolute base, or offset when relative
        self.relative = relative  # True when base token was '+offset'
        self.max_size = max_size  # None when omitted; may be negative


class KeilScatterParser(LinkerScriptFormatParser):
    """Parser for Keil/Arm armlink scatter (.sct) files."""

    @staticmethod
    def detect(content: str) -> bool:
        """Return True if content looks like an armlink scatter file.

        Requires both a region header (identifier followed by a numeric
        base address and an opening brace, with no ':' as in GNU LD
        output section syntax) and a scatter-specific input section
        selector (.ANY, +RO/+RW/+ZI/+XO, InRoot$$Sections) or region
        attribute keyword.
        """
        # GNU LD scripts with MEMORY { } blocks are never scatter files
        if re.search(r'\bMEMORY\s*\{', content, re.IGNORECASE):
            return False
        stripped = strip_scatter_comments(content)
        header = re.search(
            r'^\s*[A-Za-z_]\w*\s+\+?(?:0[xX][0-9A-Fa-f]+|\d+)\b[^{:;]*\{',
            stripped, re.MULTILINE)
        if not header:
            return False
        body = re.search(
            r'\.ANY\b'
            r'|\(\s*[^)]*\+\s*(?:RO|RW|ZI|XO|FIRST|LAST|ENTRY)\b'
            r'|InRoot\$\$Sections'
            r'|\b(?:UNINIT|EMPTY|ALIGNALL|PADVALUE|ANY_SIZE)\b',
            stripped)
        return bool(body)

    def parse(self, script_path: str) -> Dict[str, MemoryRegion]:
        """Parse a scatter file and return MemoryRegion objects.

        Raises LinkerScriptError on unbalanced braces or when no valid
        memory regions could be extracted.
        """
        path = Path(script_path).resolve()
        content = path.read_text(encoding='utf-8', errors='replace')
        if re.match(r'\s*#!', content):
            logger.warning(
                "%s: scatter file requests preprocessing ('#!'); "
                "preprocessor directives are ignored, parsing literal "
                "content", path.name)
        cleaned = strip_scatter_comments(content)

        regions, containment = self._scan_regions(cleaned, path.name)
        if not regions:
            msg = f"{path.name}: no valid memory regions found in scatter file"
            logger.error(msg)
            raise LinkerScriptError(msg)

        self._validate_regions(regions, containment, path.name)

        logger.debug("Keil scatter parser extracted %d memory regions from %s",
                     len(regions), path.name)
        return regions

    @staticmethod
    def _validate_regions(
            regions: Dict[str, MemoryRegion],
            containment: Dict[str, Tuple[int, int]],
            source: str) -> None:
        """Validate the parsed memory map for overlaps and containment.

        Two checks, both best-effort (warn, never reject):

        - Overlap: emitted regions whose [address, address+limit_size)
          ranges intersect signal an inconsistent map. Execution regions
          legitimately subdivide their parent load region, but each
          subdivision occupies a distinct slice, so siblings should not
          overlap. Mirrors the GNU LD path's overlap validation.
        - Containment: an execution region must fall within its parent
          load region's address range; one that extends past either end
          indicates a malformed scatter file.
        """
        ordered = sorted(
            (r for r in regions.values()
             if r.address is not None and r.limit_size),
            key=lambda r: (r.address, r.limit_size))
        for prev, curr in zip(ordered, ordered[1:]):
            prev_end = prev.address + prev.limit_size
            if curr.address < prev_end:
                logger.warning(
                    "%s: memory regions overlap: '%s' "
                    "[0x%x, 0x%x) and '%s' [0x%x, 0x%x)",
                    source, prev.name, prev.address, prev_end,
                    curr.name, curr.address,
                    curr.address + curr.limit_size)

        for name, (load_base, load_end) in containment.items():
            region = regions.get(name)
            if region is None or region.address is None or not region.limit_size:
                continue
            region_end = region.address + region.limit_size
            if region.address < load_base or region_end > load_end:
                logger.warning(
                    "%s: execution region '%s' [0x%x, 0x%x) extends beyond "
                    "its load region [0x%x, 0x%x)",
                    source, name, region.address, region_end,
                    load_base, load_end)

    # ------------------------------------------------------------------
    # Region scanning
    # ------------------------------------------------------------------

    def _scan_regions(  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
            self, content: str,
            source: str) -> Tuple[Dict[str, MemoryRegion],
                                  Dict[str, Tuple[int, int]]]:
        """Walk braces, collecting load and execution regions.

        Returns the emitted regions and a containment map of execution
        region name -> parent load region [base, end) range (only for
        regions whose parent load range is fully resolved).
        """
        regions: Dict[str, MemoryRegion] = {}
        containment: Dict[str, Tuple[int, int]] = {}
        # Stack frames:
        # [kind, header|None, body_start, exec_count, cursor, region_base]
        # cursor is the running placement point for '+offset' children and
        # advances past each execution region; region_base stays at the
        # region's own resolved base address.
        stack: List[list] = []
        header_start = 0
        file_cursor: Optional[int] = None  # end of previous load region

        for idx, char in enumerate(content):
            if char == '{':
                header_text = content[header_start:idx].strip()
                depth = len(stack)
                if depth == 0:
                    header = self._parse_header(header_text, source)
                    base = self._resolve_base(header, file_cursor, source)
                    stack.append(['load', header, idx + 1, 0, base, base])
                elif depth == 1:
                    header = self._parse_header(header_text, source)
                    stack[0][3] += 1
                    stack.append(['exec', header, idx + 1, 0, None, None])
                else:
                    # Scatter files have no third nesting level; tolerate
                    # and ignore unexpected nested braces.
                    stack.append(['other', None, idx + 1, 0, None, None])
                header_start = idx + 1
            elif char == '}':
                if not stack:
                    msg = f"{source}: unbalanced '}}' in scatter file"
                    logger.error(msg)
                    raise LinkerScriptError(msg)
                kind, header, body_start, exec_count, _, base = stack.pop()
                body = content[body_start:idx]
                if kind == 'exec' and header is not None:
                    load_frame = stack[0] if stack else None
                    self._emit_exec_region(
                        regions, containment, header, body, load_frame,
                        source)
                elif kind == 'load' and header is not None:
                    if exec_count == 0:
                        self._add_region(regions, header.name, base,
                                         header.max_size, body, source)
                    if base is not None and header.max_size is not None:
                        file_cursor = base + header.max_size
                    else:
                        file_cursor = None
                header_start = idx + 1

        if stack:
            msg = f"{source}: unbalanced '{{' in scatter file"
            logger.error(msg)
            raise LinkerScriptError(msg)
        return regions, containment

    def _emit_exec_region(  # pylint: disable=too-many-arguments,too-many-positional-arguments
            self, regions: Dict[str, MemoryRegion],
            containment: Dict[str, Tuple[int, int]], header: _RegionHeader,
            body: str, load_frame: Optional[list], source: str) -> None:
        """Resolve an execution region's base/size and add it.

        Records the parent load region's [base, end) range in
        ``containment`` so a post-parse pass can verify the execution
        region stays within it.
        """
        load_header = load_frame[1] if load_frame else None
        load_cursor = load_frame[4] if load_frame else None
        load_base = load_frame[5] if load_frame else None

        base = self._resolve_base(header, load_cursor, source)
        size = header.max_size

        if size is None and base is not None and load_header is not None:
            # No explicit max size: inside the load region's address range
            # the remaining load region space is the effective limit.
            if (load_base is not None and load_header.max_size is not None
                    and load_base <= base < load_base + load_header.max_size):
                size = load_base + load_header.max_size - base

        if base is None or size is None:
            logger.warning(
                "%s: skipping execution region '%s' "
                "(unresolved base address or size)", source, header.name)
        else:
            self._add_region(regions, header.name, base, size, body, source)
            if (load_base is not None and load_header is not None
                    and load_header.max_size is not None):
                containment[header.name] = (
                    load_base, load_base + load_header.max_size)

        # Advance the parent load region's placement cursor for
        # subsequent '+offset' execution regions. A negative size grows
        # downwards, so the region's top (= base) is the next free point.
        if load_frame is not None:
            if base is not None and size is not None:
                load_frame[4] = base if size < 0 else base + size
            else:
                load_frame[4] = None

    def _add_region(  # pylint: disable=too-many-arguments,too-many-positional-arguments
            self, regions: Dict[str, MemoryRegion], name: str,
            base: Optional[int], size: Optional[int], body: str,
            source: str) -> None:
        if base is None or size is None:
            logger.warning(
                "%s: skipping region '%s' (unresolved base address or size)",
                source, name)
            return
        if size < 0:
            # EMPTY -size grows downwards from base (descending stack)
            base, size = base + size, -size
        if size == 0:
            logger.warning("%s: skipping region '%s' with zero size",
                           source, name)
            return
        if name in regions:
            logger.warning("%s: duplicate region '%s'; later definition wins",
                           source, name)
        regions[name] = MemoryRegion(
            name=name,
            attributes=self._infer_attributes(body, name),
            address=base,
            limit_size=size,
        )

    @staticmethod
    def _resolve_base(header: Optional[_RegionHeader],
                      cursor: Optional[int], source: str) -> Optional[int]:
        """Resolve a header's base address, handling '+offset' bases."""
        if header is None or header.base is None:
            return None
        if not header.relative:
            return header.base
        if cursor is None:
            logger.warning(
                "%s: cannot resolve relative base '+0x%x' for region '%s' "
                "(previous region end unknown)",
                source, header.base, header.name)
            return None
        return cursor + header.base

    # ------------------------------------------------------------------
    # Header parsing
    # ------------------------------------------------------------------

    def _parse_header(self, header_text: str,
                      source: str) -> Optional[_RegionHeader]:
        """Parse 'NAME BASE [attrs] [MAX_SIZE]' into a _RegionHeader."""
        tokens = header_text.split()
        if len(tokens) < 2 or not _NAME_RE.match(tokens[0]):
            if header_text:
                logger.warning("%s: skipping unrecognized scatter region "
                               "header '%s'", source, header_text)
            return None
        name = tokens[0]

        base_token = tokens[1]
        relative = base_token.startswith('+')
        try:
            base: Optional[int] = self._parse_int(base_token.lstrip('+'))
        except ValueError:
            logger.warning("%s: cannot parse base address '%s' for region "
                           "'%s'", source, base_token, name)
            base = None

        max_size, extra = self._parse_trailing_tokens(tokens[2:], name, source)
        if extra:
            logger.warning("%s: ignoring unrecognized tokens %s in region "
                           "'%s' header", source, extra, name)
        return _RegionHeader(name, base, relative, max_size)

    def _parse_trailing_tokens(
            self, tokens: List[str], name: str,
            source: str) -> Tuple[Optional[int], List[str]]:
        """Extract the max size from attribute keywords and trailing tokens."""
        max_size: Optional[int] = None
        extra: List[str] = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            upper = token.upper()
            if upper in _ARG_KEYWORDS:
                i += 2  # keyword + its argument
                continue
            if upper in _FLAG_KEYWORDS:
                i += 1
                continue
            try:
                value = self._parse_int(token)
            except ValueError:
                extra.append(token)
            else:
                if max_size is None:
                    max_size = value
                else:
                    logger.warning(
                        "%s: multiple size values in region '%s' header; "
                        "first one wins", source, name)
            i += 1
        return max_size, extra

    @staticmethod
    def _parse_int(value: str) -> int:
        """Parse a 0x-hex or decimal integer literal, optionally negative."""
        token = value.strip().rstrip(',')
        negative = token.startswith('-')
        if negative:
            token = token[1:]
        if token.lower().startswith('0x'):
            result = int(token, 16)
        elif token.isdigit():
            result = int(token, 10)
        else:
            raise ValueError(f"not an integer literal: {value!r}")
        return -result if negative else result

    # ------------------------------------------------------------------
    # Attribute inference
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_attributes(body: str, name: str) -> str:
        """Infer GNU-style region attributes from input section selectors.

        +RO/+XO selectors mark read-only/code regions ("rx"); +RW/+ZI
        mark writable RAM regions ("rwx"). Falls back to the region name
        (ROM/FLASH vs RAM) when the body has no recognizable selectors.
        """
        has_code = bool(_CODE_SELECTOR_RE.search(body))
        has_data = bool(_DATA_SELECTOR_RE.search(body))
        if has_data:
            return 'rwx'
        if has_code:
            return 'rx'
        upper_name = name.upper()
        if any(key in upper_name for key in ('ROM', 'FLASH', 'XO')):
            return 'rx'
        if any(key in upper_name for key in ('RAM', 'STACK', 'HEAP')):
            return 'rwx'
        return 'rw'
