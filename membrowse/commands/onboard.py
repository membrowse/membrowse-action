"""Onboard subcommand - historical analysis across multiple commits."""

import os
import subprocess
import argparse
import logging
from datetime import datetime

from ..utils.git import run_git_command, get_commit_metadata
from .report import generate_report, upload_report, DEFAULT_API_URL, _parse_linker_definitions

# Set up logger
logger = logging.getLogger(__name__)


def _create_empty_report(elf_path: str) -> dict:
    """
    Create a minimal empty report structure for failed builds.

    Args:
        elf_path: Path to the ELF file (used in report metadata)

    Returns:
        Empty report dictionary matching the structure of successful reports
    """
    return {
        'file_path': elf_path,
        'architecture': 'unknown',
        'entry_point': 0,
        'file_type': 'unknown',
        'machine': 'unknown',
        'symbols': [],
        'program_headers': [],
        'memory_layout': {}
    }




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
  # Analyze last 50 commits with linker scripts
  membrowse onboard 50 "make clean && make" build/firmware.elf \\
      stm32f4 "$API_KEY" --ld-scripts "linker.ld"

  # Without linker scripts (uses default Code/Data regions)
  membrowse onboard 50 "make clean && make" build/firmware.elf \\
      stm32f4 "$API_KEY"

  # ESP-IDF project with custom API URL
  membrowse onboard 25 "idf.py build" build/firmware.elf \\
      esp32 "$API_KEY" https://custom-api.example.com \\
      --ld-scripts "build/esp-idf/esp32/esp32.project.ld"
        """)

    # Required positional arguments
    parser.add_argument(
        'num_commits',
        type=int,
        help='Number of historical commits to process')
    parser.add_argument(
        'build_script',
        help='Shell command to build firmware (quoted)')
    parser.add_argument('elf_path', help='Path to ELF file after build')
    parser.add_argument(
        'target_name',
        help='Build configuration/target (e.g., esp32, stm32, x86)')
    parser.add_argument('api_key', help='MemBrowse API key')
    parser.add_argument(
        'api_url',
        nargs='?',
        default=DEFAULT_API_URL,
        help='MemBrowse API base URL (default: %(default)s, /upload appended automatically)'
    )

    # Optional flags
    parser.add_argument(
        '--ld-scripts',
        dest='ld_scripts',
        default=None,
        metavar='SCRIPTS',
        help='Space-separated linker script paths (if omitted, uses default '
             'Code/Data regions based on ELF section flags)')
    parser.add_argument(
        '--def',
        dest='linker_defs',
        action='append',
        metavar='VAR=VALUE',
        help='Define linker script variable (can be specified multiple times, '
             'e.g., --def __flash_size__=4096K)'
    )
    parser.add_argument(
        '--build-dirs',
        dest='build_dirs',
        nargs='+',
        metavar='DIR',
        help='Directories that trigger rebuilds. If a commit has no changes in these '
             'directories, upload metadata-only report with identical=True. '
             'Example: --build-dirs src/ lib/ include/'
    )
    parser.add_argument(
        '--initial-commit',
        dest='initial_commit',
        metavar='HASH',
        help='Start processing from this commit hash (must be on the main branch, not a '
             'feature branch commit). If specified and the path from this commit to HEAD '
             'has fewer than num_commits, only those commits are processed.'
    )

    return parser


def _get_repository_info():
    """
    Get repository information including branch and repo name.

    Returns:
        Tuple of (current_branch, original_head, repo_name) or (None, None, None) if not in git repo
    """
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
        return None, None, None

    # Get repository name
    remote_url = run_git_command(['config', '--get', 'remote.origin.url'])
    repo_name = 'unknown'
    if remote_url:
        parts = remote_url.rstrip('.git').split('/')
        if parts:
            repo_name = parts[-1]

    return current_branch, original_head, repo_name


def _get_commit_list(num_commits: int, initial_commit: str = None):
    """
    Get list of commits to process.

    Args:
        num_commits: Maximum number of commits to retrieve
        initial_commit: Optional starting commit hash. If provided, only commits
                        from this commit to HEAD are included (up to num_commits).

    Returns:
        List of commit hashes (oldest first) or None on error
    """
    logger.info("Getting commit history...")

    if initial_commit:
        # Get commits from initial_commit (inclusive) to HEAD, limited to num_commits
        # Use --first-parent to follow only the main branch (not feature branch commits)
        commits_output = run_git_command(
            ['log', '--first-parent', '--format=%H', f'-n{num_commits}',
             '--reverse', f'{initial_commit}^..HEAD'])
        if not commits_output:
            # If initial_commit^ fails (first commit in repo), try without ^
            commits_output = run_git_command(
                ['log', '--first-parent', '--format=%H', f'-n{num_commits}',
                 '--reverse', f'{initial_commit}..HEAD'])
            if commits_output:
                # Prepend initial_commit since it wasn't included
                initial_hash = run_git_command(['rev-parse', initial_commit])
                if initial_hash:
                    commits_output = initial_hash + '\n' + commits_output
            else:
                # Fallback: just the initial commit itself
                commits_output = run_git_command(['rev-parse', initial_commit])
    else:
        # Use --first-parent to follow only the main branch (not feature branch commits)
        commits_output = run_git_command(
            ['log', '--first-parent', '--format=%H', f'-n{num_commits}', '--reverse'])

    if not commits_output:
        return None

    return [c.strip() for c in commits_output.split('\n') if c.strip()]


def _commit_has_changes_in_dirs(commit: str, build_dirs: list[str]) -> bool:
    """
    Check if a commit has changes in any of the specified directories.

    Args:
        commit: Commit hash to check
        build_dirs: List of directory paths to check for changes

    Returns:
        True if commit has changes in any of the build_dirs, False otherwise
    """
    # Get parent commit (handle first commit case)
    parent = run_git_command(['rev-parse', f'{commit}^'])
    if not parent:
        # First commit - always consider as having changes
        return True

    # Get list of changed files between parent and commit
    changed_files = run_git_command(['diff', '--name-only', parent, commit])
    if not changed_files:
        return False

    changed_list = [f.strip() for f in changed_files.split('\n') if f.strip()]

    # Check if any changed file is in one of the build directories
    for changed_file in changed_list:
        for build_dir in build_dirs:
            # Normalize: ensure build_dir ends with / for prefix matching
            normalized_dir = build_dir.rstrip('/') + '/'
            if changed_file.startswith(normalized_dir) or changed_file == build_dir.rstrip('/'):
                return True

    return False


def _create_metadata_only_report(elf_path: str) -> dict:
    """
    Create a minimal report for commits with no build-relevant changes.

    Contains only structural fields, no actual analysis.

    Args:
        elf_path: Path to the ELF file (used in report metadata)

    Returns:
        Minimal report dictionary for identical commits
    """
    return {
        'file_path': elf_path,
        'architecture': None,
        'entry_point': None,
        'file_type': None,
        'machine': None,
        'symbols': [],
        'program_headers': [],
        'memory_layout': {}
    }


def _handle_build_failure(result, log_prefix, elf_path):
    """
    Handle build failure by logging output and creating empty report.

    Args:
        result: subprocess.CompletedProcess result
        log_prefix: Logging prefix string
        elf_path: Path to ELF file (for empty report)

    Returns:
        Empty report dictionary
    """
    logger.warning(
        "%s: Build failed with exit code %d, will upload empty report",
        log_prefix, result.returncode)

    # Log build output (last 50 lines at INFO level, full output at DEBUG)
    if result.stdout or result.stderr:
        logger.error("%s: Build output:", log_prefix)
        combined_output = (result.stdout or "") + (result.stderr or "")
        output_lines = combined_output.strip().split('\n')
        if len(output_lines) > 50 and not logger.isEnabledFor(logging.DEBUG):
            logger.error("... (showing last 50 lines, use -v DEBUG for full output) ...")
            for line in output_lines[-50:]:
                logger.error(line)
        else:
            for line in output_lines:
                logger.error(line)

    return _create_empty_report(elf_path)


def run_onboard(args: argparse.Namespace) -> int:  # pylint: disable=too-many-locals,too-many-statements,too-many-branches
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
    if args.ld_scripts:
        logger.info("Linker scripts: %s", args.ld_scripts)
    else:
        logger.info("Using default Code/Data regions (no linker scripts)")

    # Parse linker variable definitions
    linker_variables = _parse_linker_definitions(getattr(args, 'linker_defs', None))
    if linker_variables:
        for key, value in linker_variables.items():
            logger.info("User-defined linker variable: %s = %s", key, value)

    # Get repository information
    current_branch, original_head, repo_name = _get_repository_info()
    if not original_head:
        logger.error("Not in a git repository")
        return 1

    # Get commit list
    commits = _get_commit_list(args.num_commits, getattr(args, 'initial_commit', None))
    if not commits:
        logger.error("Failed to get commit history")
        return 1

    total_commits = len(commits)

    # Progress tracking
    successful_uploads = 0
    failed_uploads = 0
    start_time = datetime.now()

    # Helper function to restore HEAD and print summary on exit
    def finalize_and_return(exit_code: int) -> int:
        """Restore original HEAD, print summary, and return exit code."""
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
        logger.info("Processed %d commits", len(commits))
        logger.info("Successful uploads: %d", successful_uploads)
        if failed_uploads > 0:
            logger.info("Failed uploads: %d", failed_uploads)
        logger.info("Total time: %s", elapsed_str)

        return exit_code

    # Process each commit
    for commit_count, commit in enumerate(commits, 1):
        log_prefix = f"({commit})"

        logger.info("")
        logger.info("Processing commit %d/%d: %s",
                       commit_count, total_commits, commit[:8])

        # Check if we need to build this commit (when --build-dirs is specified)
        # First commit is always built to establish baseline
        build_dirs = getattr(args, 'build_dirs', None)
        if build_dirs and commit_count > 1 and not _commit_has_changes_in_dirs(commit, build_dirs):
            # No changes in build directories - upload metadata-only with identical=True
            logger.info("%s: No changes in build directories, marking as identical", log_prefix)

            metadata = get_commit_metadata(commit)
            report = _create_metadata_only_report(args.elf_path)
            commit_info = {
                'commit_hash': metadata['commit_sha'],
                'base_commit_hash': metadata.get('base_sha'),
                'branch_name': current_branch,
                'repository': repo_name,
                'commit_message': metadata['commit_message'],
                'commit_timestamp': metadata['commit_timestamp'],
                'author_name': metadata.get('author_name'),
                'author_email': metadata.get('author_email'),
                'pr_number': None
            }

            try:
                upload_report(
                    report=report,
                    commit_info=commit_info,
                    target_name=args.target_name,
                    api_key=args.api_key,
                    api_url=args.api_url,
                    identical=True
                )
                logger.info("%s: Identical report uploaded (commit %d of %d)",
                            log_prefix, commit_count, total_commits)
                successful_uploads += 1
            except (ValueError, RuntimeError) as e:
                logger.error("%s: Failed to upload identical report", log_prefix)
                logger.error("%s: Error: %s", log_prefix, e)
                failed_uploads += 1
                return finalize_and_return(1)

            continue  # Skip to next commit - no checkout/build needed

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
            capture_output=True,
            text=True,
            check=False
        )

        # Get commit metadata (returns old key names: commit_sha, base_sha)
        metadata = get_commit_metadata(commit)

        # Handle build failures vs missing files after successful build
        build_failed = False

        # Case 1: Build failed (non-zero exit code)
        if result.returncode != 0:
            report = _handle_build_failure(
                result, log_prefix, args.elf_path)
            build_failed = True

        # Case 2: Build returned success but ELF missing - treat as failed build
        elif not os.path.exists(args.elf_path):
            logger.warning(
                "%s: Build script succeeded (exit 0) but ELF file not found at %s - "
                "treating as failed build",
                log_prefix, args.elf_path)

            report = _handle_build_failure(
                result, log_prefix, args.elf_path)
            build_failed = True

        # Case 3: Build succeeded and files exist - generate report
        else:
            logger.info("%s: Generating memory report (commit %d of %d)...",
                          log_prefix, commit_count, total_commits)
            try:
                report = generate_report(
                    elf_path=args.elf_path,
                    ld_scripts=args.ld_scripts,
                    skip_line_program=False,
                    linker_variables=linker_variables
                )
            except ValueError as e:
                logger.error(
                    "%s: Failed to generate memory report (commit %d of %d) - configuration error",
                    log_prefix, commit_count, total_commits)
                logger.error("%s: Error: %s", log_prefix, e)
                logger.error("%s: Stopping onboard workflow...", log_prefix)
                failed_uploads += 1
                return finalize_and_return(1)

        # Build commit_info in metadata['git'] format (map old keys to new)
        commit_info = {
            'commit_hash': metadata['commit_sha'],
            'base_commit_hash': metadata.get('base_sha'),
            'branch_name': current_branch,
            'repository': repo_name,
            'commit_message': metadata['commit_message'],
            'commit_timestamp': metadata['commit_timestamp'],
            'author_name': metadata.get('author_name'),
            'author_email': metadata.get('author_email'),
            'pr_number': None
        }

        try:
            upload_report(
                report=report,
                commit_info=commit_info,
                target_name=args.target_name,
                api_key=args.api_key,
                api_url=args.api_url,
                build_failed=build_failed
            )
            if build_failed:
                logger.info(
                    "%s: Empty report uploaded successfully for failed build (commit %d of %d)",
                    log_prefix,
                    commit_count,
                    total_commits)
            else:
                logger.info(
                    "%s: Memory report uploaded successfully (commit %d of %d)",
                    log_prefix,
                    commit_count,
                    total_commits)
            successful_uploads += 1
        except (ValueError, RuntimeError) as e:
            logger.error(
                "%s: Failed to upload memory report (commit %d of %d), stopping workflow...",
                log_prefix, commit_count, total_commits)
            logger.error("%s: Error: %s", log_prefix, e)
            failed_uploads += 1
            return finalize_and_return(1)

    # Finalize with summary and restoration
    return finalize_and_return(0 if failed_uploads == 0 else 1)
