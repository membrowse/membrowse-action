"""Metrics subcommand — attach benchmark metrics to a commit of a target.

Metrics are named numbers (cycle counts, timings, scores) measured at a
commit. They are separate from the memory report: a benchmark job can post
them before or after the build job uploads its report, and several jobs can
each post their own subset for the same commit.
"""

import argparse
import json
import logging
import math
import re
import sys
from typing import Any, Dict, List, Optional

import requests

from ..api.client import MemBrowseClient
from ..auth.strategy import AuthContext, AuthType
from ..utils.git import detect_github_commit_sha, run_git_command

logger = logging.getLogger(__name__)

DEFAULT_API_URL = 'https://api.membrowse.com'

# Limits the API enforces; checked here so a mistake is reported with the
# offending metric's name instead of as a rejected upload.
MAX_METRICS = 200
MAX_NAME_LENGTH = 100
MAX_UNIT_LENGTH = 32

# A number, then optionally a unit: "412", "3.2 ms", "1.5e3cycles", "-4 dB".
# A unit cannot start with a digit, '.' or ',', so "1,5" and "1.5.2" are
# rejected rather than read as 1 with a unit of ",5".
_VALUE_RE = re.compile(
    r'^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*([^\d\s.,].*?)?\s*$')
_FULL_SHA_RE = re.compile(r'^(?:[0-9a-f]{40}|[0-9a-f]{64})$')


class MetricsError(ValueError):
    """A metric, file or commit the command cannot use; the message says why."""


def add_metrics_parser(subparsers) -> argparse.ArgumentParser:
    """Add 'metrics' subcommand parser."""
    parser = subparsers.add_parser(
        'metrics',
        help='Attach benchmark metrics to a commit',
        description=(
            'Attach benchmark metrics (cycle counts, timings, scores) to a commit\n'
            'of a target on the MemBrowse platform. They are plotted on the target\n'
            'dashboard and compared between builds.\n\n'
            'The target must already have a memory report; the metrics themselves\n'
            'can arrive before or after the report for their commit. Uploading the\n'
            'same metric again replaces its value, so retries are safe and separate\n'
            'CI jobs can each post their own metrics for one commit.'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  # One or more metrics for the current commit (git HEAD)
  membrowse metrics "Boot time=412 ms" "CoreMark=389.5" \\
      --target-name stm32f4 --api-key "$MEMBROWSE_API_KEY"

  # From a JSON file written by a benchmark harness
  membrowse metrics --file bench.json \\
      --target-name stm32f4 --api-key "$MEMBROWSE_API_KEY"

  # In GitHub Actions (uses the pull request's head commit, not the merge commit)
  membrowse metrics --file bench.json --github \\
      --target-name stm32f4 --api-key "$MEMBROWSE_API_KEY"

  # For a specific commit
  membrowse metrics "Latency=3.2 us" --commit-sha "$SHA" \\
      --target-name stm32f4 --api-key "$MEMBROWSE_API_KEY"

  # Remove one metric, or all of them, from a commit
  membrowse metrics --delete "Boot time" \\
      --target-name stm32f4 --api-key "$MEMBROWSE_API_KEY"
  membrowse metrics --delete --all \\
      --target-name stm32f4 --api-key "$MEMBROWSE_API_KEY"

metric format:
  NAME=VALUE or NAME=VALUE UNIT, e.g. "Message Passing=412 cycles".
  The unit belongs to the metric as a whole: set it once and later uploads
  without a unit keep it.

file format (--file, '-' reads standard input):
  {
    "Message Passing": {"value": 412, "unit": "cycles"},
    "Synchronization": 389.5
  }
  Metrics given on the command line override the same names from the file.
        """,
    )

    parser.add_argument(
        'metrics',
        nargs='*',
        metavar='NAME=VALUE',
        help='Metric as NAME=VALUE or "NAME=VALUE UNIT" '
             '(with --delete: the metric NAMEs to remove)',
    )
    parser.add_argument(
        '--file',
        metavar='PATH',
        help="JSON file of metrics ({name: number | {value, unit}}); '-' for stdin",
    )
    parser.add_argument(
        '--target-name',
        required=True,
        help='Target the metrics belong to (must already exist on the platform)',
    )
    parser.add_argument(
        '--api-key',
        required=True,
        help='MemBrowse project API key',
    )
    parser.add_argument(
        '--api-url',
        default=DEFAULT_API_URL,
        help=f'MemBrowse API base URL (default: {DEFAULT_API_URL})',
    )

    commit_group = parser.add_mutually_exclusive_group()
    commit_group.add_argument(
        '--commit-sha',
        help='Full commit SHA the metrics were measured at (default: git HEAD)',
    )
    commit_group.add_argument(
        '--github',
        action='store_true',
        help='Take the commit from the GitHub Actions event '
             '(the pull request head, not the merge commit)',
    )

    parser.add_argument(
        '--delete',
        action='store_true',
        help='Remove the named metrics from the commit instead of uploading',
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='With --delete: remove every metric of the commit',
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output the raw JSON response from the API',
    )

    return parser


def _check_name(name: str) -> str:
    name = name.strip() if isinstance(name, str) else ''
    if not name:
        raise MetricsError("A metric needs a name")
    if len(name) > MAX_NAME_LENGTH:
        raise MetricsError(
            f"Metric name is longer than {MAX_NAME_LENGTH} characters: {name!r}")
    return name


def _check_value(name: str, value: Any) -> Any:
    # bool is an int in Python; the API rejects it and so do we
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MetricsError(f"Metric {name!r}: value must be a number, got {value!r}")
    if not math.isfinite(value):
        raise MetricsError(f"Metric {name!r}: value must be finite, got {value!r}")
    return value


def _check_unit(name: str, unit: Any) -> Optional[str]:
    if unit is None:
        return None
    if not isinstance(unit, str):
        raise MetricsError(f"Metric {name!r}: unit must be text, got {unit!r}")
    unit = unit.strip()
    if len(unit) > MAX_UNIT_LENGTH:
        raise MetricsError(
            f"Metric {name!r}: unit is longer than {MAX_UNIT_LENGTH} characters")
    return unit


def parse_metric_argument(argument: str) -> Dict[str, Any]:
    """Parse one NAME=VALUE or "NAME=VALUE UNIT" argument.

    Returns {name: number}, or {name: {"value": number, "unit": str}} when a
    unit follows the value. The name is everything before the last '=', so it
    may itself contain one.

    Raises:
        MetricsError: If the argument is not in that form
    """
    name, separator, rest = argument.rpartition('=')
    if not separator:
        raise MetricsError(
            f"Expected NAME=VALUE, got {argument!r} "
            '(e.g. "Boot time=412 ms")')
    name = _check_name(name)
    match = _VALUE_RE.match(rest)
    if not match:
        raise MetricsError(
            f"Metric {name!r}: {rest.strip()!r} is not a number "
            '(expected e.g. "412" or "3.2 ms")')
    number, unit = match.groups()
    value = _check_value(
        name, int(number) if re.fullmatch(r'[+-]?\d+', number) else float(number))
    if unit:
        return {name: {'value': value, 'unit': _check_unit(name, unit)}}
    return {name: value}


def load_metrics_file(path: str) -> Dict[str, Any]:
    """Read and validate a metrics JSON file ('-' reads standard input).

    Returns the metrics in the shape the API takes.

    Raises:
        MetricsError: If the file cannot be read or is not a metrics object
    """
    source = 'standard input' if path == '-' else path
    try:
        if path == '-':
            data = json.load(sys.stdin)
        else:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
    except OSError as e:
        raise MetricsError(f"Cannot read {source}: {e}") from e
    except json.JSONDecodeError as e:
        raise MetricsError(f"{source} is not valid JSON: {e}") from e

    if not isinstance(data, dict):
        raise MetricsError(
            f"{source} must hold a JSON object of metric names to values")

    metrics: Dict[str, Any] = {}
    for raw_name, raw in data.items():
        name = _check_name(raw_name)
        if isinstance(raw, dict):
            unknown = set(raw) - {'value', 'unit'}
            if unknown or 'value' not in raw:
                raise MetricsError(
                    f"Metric {name!r}: expected a number or "
                    '{"value": <number>, "unit": <text>}')
            entry: Dict[str, Any] = {'value': _check_value(name, raw['value'])}
            if 'unit' in raw:
                # null and "" both clear the metric's unit; pass them through
                entry['unit'] = _check_unit(name, raw['unit'])
            metrics[name] = entry
        else:
            metrics[name] = _check_value(name, raw)
    return metrics


def collect_metrics(arguments: List[str], file_path: Optional[str]) -> Dict[str, Any]:
    """Metrics from the file, overridden by the command-line arguments."""
    metrics: Dict[str, Any] = load_metrics_file(file_path) if file_path else {}
    for argument in arguments:
        metrics.update(parse_metric_argument(argument))
    if not metrics:
        raise MetricsError(
            'No metrics given. Pass NAME=VALUE arguments or --file PATH.')
    if len(metrics) > MAX_METRICS:
        raise MetricsError(
            f"{len(metrics)} metrics given; one upload takes at most {MAX_METRICS}")
    return metrics


def resolve_commit_sha(commit_sha: Optional[str], github: bool) -> str:
    """The full commit SHA the metrics belong to.

    An explicit SHA wins; otherwise the GitHub event's commit with --github,
    or git HEAD.

    Raises:
        MetricsError: If no commit can be determined or it is not a full SHA
    """
    if commit_sha:
        sha, source = commit_sha, '--commit-sha'
    elif github:
        sha, source = detect_github_commit_sha(), 'the GitHub Actions environment'
        if not sha:
            raise MetricsError(
                '--github was given but GITHUB_SHA is not set. '
                'Pass --commit-sha when running outside GitHub Actions.')
    else:
        sha, source = run_git_command(['rev-parse', 'HEAD']) or '', 'git HEAD'
        if not sha:
            raise MetricsError(
                'Could not read the current commit from git. '
                'Run inside the repository or pass --commit-sha.')
    sha = sha.strip().lower()
    if not _FULL_SHA_RE.match(sha):
        raise MetricsError(
            f"Commit from {source} is not a full 40- or 64-character SHA: {sha!r}")
    return sha


def _api_data(response: Dict[str, Any]) -> Dict[str, Any]:
    if not response.get('success'):
        raise RuntimeError(
            f"API request failed: {response.get('error', 'Unknown error')}")
    return response.get('data') or {}


def run_metrics(args) -> int:
    """
    Run metrics subcommand.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        if args.all and not args.delete:
            raise MetricsError('--all is only valid with --delete')

        if args.delete:
            if args.file:
                raise MetricsError('--file cannot be used with --delete')
            if args.all and args.metrics:
                raise MetricsError('Give metric names or --all, not both')
            if not args.all and not args.metrics:
                raise MetricsError(
                    'Name the metrics to remove, or pass --all to remove '
                    'every metric of the commit')
            names = None if args.all else [_check_name(n) for n in args.metrics]
        else:
            metrics = collect_metrics(args.metrics, args.file)

        commit_sha = resolve_commit_sha(args.commit_sha, args.github)
        client = MemBrowseClient(
            AuthContext(auth_type=AuthType.API_KEY, api_key=args.api_key),
            args.api_url)

        if args.delete:
            response = client.delete_metrics(args.target_name, commit_sha, names)
            removed = _api_data(response).get('removed', 0)
            message = (f"Removed {removed} metric(s) from {args.target_name} "
                       f"at {commit_sha[:10]}")
        else:
            response = client.upload_metrics(args.target_name, commit_sha, metrics)
            stored = _api_data(response).get('metrics_stored') or sorted(metrics)
            message = (f"Uploaded {len(stored)} metric(s) for {args.target_name} "
                       f"at {commit_sha[:10]}: {', '.join(stored)}")

        print(json.dumps(response, indent=2) if args.json else message)
        return 0

    except MetricsError as e:
        logger.error("%s", e)
        return 1
    except (requests.exceptions.RequestException, RuntimeError, ValueError) as e:
        logger.error("Metrics command failed: %s", e)
        return 1
