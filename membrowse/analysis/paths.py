#!/usr/bin/env python3
"""
Path forms shared by the DWARF processor and the source file resolver.

Debug information records the paths the compiler was given, so an ELF built
on Windows carries drive-letter (``C:/...``) or UNC (``//server/...``) paths
with either separator, whatever host later analyses it. Everything here works
on the slash-normalized form so joins and prefix comparisons behave the same
on every host.
"""

import os
import posixpath
import re
from typing import Optional

# A drive-letter or UNC path from a Windows toolchain, slash-normalized
WINDOWS_ABS_RE = re.compile(r'^(?:[A-Za-z]:/|//)')


def to_posix(path: Optional[str]) -> Optional[str]:
    """`path` with forward slashes; None and '' pass through."""
    return path.replace('\\', '/') if path else path


def is_windows_path(posix_path: str) -> bool:
    """Whether a slash-normalized path is a Windows drive or UNC path."""
    return bool(WINDOWS_ABS_RE.match(posix_path))


def is_abs(posix_path: str) -> bool:
    """Whether a slash-normalized path is absolute on POSIX or Windows."""
    return posixpath.isabs(posix_path) or is_windows_path(posix_path)


def case_insensitive(*posix_paths: str) -> bool:
    """Whether paths compare case-insensitively: on a Windows host, or when
    any of them comes from a Windows file system (which ignores case),
    whichever host the analysis runs on."""
    return os.name == 'nt' or any(is_windows_path(p) for p in posix_paths)
