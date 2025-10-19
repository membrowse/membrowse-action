"""Report subcommand - generates memory usage reports from ELF files."""

import sys
import json
import tempfile
import subprocess
import argparse
from typing import Optional

from ..utils.git import detect_github_metadata


def add_report_parser(subparsers) -> argparse.ArgumentParser:
    """
    Add 'report' subcommand parser.

    Args:
        subparsers: Subparsers object from argparse

    Returns:
        The report parser
    """
    parser = subparsers.add_parser(
        'report',
        help='Generate memory footprint report from ELF and linker scripts',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  # Local mode - output JSON to stdout
  membrowse report firmware.elf "linker.ld"

  # Save to file
  membrowse report firmware.elf "linker.ld" > report.json

  # Upload to MemBrowse
  membrowse report firmware.elf "linker.ld" --upload \\
      --api-key "$API_KEY" --target-name esp32 \\
      --api-url https://membrowse.appspot.com/api/upload

  # GitHub Actions mode (auto-detects Git metadata)
  membrowse report firmware.elf "linker.ld" --github \\
      --target-name stm32f4 --api-key "$API_KEY"
        """
    )

    # Required arguments
    parser.add_argument('elf_path', help='Path to ELF file')
    parser.add_argument('ld_scripts', help='Space-separated linker script paths (quoted)')

    # Mode flags
    mode_group = parser.add_argument_group('mode options')
    mode_group.add_argument(
        '--upload',
        action='store_true',
        help='Upload report to MemBrowse platform'
    )
    mode_group.add_argument(
        '--github',
        action='store_true',
        help='GitHub Actions mode - auto-detect Git metadata and upload'
    )

    # Upload parameters (only relevant with --upload or --github)
    upload_group = parser.add_argument_group(
        'upload options',
        'Required when using --upload or --github'
    )
    upload_group.add_argument('--api-key', help='MemBrowse API key')
    upload_group.add_argument('--target-name', help='Build configuration/target (e.g., esp32, stm32, x86)')
    upload_group.add_argument(
        '--api-url',
        default='https://membrowse.appspot.com/api/upload',
        help='MemBrowse API endpoint (default: %(default)s)'
    )

    # Optional Git metadata (for --upload mode without --github)
    git_group = parser.add_argument_group(
        'git metadata options',
        'Optional Git metadata (auto-detected in --github mode)'
    )
    git_group.add_argument('--commit-sha', help='Git commit SHA')
    git_group.add_argument('--base-sha', help='Git base/parent commit SHA')
    git_group.add_argument('--branch-name', help='Git branch name')
    git_group.add_argument('--repo-name', help='Repository name')
    git_group.add_argument('--commit-message', help='Commit message')
    git_group.add_argument('--commit-timestamp', help='Commit timestamp (ISO format)')
    git_group.add_argument('--pr-number', help='Pull request number')

    # Performance options
    perf_group = parser.add_argument_group('performance options')
    perf_group.add_argument(
        '--skip-line-program',
        action='store_true',
        help='Skip DWARF line program processing for faster analysis'
    )
    perf_group.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose output'
    )

    return parser


def run_report(args: argparse.Namespace) -> int:
    """
    Execute the report subcommand.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    # Determine upload mode
    upload_mode = args.upload or args.github

    # Validate upload requirements
    if upload_mode:
        if not args.api_key:
            print("Error: --api-key is required when using --upload or --github", file=sys.stderr)
            return 1
        if not args.target_name:
            print("Error: --target-name is required when using --upload or --github",
                  file=sys.stderr)
            return 1

    # Set up log prefix
    log_prefix = "MemBrowse"
    if args.commit_sha:
        log_prefix = f"({args.commit_sha})"

    print(f"{log_prefix}: Started Memory Report generation", file=sys.stderr)
    if args.target_name:
        print(f"Target: {args.target_name}", file=sys.stderr)
    print(f"ELF file: {args.elf_path}", file=sys.stderr)
    print(f"Linker scripts: {args.ld_scripts}", file=sys.stderr)

    # Parse memory regions from linker scripts
    print(f"{log_prefix}: Parsing memory regions from linker scripts.", file=sys.stderr)
    memory_regions_file = tempfile.NamedTemporaryFile(
        mode='w', suffix='.json', delete=False
    )

    try:
        # Call linker parser
        ld_array = args.ld_scripts.split()
        result = subprocess.run(
            ['python3', '-m', 'membrowse.linker.cli'] + ld_array,
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0:
            print(f"{log_prefix}: Error: Failed to parse memory regions", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            return 1

        memory_regions_file.write(result.stdout)
        memory_regions_file.close()

        # Generate JSON report
        print(f"{log_prefix}: Generating JSON memory report...", file=sys.stderr)
        report_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        )
        report_file.close()

        cli_args = [
            'python3', '-m', 'membrowse.core.cli',
            '--elf-path', args.elf_path,
            '--memory-regions', memory_regions_file.name,
            '--output', report_file.name
        ]

        if args.skip_line_program:
            cli_args.append('--skip-line-program')
        if args.verbose:
            cli_args.append('--verbose')

        result = subprocess.run(cli_args, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            print(f"{log_prefix}: Error: Failed to generate memory report", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            return 1

        print(f"{log_prefix}: JSON report generated successfully", file=sys.stderr)

        # If not uploading, print report to stdout and exit
        if not upload_mode:
            print(f"{log_prefix}: Local mode - printing report to stdout", file=sys.stderr)
            with open(report_file.name, 'r', encoding='utf-8') as f:
                print(f.read())
            return 0

        # Upload mode - detect Git metadata if --github flag
        if args.github:
            metadata = detect_github_metadata()
            # Override with detected metadata
            if not args.commit_sha:
                args.commit_sha = metadata.commit_sha
            if not args.base_sha:
                args.base_sha = metadata.base_sha
            if not args.branch_name:
                args.branch_name = metadata.branch_name
            if not args.repo_name:
                args.repo_name = metadata.repo_name
            if not args.commit_message:
                args.commit_message = metadata.commit_message
            if not args.commit_timestamp:
                args.commit_timestamp = metadata.commit_timestamp
            if not args.pr_number:
                args.pr_number = metadata.pr_number

        # Upload report
        print(f"{log_prefix}: Starting upload of report to MemBrowse...", file=sys.stderr)

        upload_args = [
            'python3', '-m', 'membrowse.api.client',
            '--base-report', report_file.name,
            '--target-name', args.target_name,
            '--api-key', args.api_key,
            '--api-endpoint', args.api_url
        ]

        # Add optional Git metadata
        if args.commit_sha:
            upload_args.extend(['--commit-sha', args.commit_sha])
        if args.commit_message:
            upload_args.extend(['--commit-message', args.commit_message])
        if args.commit_timestamp:
            upload_args.extend(['--timestamp', args.commit_timestamp])
        if args.base_sha:
            upload_args.extend(['--base-sha', args.base_sha])
        if args.branch_name:
            upload_args.extend(['--branch-name', args.branch_name])
        if args.repo_name:
            upload_args.extend(['--repository', args.repo_name])
        if args.pr_number:
            upload_args.extend(['--pr-number', args.pr_number])

        result = subprocess.run(upload_args, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            print(f"{log_prefix}: Error: Failed to upload report", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            return 1

        print(f"{log_prefix}: Memory report uploaded successfully", file=sys.stderr)
        return 0

    finally:
        # Cleanup temp files
        try:
            import os
            os.unlink(memory_regions_file.name)
            if upload_mode:
                os.unlink(report_file.name)
        except Exception:  # pylint: disable=broad-exception-caught
            pass
