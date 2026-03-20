# pylint: disable=too-many-lines
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

This command iterates through commits in your Git repository, builds the firmware
for each commit, and uploads the memory footprint analysis to MemBrowse.

Two modes of commit selection:
  - Last N commits: provide num_commits to process the most recent N commits
  - Explicit list: use --commits to specify exact commits/tags to process

How it works:
  1. Iterates through commits (oldest first)
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

  # Analyze specific commits/tags (parent chain is faked)
  membrowse onboard --commits "v1.0 v1.1 v2.0" "make clean && make" \\
      build/firmware.elf stm32f4 "$API_KEY" --ld-scripts "linker.ld"

  # ESP-IDF project with custom API URL
  membrowse onboard 25 "idf.py build" build/firmware.elf \\
      esp32 "$API_KEY" https://custom-api.example.com \\
      --ld-scripts "build/esp-idf/esp32/esp32.project.ld"
        """)

    # Positional arguments (num_commits is optional when --commits is used)
    parser.add_argument(
        'num_commits',
        type=int,
        nargs='?',
        default=None,
        help='Number of historical commits to process (required unless --commits is used)')
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
        help='MemBrowse API base URL (default: %(default)s, /upload appended automatically). '
             'When using --commits, use --api-url instead of the positional argument.'
    )
    parser.add_argument(
        '--api-url',
        dest='api_url_flag',
        metavar='URL',
        default=None,
        help='MemBrowse API base URL (alternative to positional api_url, '
             'required when using --commits with a custom URL)'
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
             'has fewer than num_commits, only those commits are processed. '
             'Mutually exclusive with --commits.'
    )
    parser.add_argument(
        '--commits',
        dest='commits',
        metavar='REFS',
        help='Space-separated list of commit hashes and/or tags to process (quoted). '
             'Commits are processed in the given order with a faked parent chain. '
             'Mutually exclusive with num_commits and --initial-commit. '
             'Example: --commits "v1.0 v1.1 abc123 v2.0"'
    )
    parser.add_argument(
        '--binary-search',
        dest='binary_search',
        action='store_true',
        help='Use binary search to minimize builds. Builds endpoints of commit ranges, '
             'compares memory fingerprints, and only builds midpoints where changes are '
             'detected. Mutually exclusive with --build-dirs.'
    )
    parser.add_argument(
        '--dry-run',
        dest='dry_run',
        action='store_true',
        help='Run the full onboard workflow (checkout, build, analyze) but skip '
             'uploading reports. Logs what would be uploaded for each commit.'
    )

    return parser


def _resolve_and_validate_commits(commits_str: str) -> list[str]:
    """
    Resolve commit references (hashes, tags) and validate they exist.

    Args:
        commits_str: Space-separated string of commit refs

    Returns:
        List of resolved full commit SHAs

    Raises:
        ValueError: If any ref cannot be resolved
    """
    refs = commits_str.split()
    if not refs:
        raise ValueError("--commits requires at least one commit reference")

    resolved = []
    invalid = []
    for ref in refs:
        sha = run_git_command(['rev-parse', '--verify', f'{ref}^{{commit}}'])
        if sha:
            resolved.append(sha)
        else:
            invalid.append(ref)

    if invalid:
        raise ValueError(
            f"Cannot resolve commit reference(s): {', '.join(invalid)}")

    return resolved


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


def _extract_fingerprint(report: dict) -> tuple:
    """
    Extract a memory fingerprint from a report for comparison.

    The fingerprint is a sorted tuple of (region_name, used_size) pairs,
    capturing actual memory usage while ignoring address changes from
    recompilation.

    Args:
        report: Memory analysis report dict with 'memory_layout' key

    Returns:
        Sorted tuple of (region_name, used_size) tuples
    """
    memory_layout = report.get('memory_layout', {})
    return tuple(
        (name, region_data.get('used_size', 0))
        for name, region_data in sorted(memory_layout.items())
    )


def _build_and_generate_report(commit, args, linker_variables):
    """
    Checkout, build, and generate a memory report for a single commit.

    Args:
        commit: Commit hash
        args: Parsed CLI arguments (build_script, elf_path, ld_scripts)
        linker_variables: Parsed linker variable definitions

    Returns:
        Tuple of (report, build_failed) where report is the report dict
        and build_failed is True if the build failed.

    Raises:
        RuntimeError: If checkout fails
        ValueError: If report generation fails with a configuration error
    """
    log_prefix = f"({commit})"

    # Checkout the commit
    logger.info("%s: Checking out commit...", log_prefix)
    result = subprocess.run(
        ['git', 'checkout', commit, '--quiet'],
        capture_output=True,
        check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to checkout commit {commit}")

    # Clean previous build artifacts
    logger.info("Cleaning previous build artifacts...")
    subprocess.run(['git', 'clean', '-fd'],
                   capture_output=True, check=False)

    # Build the firmware
    logger.info("%s: Building firmware with: %s", log_prefix, args.build_script)
    result = subprocess.run(
        ['bash', '-c', args.build_script],
        capture_output=True,
        text=True,
        check=False
    )

    # Case 1: Build failed (non-zero exit code)
    if result.returncode != 0:
        return _handle_build_failure(result, log_prefix, args.elf_path), True

    # Case 2: Build returned success but ELF missing
    if not os.path.exists(args.elf_path):
        logger.warning(
            "%s: Build script succeeded (exit 0) but ELF file not found at %s - "
            "treating as failed build",
            log_prefix, args.elf_path)
        return _handle_build_failure(result, log_prefix, args.elf_path), True

    # Case 3: Build succeeded - generate report
    logger.info("%s: Generating memory report...", log_prefix)
    report = generate_report(
        elf_path=args.elf_path,
        ld_scripts=args.ld_scripts,
        skip_line_program=False,
        linker_variables=linker_variables
    )

    # Case 3b: Build succeeded but report has empty memory_layout
    # (e.g. linker script parsing failed for this commit).
    # Treat as a build failure so the API accepts it instead of
    # rejecting with 400 "memory_layout is required and cannot be empty".
    if not report.get('memory_layout'):
        logger.error(
            "%s: Build succeeded but memory_layout is empty "
            "(linker script parsing may have failed) - "
            "treating as failed build",
            log_prefix)
        return _create_empty_report(args.elf_path), True

    return report, False


def _build_commit_info(commit, current_branch, repo_name, base_sha_override=None):
    """
    Build commit_info dict for upload from a commit hash.

    Args:
        commit: Commit hash
        current_branch: Branch name
        repo_name: Repository name
        base_sha_override: If provided, use this instead of the real git parent

    Returns:
        Dict with Git metadata for upload_report
    """
    metadata = get_commit_metadata(commit)
    return {
        'commit_hash': metadata['commit_sha'],
        'base_commit_hash': base_sha_override if base_sha_override is not None else metadata.get('base_sha'),
        'branch_name': current_branch,
        'repository': repo_name,
        'commit_message': metadata['commit_message'],
        'commit_timestamp': metadata['commit_timestamp'],
        'author_name': metadata.get('author_name'),
        'author_email': metadata.get('author_email'),
        'pr_number': None
    }


def _upload_commit(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    report, commit, args, current_branch, repo_name,
    build_failed=False, identical=False, api_url=None, base_sha_override=None
):
    """
    Upload a report for a single commit with proper git metadata.

    In dry-run mode, logs what would be uploaded instead of uploading.

    Args:
        report: Report dict to upload
        commit: Commit hash
        args: CLI args (target_name, api_key, api_url)
        current_branch: Branch name
        repo_name: Repository name
        build_failed: Whether the build failed
        identical: Whether to mark as identical
        api_url: Resolved API URL (overrides args.api_url if provided)
        base_sha_override: If provided, use this as the parent commit hash

    Returns:
        True if upload succeeded (or dry-run), False otherwise
    """
    commit_info = _build_commit_info(commit, current_branch, repo_name,
                                     base_sha_override=base_sha_override)
    log_prefix = f"({commit})"
    resolved_api_url = api_url if api_url is not None else args.api_url

    if getattr(args, 'dry_run', False):
        status = ("identical" if identical
                  else "build_failed" if build_failed
                  else "ok")
        layout = report.get('memory_layout', {})
        regions = ", ".join(
            f"{name}: {data.get('used_size', 0)}"
            for name, data in sorted(layout.items())
        ) if layout else "(empty)"
        logger.info("%s: [DRY-RUN] Would upload: status=%s, regions={%s}",
                    log_prefix, status, regions)
        return True

    try:
        upload_report(
            report=report,
            commit_info=commit_info,
            target_name=args.target_name,
            api_key=args.api_key,
            api_url=resolved_api_url,
            build_failed=build_failed,
            identical=identical
        )
        return True
    except (ValueError, RuntimeError) as e:
        logger.error("%s: Failed to upload report: %s", log_prefix, e)
        return False


def _mark_identical_range(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    commits, left_idx, right_idx, left_fingerprint,
    built_indices, commit_results, elf_path
):
    """Mark all commits between left and right as identical or build failures."""
    count = right_idx - left_idx - 1
    both_failed = left_fingerprint is None

    if both_failed:
        logger.info(
            "Commits %d..%d both failed to build, "
            "marking %d intermediate commits as build failures",
            left_idx, right_idx, count)
    else:
        logger.info(
            "Commits %d..%d have identical memory fingerprints, "
            "marking %d intermediate commits as identical",
            left_idx, right_idx, count)

    for i in range(left_idx + 1, right_idx):
        if i in built_indices:
            continue
        commit = commits[i]
        if both_failed:
            report = _create_empty_report(elf_path)
            commit_results[i] = (report, True, False)
            logger.info("(%s): Marked as build failure (%d/%d)",
                        commit[:8], i + 1, len(commits))
        else:
            report = _create_metadata_only_report(elf_path)
            commit_results[i] = (report, False, True)
            logger.info("(%s): Marked as identical (%d/%d)",
                        commit[:8], i + 1, len(commits))


def _binary_search_range(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals,too-many-return-statements
    commits, left_idx, right_idx,
    left_fingerprint, right_fingerprint,
    built_indices, failed_indices, reports_cache, commit_results,
    args, linker_variables, flush_fn
):
    """
    Recursively classify a range of commits using binary search.

    Builds midpoints only where fingerprints differ, and marks identical
    ranges. Build failures are treated as a distinct fingerprint state
    (None), allowing binary search to find where builds start/stop
    failing. Does NOT upload — results are stored in commit_results for
    chronological upload via flush_fn.

    Args:
        commits: Full list of commit hashes (oldest first)
        left_idx: Index of the left boundary (already built)
        right_idx: Index of the right boundary (already built)
        left_fingerprint: Fingerprint of the left boundary report,
                          or None if the build failed
        right_fingerprint: Fingerprint of the right boundary report,
                           or None if the build failed
        built_indices: Set of indices that have been built
        failed_indices: Set of indices where builds failed
        reports_cache: Dict mapping index -> report (for built commits)
        commit_results: Dict mapping index -> (report, build_failed, identical)
                        populated by this function for later upload
        args: CLI args
        linker_variables: Parsed linker definitions
        flush_fn: Callable that uploads consecutive ready commits in order

    Returns:
        True if processing should continue, False to abort
    """
    # Base case: no commits between left and right
    if right_idx - left_idx <= 1:
        return True

    # Fingerprints match - all commits in between share the same state
    if left_fingerprint == right_fingerprint:
        _mark_identical_range(
            commits, left_idx, right_idx, left_fingerprint,
            built_indices, commit_results, args.elf_path)
        flush_fn()
        return True

    # Fingerprints differ - binary search for the change point
    mid_idx = (left_idx + right_idx) // 2

    if mid_idx in built_indices:
        # Already built (shouldn't normally happen), use cached report
        mid_report = reports_cache[mid_idx]
        mid_fingerprint = None if mid_idx in failed_indices else _extract_fingerprint(mid_report)
    else:
        # Build the midpoint
        commit = commits[mid_idx]
        logger.info("Building midpoint commit %d/%d: %s",
                     mid_idx + 1, len(commits), commit[:8])
        try:
            mid_report, build_failed = _build_and_generate_report(
                commit, args, linker_variables)
        except RuntimeError as e:
            logger.error("Checkout failed at midpoint %s: %s", commit[:8], e)
            mid_report = _create_empty_report(args.elf_path)
            build_failed = True
        except ValueError as e:
            logger.error("Report generation failed at midpoint %s: %s",
                         commit[:8], e)
            return False

        commit_results[mid_idx] = (mid_report, build_failed, False)
        built_indices.add(mid_idx)
        reports_cache[mid_idx] = mid_report
        flush_fn()

        if build_failed:
            failed_indices.add(mid_idx)
            mid_fingerprint = None
        else:
            mid_fingerprint = _extract_fingerprint(mid_report)

    # Recurse on both halves
    if not _binary_search_range(
            commits, left_idx, mid_idx,
            left_fingerprint, mid_fingerprint,
            built_indices, failed_indices, reports_cache, commit_results,
            args, linker_variables, flush_fn):
        return False

    return _binary_search_range(
        commits, mid_idx, right_idx,
        mid_fingerprint, right_fingerprint,
        built_indices, failed_indices, reports_cache, commit_results,
        args, linker_variables, flush_fn)


def _run_binary_search_onboard(  # pylint: disable=too-many-locals,too-many-statements
    args, commits, current_branch, repo_name, linker_variables
):
    """
    Run onboard using binary search to minimize builds.

    Uploads are performed in chronological order via a flush mechanism.
    Built commits whose fingerprint matches the previous upload are
    automatically marked as identical.

    Args:
        args: CLI args
        commits: List of commit hashes (oldest first)
        current_branch: Branch name
        repo_name: Repository name
        linker_variables: Parsed linker definitions

    Returns:
        Tuple of (successful_uploads, failed_uploads)
    """
    counters = {'successful': 0, 'failed': 0}
    built_indices = set()
    failed_indices = set()
    reports_cache = {}
    commit_results = {}  # index -> (report, build_failed, identical)
    total = len(commits)

    # Flush state: upload consecutive ready commits in chronological order
    flush_state = {'next_to_upload': 0, 'prev_fingerprint': None, 'prev_build_failed': False}

    def flush_fn():
        """Upload consecutive ready commits starting from next_to_upload."""
        while flush_state['next_to_upload'] in commit_results:
            idx = flush_state['next_to_upload']
            report, build_failed, identical = commit_results.pop(idx)

            # If not already marked identical, compare fingerprint to previous
            if not identical and not build_failed and flush_state['prev_fingerprint'] is not None:
                fp = _extract_fingerprint(report)
                if fp == flush_state['prev_fingerprint']:
                    identical = True

            # Cannot upload identical when parent is build_failed —
            # convert to build_failed with empty report instead
            if identical and flush_state['prev_build_failed']:
                identical = False
                build_failed = True
                report = _create_empty_report(args.elf_path)

            if _upload_commit(report, commits[idx], args, current_branch,
                              repo_name, build_failed=build_failed,
                              identical=identical):
                counters['successful'] += 1
            else:
                counters['failed'] += 1

            # Update fingerprint for next comparison.
            # Reset after failed builds to prevent stale dedup.
            # For identical commits with metadata-only reports, keep the
            # previous fingerprint since their empty layout is not meaningful.
            if build_failed:
                flush_state['prev_fingerprint'] = None
            else:
                fp = _extract_fingerprint(report)
                if fp:
                    flush_state['prev_fingerprint'] = fp

            flush_state['prev_build_failed'] = build_failed

            flush_state['next_to_upload'] += 1

    logger.info("Binary search mode: %d commits to analyze", total)

    # Edge case: single commit
    if total == 1:
        commit = commits[0]
        logger.info("Single commit to process: %s", commit[:8])
        try:
            report, build_failed = _build_and_generate_report(
                commit, args, linker_variables)
        except (RuntimeError, ValueError) as e:
            logger.error("Failed to process commit %s: %s", commit[:8], e)
            counters['failed'] += 1
            return counters['successful'], counters['failed']

        commit_results[0] = (report, build_failed, False)
        flush_fn()
        return counters['successful'], counters['failed']

    # Build oldest endpoint
    logger.info("Building endpoint 1/%d: %s (oldest)", total, commits[0][:8])
    try:
        first_report, first_failed = _build_and_generate_report(
            commits[0], args, linker_variables)
    except (RuntimeError, ValueError) as e:
        logger.error("Failed to build oldest commit %s: %s",
                     commits[0][:8], e)
        counters['failed'] += 1
        return counters['successful'], counters['failed']

    commit_results[0] = (first_report, first_failed, False)
    built_indices.add(0)
    if first_failed:
        failed_indices.add(0)
    reports_cache[0] = first_report
    flush_fn()

    # Build newest endpoint
    logger.info("Building endpoint %d/%d: %s (newest)",
                total, total, commits[-1][:8])
    try:
        last_report, last_failed = _build_and_generate_report(
            commits[-1], args, linker_variables)
    except (RuntimeError, ValueError) as e:
        logger.error("Failed to build newest commit %s: %s",
                     commits[-1][:8], e)
        counters['failed'] += 1
        return counters['successful'], counters['failed']

    commit_results[total - 1] = (last_report, last_failed, False)
    built_indices.add(total - 1)
    if last_failed:
        failed_indices.add(total - 1)
    reports_cache[total - 1] = last_report

    # Edge case: only two commits
    if total == 2:
        flush_fn()
        return counters['successful'], counters['failed']

    # Extract fingerprints (None for failed builds)
    first_fp = None if first_failed else _extract_fingerprint(first_report)
    last_fp = None if last_failed else _extract_fingerprint(last_report)

    if first_fp == last_fp:
        if first_fp is None:
            logger.info(
                "Both endpoints failed - searching for working builds "
                "among %d intermediate commits", total - 2)
        else:
            logger.info(
                "Endpoints have identical fingerprints - marking all %d "
                "intermediate commits as identical", total - 2)
    else:
        logger.info("Endpoints differ - searching for changes via binary search")

    if not _binary_search_range(
            commits, 0, total - 1,
            first_fp, last_fp,
            built_indices, failed_indices, reports_cache, commit_results,
            args, linker_variables, flush_fn):
        logger.error("Binary search aborted due to upload failure")

    # Final flush to ensure HEAD (newest) is uploaded last
    flush_fn()

    return counters['successful'], counters['failed']


def run_onboard(args: argparse.Namespace) -> int:  # pylint: disable=too-many-locals,too-many-statements,too-many-branches,too-many-return-statements
    """
    Execute the onboard subcommand.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """

    commits_arg = getattr(args, 'commits', None)
    initial_commit = getattr(args, 'initial_commit', None)
    use_explicit_commits = commits_arg is not None

    # Resolve api_url: --api-url flag takes precedence over positional
    api_url_flag = getattr(args, 'api_url_flag', None)
    api_url = api_url_flag if api_url_flag is not None else args.api_url

    # Validate mutually exclusive options
    if getattr(args, 'binary_search', False) and getattr(args, 'build_dirs', None):
        logger.error("--binary-search and --build-dirs are mutually exclusive")
        return 1
    if use_explicit_commits and getattr(args, 'binary_search', False):
        logger.error("--binary-search and --commits are mutually exclusive")
        return 1
    if use_explicit_commits and getattr(args, 'build_dirs', None):
        logger.error("--build-dirs and --commits are mutually exclusive")
        return 1
    if use_explicit_commits and args.num_commits is not None:
        logger.error("Cannot use both num_commits and --commits")
        return 1
    if use_explicit_commits and initial_commit:
        logger.error("Cannot use both --commits and --initial-commit")
        return 1
    if not use_explicit_commits and args.num_commits is None:
        logger.error("Either num_commits or --commits is required")
        return 1

    if getattr(args, 'dry_run', False):
        logger.info("DRY-RUN MODE: will build and analyze but skip uploading")


    logger.info("Starting historical memory analysis for %s", args.target_name)
    if use_explicit_commits:
        logger.info("Processing explicit commit list")
    else:
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
    if use_explicit_commits:
        try:
            commits = _resolve_and_validate_commits(commits_arg)
        except ValueError as e:
            logger.error("Invalid --commits: %s", e)
            return 1
        logger.info("Resolved %d commit(s) to process", len(commits))
    else:
        commits = _get_commit_list(args.num_commits, initial_commit)
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

    # Binary search mode: delegate to binary search orchestrator
    if getattr(args, 'binary_search', False):
        successful_uploads, failed_uploads = _run_binary_search_onboard(
            args, commits, current_branch, repo_name, linker_variables
        )
        return finalize_and_return(0 if failed_uploads == 0 else 1)

    # Process each commit
    for commit_count, commit in enumerate(commits, 1):
        log_prefix = f"({commit})"

        logger.info("")
        logger.info("Processing commit %d/%d: %s",
                       commit_count, total_commits, commit[:8])

        # Check if we need to build this commit (when --build-dirs is specified)
        # First commit is always built to establish baseline
        # Skip this optimization when using --commits (explicit commit list)
        build_dirs = getattr(args, 'build_dirs', None)
        if (build_dirs and not use_explicit_commits
                and commit_count > 1
                and not _commit_has_changes_in_dirs(commit, build_dirs)):
            # No changes in build directories - upload metadata-only with identical=True
            logger.info("%s: No changes in build directories, marking as identical", log_prefix)

            report = _create_metadata_only_report(args.elf_path)
            if _upload_commit(report, commit, args, current_branch, repo_name,
                              identical=True, api_url=api_url):
                logger.info("%s: Identical report uploaded (commit %d of %d)",
                            log_prefix, commit_count, total_commits)
                successful_uploads += 1
            else:
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
            logger.error("%s: Failed to checkout commit — stopping onboard", log_prefix)
            failed_uploads += 1
            return finalize_and_return(1)

        # Update submodules to match the checked-out commit
        logger.info("%s: Updating submodules...", log_prefix)
        subprocess.run(
            ['git', 'submodule', 'update', '--init', '--recursive', '--quiet'],
            capture_output=True, check=False
        )

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

            # Case 3b: Build succeeded but report has empty memory_layout
            # (e.g. linker script parsing failed for this commit).
            # Treat as a build failure so the API accepts it instead of
            # rejecting with 400 "memory_layout is required and cannot be empty".
            if not report.get('memory_layout'):
                logger.error(
                    "%s: Build succeeded but memory_layout is empty "
                    "(linker script parsing may have failed) - "
                    "treating as failed build",
                    log_prefix)
                report = _create_empty_report(args.elf_path)
                build_failed = True

        # Build commit_info in metadata['git'] format (map old keys to new)
        # When using --commits, fake the parent chain so commits appear connected
        if use_explicit_commits:
            faked_parent = commits[commit_count - 2] if commit_count > 1 else None
        else:
            faked_parent = None

        if _upload_commit(report, commit, args, current_branch, repo_name,
                          build_failed=build_failed, api_url=api_url,
                          base_sha_override=faked_parent):
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
        else:
            logger.error(
                "%s: Failed to upload memory report (commit %d of %d), stopping workflow...",
                log_prefix, commit_count, total_commits)
            failed_uploads += 1
            return finalize_and_return(1)

    # Finalize with summary and restoration
    return finalize_and_return(0 if failed_uploads == 0 else 1)
