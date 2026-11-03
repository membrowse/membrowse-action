#!/usr/bin/env python3
"""
The ELF symbol table, read once per ELF file.

pyelftools parses a symbol each time iter_symbols() yields it: about 1 s per
pass over a 30000 symbol table. Several analysis steps need the symbols, so
they are parsed once and the list is shared by every step of an ELFFile.
"""

import weakref
from typing import List, Optional

_SYMBOLS: 'weakref.WeakKeyDictionary' = weakref.WeakKeyDictionary()


def symtab_symbols(elffile, section=None) -> Optional[List]:
    """The symbols of elffile's .symtab, parsed on the first call.

    Args:
        elffile: An open pyelftools ELFFile, the key of the cache.
        section: The .symtab section when the caller already has it; it is
            looked up by name otherwise.

    Returns:
        The pyelftools Symbol objects in table order, None when the ELF has
        no .symtab. Callers must not modify the list.
    """
    try:
        return _SYMBOLS[elffile]
    except KeyError:
        cacheable = True
    except TypeError:  # not weak-referenceable (test doubles): no cache
        cacheable = False
    if section is None:
        section = elffile.get_section_by_name('.symtab')
        if section is None:
            return None
    symbols = list(section.iter_symbols())
    if cacheable:
        _SYMBOLS[elffile] = symbols
    return symbols
