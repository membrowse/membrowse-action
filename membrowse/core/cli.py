#!/usr/bin/env python3
# pylint: disable=duplicate-code
"""
Command-line interface for memory report generation.

This module provides the CLI functionality for generating memory reports
from ELF files and memory region data.
"""

import argparse
import json
import sys

from .generator import ReportGenerator
from .exceptions import ELFAnalysisError


class CLIHandler:
    """Handles command-line interface for memory report generation"""

    @staticmethod
    def create_parser() -> argparse.ArgumentParser:
        """Create command-line argument parser.

        Returns:
            Configured ArgumentParser for memory report generation
        """
        parser = argparse.ArgumentParser(
            description='Generate memory report from ELF and linker scripts',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  %(prog)s --elf-path firmware.elf --memory-regions regions.json --output report.json
  %(prog)s --elf-path app.elf --memory-regions memory_layout.json --output memory.json
  %(prog)s --elf-path test.elf --output analysis.json
  %(prog)s --elf-path firmware.elf --output symbols_only.json
            """
        )

        parser.add_argument(
            '--elf-path',
            required=True,
            help='Path to ELF file'
        )
        parser.add_argument(
            '--memory-regions',
            required=False,
            help='Path to JSON file containing memory regions data (optional)'
        )
        parser.add_argument(
            '--output',
            required=True,
            help='Output JSON file path'
        )
        parser.add_argument(
            '--verbose',
            required=False,
            default=False,
            action='store_true',
            help='Enable verbose output'
        )
        parser.add_argument(
            '--skip-line-program',
            required=False,
            default=False,
            action='store_true',
            help=(
                'Skip DWARF line program processing for faster analysis '
                '(may reduce source file coverage by 0.3-7%%)'
            )
        )

        return parser

    @staticmethod
    def run(args: argparse.Namespace) -> None:
        """Execute the memory report generation.

        Args:
            args: Parsed command-line arguments
        """
        try:
            # Load memory regions from JSON file (if provided)
            memory_regions_data = None
            if args.memory_regions:
                with open(args.memory_regions, 'r', encoding='utf-8') as f:
                    memory_regions_data = json.load(f)

            generator = ReportGenerator(
                args.elf_path,
                memory_regions_data,
                skip_line_program=args.skip_line_program
            )
            report = generator.generate_report(args.verbose)

            # Write report to file
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2)
            if args.verbose:
                print(f"Memory report generated successfully: {args.output}")

        except ELFAnalysisError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Unexpected error: {e}", file=sys.stderr)
            sys.exit(1)


def main() -> None:
    """Main entry point for the memory report CLI."""
    parser = CLIHandler.create_parser()
    args = parser.parse_args()
    CLIHandler.run(args)


if __name__ == '__main__':
    main()
