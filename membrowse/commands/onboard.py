"""Onboard subcommand - historical analysis across multiple commits."""

import sys
import os
import subprocess
import argparse
from datetime import datetime
from typing import Optional

from ..utils.git import run_git_command, get_commit_metadata


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
  # Analyze last 50 commits
  membrowse onboard 50 "make clean && make" build/firmware.elf "linker.ld" \\
      stm32f4 "$API_KEY" https://membrowse.appspot.com/api/upload

  # ESP-IDF project
  membrowse onboard 25 "idf.py build" build/firmware.elf \\
      "build/esp-idf/esp32/esp32.project.ld" esp32 "$API_KEY" \\
      https://membrowse.appspot.com/api/upload
        """
    )

    # Required arguments
    parser.add_argument('num_commits', type=int, help='Number of historical commits to process')
    parser.add_argument('build_script', help='Shell command to build firmware (quoted)')
    parser.add_argument('elf_path', help='Path to ELF file after build')
    parser.add_argument('ld_scripts', help='Space-separated linker script paths (quoted)')
    parser.add_argument('target_name', help='Build configuration/target (e.g., esp32, stm32, x86)')
    parser.add_argument('api_key', help='MemBrowse API key')
    parser.add_argument(
        'api_url',
        nargs='?',
        default='https://membrowse.appspot.com/api/upload',
        help='MemBrowse API endpoint URL (default: %(default)s)'
    )

    return parser


def run_onboard(args: argparse.Namespace) -> int:
    """
    Execute the onboard subcommand.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    print(f"Starting historical memory analysis for {args.target_name}")
    print(f"Processing last {args.num_commits} commits")
    print(f"Build script: {args.build_script}")
    print(f"ELF file: {args.elf_path}")
    print(f"Linker scripts: {args.ld_scripts}")

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
        print("Error: Not in a git repository", file=sys.stderr)
        return 1

    # Get repository name
    remote_url = run_git_command(['config', '--get', 'remote.origin.url'])
    repo_name = 'unknown'
    if remote_url:
        parts = remote_url.rstrip('.git').split('/')
        if parts:
            repo_name = parts[-1]

    # Get commit history (reversed to process oldest first)
    print("Getting commit history...")
    commits_output = run_git_command(['log', '--format=%H', f'-n{args.num_commits}', '--reverse'])
    if not commits_output:
        print("Error: Failed to get commit history", file=sys.stderr)
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

        print("")
        print(f"=== Processing commit {commit_count}/{total_commits}: {commit} ===")

        # Checkout the commit
        print(f"{log_prefix}: Checking out commit...")
        result = subprocess.run(
            ['git', 'checkout', commit, '--quiet'],
            capture_output=True,
            check=False
        )
        if result.returncode != 0:
            print(f"{log_prefix}: Failed to checkout commit", file=sys.stderr)
            failed_uploads += 1
            continue

        # Clean previous build artifacts
        print("Cleaning previous build artifacts...")
        subprocess.run(['git', 'clean', '-fd'], capture_output=True, check=False)

        # Build the firmware
        print(f"{log_prefix}: Building firmware with: {args.build_script}")
        result = subprocess.run(
            ['bash', '-c', args.build_script],
            capture_output=False,
            check=False
        )

        if result.returncode != 0:
            print(f"{log_prefix}: Build failed, stopping workflow...", file=sys.stderr)
            failed_uploads += 1
            # Restore HEAD and exit
            subprocess.run(['git', 'checkout', original_head, '--quiet'], check=False)
            return 1

        # Check if ELF file was generated
        if not os.path.exists(args.elf_path):
            print(f"{log_prefix}: ELF file not found at {args.elf_path}, stopping workflow...",
                  file=sys.stderr)
            failed_uploads += 1
            subprocess.run(['git', 'checkout', original_head, '--quiet'], check=False)
            return 1

        # Get commit metadata
        metadata = get_commit_metadata(commit)

        print(f"{log_prefix}: Generating memory report (commit {commit_count} of {total_commits})...")
        print(f"{log_prefix}: Base commit: {metadata.get('base_sha', 'N/A')}")

        # Call membrowse report command
        report_args = [
            'python3', '-m', 'membrowse.cli',
            'report',
            args.elf_path,
            args.ld_scripts,
            '--upload',
            '--api-key', args.api_key,
            '--target-name', args.target_name,
            '--api-url', args.api_url,
            '--commit-sha', commit,
            '--branch-name', current_branch,
            '--repo-name', repo_name,
            '--commit-message', metadata['commit_message'],
            '--commit-timestamp', metadata['commit_timestamp']
        ]

        if metadata.get('base_sha'):
            report_args.extend(['--base-sha', metadata['base_sha']])

        result = subprocess.run(report_args, capture_output=False, check=False)

        if result.returncode != 0:
            print(f"{log_prefix}: Failed to generate or upload memory report " +
                  f"(commit {commit_count} of {total_commits}), stopping workflow...",
                  file=sys.stderr)
            failed_uploads += 1
            subprocess.run(['git', 'checkout', original_head, '--quiet'], check=False)
            return 1

        print(f"{log_prefix}: Memory report uploaded successfully " +
              f"(commit {commit_count} of {total_commits})")
        successful_uploads += 1

    # Restore original HEAD
    print("")
    print("Restoring original HEAD...")
    subprocess.run(['git', 'checkout', original_head, '--quiet'], check=False)

    # Print summary
    elapsed = datetime.now() - start_time
    elapsed_str = f"{int(elapsed.total_seconds() // 60):02d}:{int(elapsed.total_seconds() % 60):02d}"

    print("")
    print("Historical analysis completed!")
    print(f"Processed {total_commits} commits")
    print(f"Successful uploads: {successful_uploads}")
    print(f"Failed uploads: {failed_uploads}")
    print(f"Total time: {elapsed_str}")

    return 0 if failed_uploads == 0 else 1
