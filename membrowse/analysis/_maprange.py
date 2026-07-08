#!/usr/bin/env python3
"""Shared scaffolding for the GNU LD / LLD / IAR map-file parsers.

All three parsers build the same artifact — a sorted list of half-open
``[start, end)`` object ranges — applying the same rules: skip zero-address
and zero-size entries, keep the first occurrence of each start address
(link order wins), and drop entries with no attributable object file.
``RangeAccumulator`` centralizes that spine; ``resolve_archive_object``
centralizes the shared ``archive(object)`` / bare-object field parsing used
by the GNU LD and LLD parsers.
"""

from typing import List, Pattern, Tuple


class RangeAccumulator:
    """Accumulate half-open ``[start, end)`` object ranges with dedup + sort.

    Each ``add`` enforces the shared map-parser invariants; ``finalize``
    returns the ranges sorted by start address.
    """

    def __init__(self) -> None:
        self._ranges: List[Tuple[int, int, str, str]] = []
        self._seen_starts = set()

    def add(self, address: int, size: int, archive: str, obj: str) -> None:
        """Record a range, skipping zero/duplicate/unattributable entries.

        A zero address or size, an already-seen start address, or an empty
        ``obj`` are all dropped. An empty ``obj`` does not consume the start
        address, so a later attributable entry at the same address still wins.
        """
        if address == 0 or size == 0:
            return
        if address in self._seen_starts:
            return
        if not obj:
            return
        self._seen_starts.add(address)
        self._ranges.append((address, address + size, archive, obj))

    def finalize(self) -> List[Tuple[int, int, str, str]]:
        """Return the accumulated ranges sorted by start address."""
        return sorted(self._ranges, key=lambda r: r[0])


def resolve_archive_object(
    field: str, archive_re: Pattern[str]
) -> Tuple[str, str]:
    """Resolve a map-file file field to ``(archive, object_file)``.

    Shared tail for the GNU LD and LLD parsers: match the format-specific
    ``archive(object)`` pattern, else accept a bare ``.o``/``.obj`` object,
    else attribute to nothing. Callers apply their own synthetic-source
    guard before calling this.

    Returns:
        ``(archive, object_file)``; ``archive`` is "" for bare objects, and
        ``("", "")`` for anything unrecognized.
    """
    archive_match = archive_re.match(field)
    if archive_match:
        return (archive_match.group(1), archive_match.group(2))
    if field.endswith('.o') or field.endswith('.obj'):
        return ('', field)
    return ('', '')
