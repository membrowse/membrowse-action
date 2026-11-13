#!/usr/bin/env python3

"""
test_metrics_command.py - Tests for the `membrowse metrics` subcommand

Covers metric argument and file parsing, commit resolution, and the requests
the command sends to the /metrics endpoint.
"""

# pylint: disable=consider-using-with

import io
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import requests

from membrowse.cli import create_parser
from membrowse.commands.metrics import (
    MetricsError, collect_metrics, load_metrics_file, parse_metric_argument,
    parse_metric_option, resolve_commit_sha, run_metrics,
)

SHA = 'a' * 40
BASE = ['--target-name', 'stm32f4', '--api-key', 'key']


def _response(payload, status=200):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload
    if status >= 400:
        error = requests.exceptions.HTTPError(f"{status} Client Error")
        error.response = response
        response.raise_for_status.side_effect = error
    else:
        response.raise_for_status.return_value = None
    return response


class TestParseMetricArgument(unittest.TestCase):
    """NAME=VALUE and "NAME=VALUE UNIT" arguments."""

    def test_bare_numbers(self):
        """Bare numbers."""
        self.assertEqual(parse_metric_argument('CoreMark=389.5'), {'CoreMark': 389.5})
        self.assertEqual(parse_metric_argument('Cycles=412'), {'Cycles': 412})
        self.assertIsInstance(parse_metric_argument('Cycles=412')['Cycles'], int)
        self.assertEqual(parse_metric_argument('Gain=-4'), {'Gain': -4})
        self.assertEqual(parse_metric_argument('Rate=1.5e3'), {'Rate': 1500.0})
        self.assertEqual(parse_metric_argument('Half=.5'), {'Half': 0.5})

    def test_units(self):
        """Units."""
        self.assertEqual(parse_metric_argument('Boot time=412 ms'),
                         {'Boot time': {'value': 412, 'unit': 'ms'}})
        self.assertEqual(parse_metric_argument('Latency=3.2us'),
                         {'Latency': {'value': 3.2, 'unit': 'us'}})
        self.assertEqual(parse_metric_argument('  Speed = 12  m / s  '),
                         {'Speed': {'value': 12, 'unit': 'm / s'}})

    def test_name_may_contain_equals(self):
        """Name may contain equals."""
        self.assertEqual(parse_metric_argument('a=b=3'), {'a=b': 3})

    def test_rejects_malformed(self):
        """Rejects malformed."""
        for bad in ('NoValue', '=5', 'Name=', 'Name=fast', 'Name=nan',
                    'Name=inf', 'Name=1,5', 'Name=true',
                    'x' * 101 + '=1', 'Name=1 ' + 'u' * 33):
            with self.assertRaises(MetricsError, msg=bad):
                parse_metric_argument(bad)


class TestParseMetricOption(unittest.TestCase):
    """-m NAME VALUE [UNIT] options."""

    def test_name_value_and_optional_unit(self):
        """Name, number and unit arrive as separate arguments."""
        self.assertEqual(parse_metric_option(['CoreMark', '389.5']), {'CoreMark': 389.5})
        self.assertEqual(parse_metric_option(['Boot time', '412', 'ms']),
                         {'Boot time': {'value': 412, 'unit': 'ms'}})
        self.assertEqual(parse_metric_option(['Gain', '-4e0', ' dB ']),
                         {'Gain': {'value': -4.0, 'unit': 'dB'}})
        # An empty unit, e.g. an unset shell variable, is no unit
        self.assertEqual(parse_metric_option(['A', '1', '']), {'A': 1})

    def test_rejects_malformed(self):
        """Wrong arity, a non-numeric value, or a unit glued to the value."""
        for bad in (['A'], ['A', '1', 'ms', 'extra'], ['A', 'fast'],
                    ['A', ''], ['A', '412ms'], ['', '1'], ['A', 'nan']):
            with self.assertRaises(MetricsError, msg=bad):
                parse_metric_option(bad)


class TestMetricsFile(unittest.TestCase):
    """--file JSON input."""

    def _file(self, content):
        handle = tempfile.NamedTemporaryFile(
            'w', suffix='.json', delete=False, encoding='utf-8')
        handle.write(content if isinstance(content, str) else json.dumps(content))
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_array_of_name_value_unit(self):
        """Entries become the API's metrics object; a missing unit is left alone."""
        path = self._file([
            {'name': 'Message Passing', 'unit': 'cycles', 'value': 412},
            {'name': 'Synchronization', 'value': 389.5},
            {'name': ' Padded ', 'value': 1, 'unit': ' ms '},
            {'name': 'Cleared', 'value': 2, 'unit': None},
            # github-action-benchmark's extra fields are accepted and ignored
            {'name': 'Ranged', 'value': 3, 'unit': 'ns', 'range': '+/- 2',
             'extra': 'iterations: 100'},
        ])
        self.assertEqual(load_metrics_file(path), {
            'Message Passing': {'value': 412, 'unit': 'cycles'},
            'Synchronization': 389.5,
            'Padded': {'value': 1, 'unit': 'ms'},
            'Cleared': {'value': 2, 'unit': None},
            'Ranged': {'value': 3, 'unit': 'ns'},
        })

    def test_stdin(self):
        """Stdin."""
        with patch('sys.stdin', io.StringIO('[{"name": "A", "value": 1}]')):
            self.assertEqual(load_metrics_file('-'), {'A': 1})

    def test_rejects_bad_files(self):
        """Rejects bad files."""
        with self.assertRaises(MetricsError):
            load_metrics_file('/no/such/metrics.json')
        for content in ('{not json', {'A': 1}, [1, 2], [{'name': 'A'}],
                        [{'value': 1}], [{'name': 'A', 'value': 'fast'}],
                        [{'name': 'A', 'value': True}],
                        [{'name': 'A', 'value': 1, 'surprise': 2}],
                        [{'name': 'A', 'value': 1, 'unit': 5}],
                        [{'name': '', 'value': 1}],
                        [{'name': 'A', 'value': 1}, {'name': 'A', 'value': 2}],
                        [{'name': 'A', 'value': float('inf')}]):
            with self.assertRaises(MetricsError, msg=repr(content)):
                load_metrics_file(self._file(content))

    def test_arguments_override_file_and_count_is_capped(self):
        """Arguments override file and count is capped."""
        path = self._file([{'name': 'A', 'value': 1}, {'name': 'B', 'value': 2}])
        self.assertEqual(collect_metrics(['B=5 ms'], path),
                         {'A': 1, 'B': {'value': 5, 'unit': 'ms'}})
        self.assertEqual(
            collect_metrics(['B=5 ms'], path, [['B', '7'], ['C', '3', 'us']]),
            {'A': 1, 'B': 7, 'C': {'value': 3, 'unit': 'us'}})
        with self.assertRaises(MetricsError):
            collect_metrics([], None)
        with self.assertRaises(MetricsError):
            collect_metrics([f'm{i}=1' for i in range(201)], None)


class TestResolveCommit(unittest.TestCase):
    """Which commit the metrics are attached to."""

    def test_explicit_sha_is_normalised(self):
        """Explicit sha is normalised."""
        self.assertEqual(resolve_commit_sha(SHA.upper(), False), SHA)
        self.assertEqual(resolve_commit_sha('b' * 64, False), 'b' * 64)

    def test_short_or_symbolic_commits_are_rejected(self):
        """Short or symbolic commits are rejected."""
        for bad in ('abc1234', 'HEAD', 'main'):
            with self.assertRaises(MetricsError, msg=bad):
                resolve_commit_sha(bad, False)

    def test_default_is_git_head(self):
        """Default is git head."""
        with patch('membrowse.commands.metrics.run_git_command', return_value=SHA):
            self.assertEqual(resolve_commit_sha(None, False), SHA)
        with patch('membrowse.commands.metrics.run_git_command', return_value=None):
            with self.assertRaises(MetricsError):
                resolve_commit_sha(None, False)

    def test_github_uses_the_pull_request_head(self):
        """Github uses the pull request head."""
        head = 'c' * 40
        event = tempfile.NamedTemporaryFile(
            'w', suffix='.json', delete=False, encoding='utf-8')
        json.dump({'pull_request': {'number': 7, 'head': {'sha': head, 'ref': 'f'},
                                    'base': {'sha': 'd' * 40}}}, event)
        event.close()
        self.addCleanup(os.unlink, event.name)
        env = {'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_SHA': 'e' * 40,
               'GITHUB_EVENT_PATH': event.name}
        with patch.dict(os.environ, env):
            self.assertEqual(resolve_commit_sha(None, True), head)

        # A push reports GITHUB_SHA itself
        with patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'push',
                                     'GITHUB_SHA': 'e' * 40,
                                     'GITHUB_EVENT_PATH': ''}):
            self.assertEqual(resolve_commit_sha(None, True), 'e' * 40)

    def test_github_outside_actions_is_an_error(self):
        """Github outside actions is an error."""
        with patch.dict(os.environ, {'GITHUB_EVENT_NAME': '', 'GITHUB_SHA': '',
                                     'GITHUB_EVENT_PATH': ''}):
            with self.assertRaises(MetricsError):
                resolve_commit_sha(None, True)


class TestRunMetrics(unittest.TestCase):
    """The requests the command sends, end to end through the CLI parser."""

    def _run(self, argv, response=None):
        args = create_parser().parse_args(['metrics'] + argv)
        with patch('requests.Session.request',
                   return_value=response or _response(
                       {'success': True, 'data': {'metrics_stored': ['A']}})) as request, \
                patch('sys.stdout', new_callable=io.StringIO) as stdout:
            code = run_metrics(args)
        return code, request, stdout.getvalue()

    def test_upload_posts_metrics_for_the_commit(self):
        """Upload posts metrics for the commit."""
        code, request, output = self._run(
            ['Boot time=412 ms', 'CoreMark=389.5', '--commit-sha', SHA] + BASE
            + ['--api-url', 'https://example.test/'],
            _response({'success': True, 'data': {
                'target': 'stm32f4', 'commit': SHA,
                'metrics_stored': ['Boot time', 'CoreMark']}}))
        self.assertEqual(code, 0)
        (method, url), kwargs = request.call_args
        self.assertEqual((method, url), ('POST', 'https://example.test/metrics'))
        self.assertEqual(kwargs['json'], {
            'metadata': {'target_name': 'stm32f4', 'git': {'commit_hash': SHA}},
            'metrics': {'Boot time': {'value': 412, 'unit': 'ms'},
                        'CoreMark': 389.5},
        })
        self.assertIn('Uploaded 2 metric(s) for stm32f4', output)
        self.assertIn('Boot time, CoreMark', output)

    def test_metric_options_are_uploaded(self):
        """-m options and NAME=VALUE arguments end up in one upload."""
        code, request, _ = self._run(
            ['-m', 'Boot time', '412', 'ms', '--metric', 'CoreMark', '389.5',
             '--commit-sha', SHA] + BASE + ['Extra=1'])
        self.assertEqual(code, 0)
        self.assertEqual(request.call_args[1]['json']['metrics'], {
            'Boot time': {'value': 412, 'unit': 'ms'},
            'CoreMark': 389.5,
            'Extra': 1,
        })

    def test_json_prints_the_raw_response(self):
        """Json prints the raw response."""
        payload = {'success': True, 'data': {'metrics_stored': ['A']}}
        code, _, output = self._run(
            ['A=1', '--commit-sha', SHA, '--json'] + BASE, _response(payload))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output), payload)

    def test_delete_named_and_all(self):
        """Delete named and all."""
        code, request, output = self._run(
            ['--delete', 'Boot time', 'CoreMark', '--commit-sha', SHA] + BASE,
            _response({'success': True, 'data': {'removed': 2}}))
        self.assertEqual(code, 0)
        (method, url), kwargs = request.call_args
        self.assertEqual(method, 'DELETE')
        self.assertTrue(url.endswith('/metrics'))
        self.assertEqual(kwargs['json']['names'], ['Boot time', 'CoreMark'])
        self.assertIn('Removed 2 metric(s)', output)

        code, request, _ = self._run(
            ['--delete', '--all', '--commit-sha', SHA] + BASE,
            _response({'success': True, 'data': {'removed': 5}}))
        self.assertEqual(code, 0)
        self.assertNotIn('names', request.call_args[1]['json'])

    def test_usage_errors_send_nothing(self):
        """Usage errors send nothing."""
        for argv in (
                ['--commit-sha', SHA],                       # no metrics
                ['A=fast', '--commit-sha', SHA],              # not a number
                ['A=1', '--commit-sha', 'abc123'],            # short SHA
                ['--delete', '--commit-sha', SHA],            # nothing named
                ['--delete', '--all', 'A', '--commit-sha', SHA],
                ['A=1', '--all', '--commit-sha', SHA],        # --all without --delete
                ['-m', 'A', '--commit-sha', SHA],              # -m without a value
                ['--delete', 'A', '-m', 'B', '1', '--commit-sha', SHA],
                ['--delete', 'A', '--file', 'x.json', '--commit-sha', SHA]):
            code, request, _ = self._run(argv + BASE)
            self.assertEqual(code, 1, argv)
            request.assert_not_called()

    def test_api_error_is_reported_with_exit_code_1(self):
        """Api error is reported with exit code 1."""
        code, _, _ = self._run(
            ['A=1', '--commit-sha', SHA] + BASE,
            _response({'success': False, 'error': 'Target not found'}, status=404))
        self.assertEqual(code, 1)

    def test_negative_values_in_every_notation_reach_the_upload(self):
        """argparse must not mistake -4e0 or -1.5e-3 for an option."""
        for value, expected in (('-4', -4), ('-4.5', -4.5), ('-.5', -0.5),
                                ('-4e0', -4.0), ('-1.5e-3', -0.0015),
                                ('-4E2', -400.0)):
            code, request, _ = self._run(
                ['-m', 'Gain', value, 'dB', '-m', 'Offset', value,
                 '--commit-sha', SHA] + BASE)
            self.assertEqual(code, 0, value)
            self.assertEqual(request.call_args[1]['json']['metrics'], {
                'Gain': {'value': expected, 'unit': 'dB'},
                'Offset': expected,
            }, value)

    def test_dash_options_are_still_options(self):
        """Widening the number rule leaves real flags alone."""
        with self.assertRaises(SystemExit), patch('sys.stderr', new_callable=io.StringIO):
            create_parser().parse_args(['metrics', '-m', 'A', '1', '-x'] + BASE)

    def test_commit_flags_are_mutually_exclusive(self):
        """Commit flags are mutually exclusive."""
        with self.assertRaises(SystemExit), patch('sys.stderr', new_callable=io.StringIO):
            create_parser().parse_args(
                ['metrics', 'A=1', '--github', '--commit-sha', SHA] + BASE)


if __name__ == '__main__':
    unittest.main()
