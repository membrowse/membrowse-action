"""Report subcommand - generates memory footprint reports from ELF files."""

import os
import json
import tempfile
import argparse
import logging
from importlib.metadata import version

from ..utils.git import detect_github_metadata
from ..linker.parser import LinkerScriptParser
from ..core.generator import ReportGenerator
from ..api.client import MemBrowseUploader

# Set up logger
logger = logging.getLogger(__name__)

# Default MemBrowse API endpoint
DEFAULT_API_URL = 'https://www.membrowse.com/api/upload'


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
      --api-url https://www.membrowse.com/api/upload

  # GitHub Actions mode (auto-detects Git metadata)
  membrowse report firmware.elf "linker.ld" --github \\
      --target-name stm32f4 --api-key "$API_KEY"
        """
    )

    # Required arguments
    parser.add_argument('elf_path', help='Path to ELF file')
    parser.add_argument(
        'ld_scripts',
        help='Space-separated linker script paths (quoted)')

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
    upload_group.add_argument(
        '--target-name',
        help='Build configuration/target (e.g., esp32, stm32, x86)')
    upload_group.add_argument(
        '--api-url',
        default=DEFAULT_API_URL,
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
    git_group.add_argument(
        '--commit-timestamp',
        help='Commit timestamp (ISO format)')
    git_group.add_argument('--author', help='Commit author')
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


def generate_and_upload_report(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals,too-many-return-statements,too-many-branches,too-many-statements
    elf_path: str,
    ld_scripts: str,
    target_name: str = None,
    api_key: str = None,
    api_url: str = None,
    commit_sha: str = None,
    base_sha: str = None,
    branch_name: str = None,
    repo_name: str = None,
    commit_message: str = None,
    commit_timestamp: str = None,
    author: str = None,
    skip_line_program: bool = False,
    verbose: bool = False,
    upload: bool = True,
    github: bool = False
) -> int:
    """
    Generate and optionally upload a memory footprint report.

    This function is designed to be called programmatically from other modules.

    Args:
        elf_path: Path to ELF file
        ld_scripts: Space-separated linker script paths
        target_name: Build configuration/target (e.g., esp32, stm32, x86) - required if upload=True
        api_key: MemBrowse API key - required if upload=True
        api_url: MemBrowse API endpoint URL
        commit_sha: Git commit SHA (optional)
        base_sha: Git base/parent commit SHA (optional)
        branch_name: Git branch name (optional)
        repo_name: Repository name (optional)
        commit_message: Commit message (optional)
        commit_timestamp: Commit timestamp in ISO format (optional)
        author: Commit author (optional)
        skip_line_program: Skip DWARF line program processing (optional)
        verbose: Enable verbose output (optional)
        upload: Whether to upload the report (default: True)
        github: Whether to auto-detect Git metadata from GitHub Actions env (default: False)

    Returns:
        Exit code (0 for success, 1 for error)
    """
    # Use default API URL if not provided
    if api_url is None:
        api_url = DEFAULT_API_URL

    # Determine upload mode
    upload_mode = upload or github

    # Validate upload requirements
    if upload_mode:
        if not api_key:
            logger.error(
                "--api-key is required when using --upload or --github")
            return 1
        if not target_name:
            logger.error(
                "--target-name is required when using --upload or --github")
            return 1

    # Set up log prefix
    log_prefix = "MemBrowse"
    if commit_sha:
        log_prefix = f"({commit_sha})"

    logger.info("%s: Started Memory Report generation", log_prefix)
    if target_name:
        logger.info("Target: %s", target_name)
    logger.info("ELF file: %s", elf_path)
    logger.info("Linker scripts: %s", ld_scripts)

    # Validate ELF file exists
    if not os.path.exists(elf_path):
        logger.error("ELF file not found: %s", elf_path)
        return 1

    # Validate linker scripts exist
    ld_array = ld_scripts.split()
    for ld_script in ld_array:
        if not os.path.exists(ld_script):
            logger.error("Linker script not found: %s", ld_script)
            return 1

    # Parse memory regions from linker scripts
    logger.info("%s: Parsing memory regions from linker scripts.", log_prefix)
    try:
        parser = LinkerScriptParser(ld_array, elf_file=elf_path)
        memory_regions_data = parser.parse_memory_regions()
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("%s: Failed to parse memory regions: %s", log_prefix, e)
        return 1

    # Generate JSON report
    logger.info("%s: Generating JSON memory report...", log_prefix)
    try:
        generator = ReportGenerator(
            elf_path,
            memory_regions_data,
            skip_line_program=skip_line_program
        )
        report = generator.generate_report(verbose)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("%s: Failed to generate memory report: %s", log_prefix, e)
        return 1

    logger.info("%s: JSON report generated successfully", log_prefix)

    # If not uploading, print report to stdout and exit
    if not upload_mode:
        logger.info("%s: Local mode - printing report to stdout", log_prefix)
        print(json.dumps(report, indent=2))
        return 0

    # Upload mode - write report to temp file for upload
    # pylint: disable=consider-using-with
    report_file = tempfile.NamedTemporaryFile(
        mode='w', suffix='.json', delete=False
    )
    report_file_name = report_file.name

    try:
        with open(report_file.name, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        report_file.close()

        # Upload mode - detect Git metadata if --github flag
        if github:
            git_metadata = detect_github_metadata()
            # Override with detected metadata (only if not already set)
            if not commit_sha:
                commit_sha = git_metadata.commit_sha
            if not base_sha:
                base_sha = git_metadata.base_sha
            if not branch_name:
                branch_name = git_metadata.branch_name
            if not repo_name:
                repo_name = git_metadata.repo_name
            if not commit_message:
                commit_message = git_metadata.commit_message
            if not commit_timestamp:
                commit_timestamp = git_metadata.commit_timestamp
            if not author:
                author = git_metadata.author

        # Upload report
        logger.info(
            "%s: Starting upload of report to MemBrowse...",
            log_prefix)

        # Build metadata structure
        metadata = {
            'git': {
                'commit_hash': commit_sha,
                'commit_message': commit_message,
                'commit_timestamp': commit_timestamp,
                'author': author,
                'base_commit_hash': base_sha,
                'branch_name': branch_name,
                'pr_number': None  # pr_number not passed as parameter
            },
            'repository': repo_name,
            'target_name': target_name,
            'analysis_version': version('membrowse')
        }

        # Load base report and enrich with metadata
        with open(report_file.name, 'r', encoding='utf-8') as f:
            base_report = json.load(f)

        enriched_report = {
            'metadata': metadata,
            'memory_analysis': base_report
        }

        # Upload to MemBrowse
        uploader = MemBrowseUploader(api_key, api_url)
        success = uploader.upload_report(enriched_report)

        if not success:
            logger.error("%s: Failed to upload report", log_prefix)
            return 1

        logger.info("%s: Memory report uploaded successfully", log_prefix)
        return 0

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("%s: Failed to upload report: %s", log_prefix, e)
        return 1

    finally:
        # Cleanup report temp file
        try:
            os.unlink(report_file_name)
        except Exception:  # pylint: disable=broad-exception-caught
            pass


def run_report(args: argparse.Namespace) -> int:
    """
    Execute the report subcommand.

    This function converts argparse.Namespace to function parameters
    and calls generate_and_upload_report().

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    return generate_and_upload_report(
        elf_path=args.elf_path,
        ld_scripts=args.ld_scripts,
        target_name=getattr(args, 'target_name', None),
        api_key=getattr(args, 'api_key', None),
        api_url=getattr(args, 'api_url', None),
        commit_sha=getattr(args, 'commit_sha', None),
        base_sha=getattr(args, 'base_sha', None),
        branch_name=getattr(args, 'branch_name', None),
        repo_name=getattr(args, 'repo_name', None),
        commit_message=getattr(args, 'commit_message', None),
        commit_timestamp=getattr(args, 'commit_timestamp', None),
        author=getattr(args, 'author', None),
        skip_line_program=getattr(args, 'skip_line_program', False),
        verbose=getattr(args, 'verbose', False),
        upload=getattr(args, 'upload', False),
        github=getattr(args, 'github', False)
    )
