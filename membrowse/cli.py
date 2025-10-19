#!/usr/bin/env python3
"""
Main CLI entry point for MemBrowse.

Provides a unified command-line interface with subcommands for memory analysis.
"""

import sys
import logging
import argparse

from .commands.report import add_report_parser, run_report
from .commands.onboard import add_onboard_parser, run_onboard


def create_parser() -> argparse.ArgumentParser:
    """
    Create the main argument parser with subcommands.

    Returns:
        Configured ArgumentParser
    """
    parser = argparse.ArgumentParser(
        prog='membrowse',
        description='Memory footprint analysis tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
subcommands:
  report    Generate memory footprint report (local or upload mode)
  onboard   Analyze and upload memory footprints across historical commits

examples:
  # Local mode - generate report to stdout (no upload)
  membrowse report firmware.elf "linker.ld"

  # Upload mode - upload report to MemBrowse platform
  membrowse report firmware.elf "linker.ld" --upload \\
      --target-name esp32 --api-key "$API_KEY"

  # GitHub mode - auto-detect Git metadata and upload
  membrowse report firmware.elf "linker.ld" --github \\
      --target-name stm32f4 --api-key "$API_KEY"

  # Onboard - analyze and upload last 50 commits
  membrowse onboard 50 "make build" build/firmware.elf "linker.ld" \\
      esp32 "$API_KEY" https://www.membrowse.com/api/upload

For more help on a subcommand:
  membrowse report --help
  membrowse onboard --help
        """
    )

    # Create subparsers
    subparsers = parser.add_subparsers(
        title='subcommands',
        description='Available commands',
        dest='subcommand',
        required=True
    )

    # Add subcommand parsers
    add_report_parser(subparsers)
    add_onboard_parser(subparsers)

    return parser


def main() -> int:
    """
    Main entry point for the CLI.

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    parser = create_parser()
    args = parser.parse_args()

    # Configure logging based on verbose flag
    # Messages go to stderr to keep stdout clean for JSON output
    # Default: ERROR level (only show errors)
    # Verbose: INFO level (show all informational messages)
    log_level = logging.INFO if getattr(
        args, 'verbose', False) else logging.ERROR
    logging.basicConfig(
        level=log_level,
        format='%(message)s',
        stream=sys.stderr
    )

    # Route to appropriate subcommand
    if args.subcommand == 'report':
        return run_report(args)
    if args.subcommand == 'onboard':
        return run_onboard(args)
    parser.print_help()
    return 1


if __name__ == '__main__':
    sys.exit(main())
