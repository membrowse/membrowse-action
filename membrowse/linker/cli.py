#!/usr/bin/env python3
"""
CLI wrapper for linker script parser.

This module provides command-line interface for parsing linker scripts
and outputting memory regions as JSON.
"""

import sys
import json
from .parser import parse_linker_scripts


def main():
    """Main CLI entry point for linker script parsing."""
    if len(sys.argv) < 2:
        print(
            "Usage: python -m membrowse.linker.cli <linker_script1> [linker_script2] ...")
        sys.exit(1)

    try:
        regions = parse_linker_scripts(sys.argv[1:])
        # Output JSON to stdout for consumption by other tools
        print(json.dumps(regions, indent=2))
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
