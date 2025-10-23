"""Onboard subcommand - historical analysis across multiple commits."""

import os
import subprocess
import argparse
import logging
from datetime import datetime

from ..utils.git import run_git_command, get_commit_metadata
from .report import generate_and_upload_report, DEFAULT_API_URL

# Set up logger
logger = logging.getLogger(__name__)


def add_onboard_parser(subparsers) -> argparse.ArgumentParser:
    """
    Add 'onboard' subcommand parser.

    Args:
        subparsers: Subparsers object from argparse

    Returns:
        The onboard parser
    """
    parser = subparsers.add_parser(
        'onboard',
        help='Analyze memory footprints across historical commits for onboarding',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""
Analyzes memory footprints across historical commits and uploads them to MemBrowse.

This command iterates through the last N commits in your Git repository, builds
the firmware for each commit, and uploads the memory footprint analysis to MemBrowse.

How it works:
  1. Iterates through the last N commits in reverse chronological order (oldest first)
  2. Checks out each commit
  3. Runs the build command to compile the firmware
  4. Analyzes the resulting ELF file and linker scripts
  5. Uploads the memory footprint report to MemBrowse platform with Git metadata
  6. Restores the original HEAD when complete

Requirements:
  - Must be run from within a Git repository
  - Build command must produce the ELF file at the specified path
  - All commits must be buildable (script stops on first build failure)
        """,
        epilog="""
examples:
  # Analyze last 50 commits (uses default API URL)
  membrowse onboard 50 "make clean && make" build/firmware.elf "linker.ld" \\
      stm32f4 "$API_KEY"

  # ESP-IDF project with custom API URL
  membrowse onboard 25 "idf.py build" build/firmware.elf \\
      "build/esp-idf/esp32/esp32.project.ld" esp32 "$API_KEY" \\
      https://custom-api.example.com/api/upload
        """)

    # Required arguments
    parser.add_argument(
        'num_commits',
        type=int,
        help='Number of historical commits to process')
    parser.add_argument(
        'build_script',
        help='Shell command to build firmware (quoted)')
    parser.add_argument('elf_path', help='Path to ELF file after build')
    parser.add_argument(
        'ld_scripts',
        help='Space-separated linker script paths (quoted)')
    parser.add_argument(
        'target_name',
        help='Build configuration/target (e.g., esp32, stm32, x86)')
    parser.add_argument('api_key', help='MemBrowse API key')
    parser.add_argument(
        'api_url',
        nargs='?',
        default=DEFAULT_API_URL,
        help='MemBrowse API endpoint URL (default: %(default)s)'
    )

    # Optional flags
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose output'
    )

    return parser


def run_onboard(args: argparse.Namespace) -> int:  # pylint: disable=too-many-locals,too-many-statements
    """
    Execute the onboard subcommand.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    logger.info("Starting historical memory analysis for %s", args.target_name)
    logger.info("Processing last %d commits", args.num_commits)
    logger.info("Build script: %s", args.build_script)
    logger.info("ELF file: %s", args.elf_path)
    logger.info("Linker scripts: %s", args.ld_scripts)

    # Get current branch
    current_branch = (
        run_git_command(['symbolic-ref', '--short', 'HEAD']) or
        run_git_command(['for-each-ref', '--points-at', 'HEAD',
                        '--format=%(refname:short)', 'refs/heads/']) or
        os.environ.get('GITHUB_REF_NAME', 'unknown')
    )

    # Save current HEAD
    original_head = run_git_command(['rev-parse', 'HEAD'])
    if not original_head:
        logger.error("Not in a git repository")
        return 1

    # Get repository name
    remote_url = run_git_command(['config', '--get', 'remote.origin.url'])
    repo_name = 'unknown'
    if remote_url:
        parts = remote_url.rstrip('.git').split('/')
        if parts:
            repo_name = parts[-1]

    # Get commit history (reversed to process oldest first)
    logger.info("Getting commit history...")
    commits_output = run_git_command(
        ['log', '--format=%H', f'-n{args.num_commits}', '--reverse'])
    if not commits_output:
        logger.error("Failed to get commit history")
        return 1

    commits = [c.strip() for c in commits_output.split('\n') if c.strip()]
    total_commits = len(commits)

    # Progress tracking
    successful_uploads = 0
    failed_uploads = 0
    start_time = datetime.now()

    # Process each commit
    for commit_count, commit in enumerate(commits, 1):
        log_prefix = f"({commit})"

        logger.info("")
        logger.info("=== Processing commit %d/%d: %s ===",
                    commit_count, total_commits, commit)

        # Checkout the commit
        logger.info("%s: Checking out commit...", log_prefix)
        result = subprocess.run(
            ['git', 'checkout', commit, '--quiet'],
            capture_output=True,
            check=False
        )
        if result.returncode != 0:
            logger.error("%s: Failed to checkout commit", log_prefix)
            failed_uploads += 1
            continue

        # Clean previous build artifacts
        logger.info("Cleaning previous build artifacts...")
        subprocess.run(['git', 'clean', '-fd'],
                       capture_output=True, check=False)

        # Build the firmware
        logger.info(
            "%s: Building firmware with: %s",
            log_prefix,
            args.build_script)
        result = subprocess.run(
            ['bash', '-c', args.build_script],
            capture_output=False,
            check=False
        )

        if result.returncode != 0:
            logger.error("%s: Build failed, stopping workflow...", log_prefix)
            failed_uploads += 1
            # Restore HEAD and exit
            subprocess.run(
                ['git', 'checkout', original_head, '--quiet'], check=False)
            return 1

        # Check if ELF file was generated
        if not os.path.exists(args.elf_path):
            logger.error("%s: ELF file not found at %s, stopping workflow...",
                         log_prefix, args.elf_path)
            failed_uploads += 1
            subprocess.run(
                ['git', 'checkout', original_head, '--quiet'], check=False)
            return 1

        # Get commit metadata
        metadata = get_commit_metadata(commit)

        logger.info("%s: Generating memory report (commit %d of %d)...",
                    log_prefix, commit_count, total_commits)
        logger.info(
            "%s: Base commit: %s",
            log_prefix,
            metadata.get(
                'base_sha',
                'N/A'))

        # Generate and upload report using helper function
        result = generate_and_upload_report(
            elf_path=args.elf_path,
            ld_scripts=args.ld_scripts,
            target_name=args.target_name,
            api_key=args.api_key,
            api_url=args.api_url,
            commit_sha=commit,
            base_sha=metadata.get('base_sha'),
            branch_name=current_branch,
            repo_name=repo_name,
            commit_message=metadata['commit_message'],
            commit_timestamp=metadata['commit_timestamp'],
            author=metadata.get('author'),
            verbose=args.verbose
        )

        if result != 0:
            logger.error("%s: Failed to generate or upload memory report " +
                         "(commit %d of %d), stopping workflow...",
                         log_prefix, commit_count, total_commits)
            failed_uploads += 1
            subprocess.run(
                ['git', 'checkout', original_head, '--quiet'], check=False)
            return 1

        logger.info(
            "%s: Memory report uploaded successfully (commit %d of %d)",
            log_prefix,
            commit_count,
            total_commits)
        successful_uploads += 1

    # Restore original HEAD
    logger.info("")
    logger.info("Restoring original HEAD...")
    subprocess.run(['git', 'checkout', original_head, '--quiet'], check=False)

    # Print summary
    elapsed = datetime.now() - start_time
    minutes = int(elapsed.total_seconds() // 60)
    seconds = int(elapsed.total_seconds() % 60)
    elapsed_str = f"{minutes:02d}:{seconds:02d}"

    logger.info("")
    logger.info("Historical analysis completed!")
    logger.info("Processed %d commits", total_commits)
    logger.info("Successful uploads: %d", successful_uploads)
    logger.info("Failed uploads: %d", failed_uploads)
    logger.info("Total time: %s", elapsed_str)

    return 0 if failed_uploads == 0 else 1
