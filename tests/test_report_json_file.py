#!/usr/bin/env python3
"""Tests for ``membrowse report --json-file``: the JSON report is written to
a file while stdout keeps whatever it would have shown without the flag."""

import argparse
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from membrowse.commands.report import add_report_parser, run_report

REPORT = {'memory_regions': {}, 'symbols': [{'name': 'main', 'size': 4}]}


class TestJsonFile(unittest.TestCase):
    """--json-file writes the JSON report and leaves stdout as it was."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.elf = os.path.join(self.tmp, 'fw.elf')
        Path(self.elf).touch()
        self.out = os.path.join(self.tmp, 'report.json')

    def _run(self, *argv):
        parser = argparse.ArgumentParser()
        add_report_parser(parser.add_subparsers())
        args = parser.parse_args(['report', self.elf, *argv])
        stdout = io.StringIO()
        with patch('membrowse.commands.report.generate_report',
                   return_value=REPORT), \
                patch('membrowse.commands.report.format_report_human_readable',
                      return_value='HUMAN'), \
                contextlib.redirect_stdout(stdout):
            code = run_report(args)
        return code, stdout.getvalue()

    def _written(self):
        with open(self.out, encoding='utf-8') as f:
            return json.load(f)

    def test_human_readable_stdout_and_json_file(self):
        """Stdout keeps the human-readable report."""
        code, stdout = self._run('--json-file', self.out)
        self.assertEqual(code, 0)
        self.assertEqual(stdout, 'HUMAN\n')
        self.assertEqual(self._written(), REPORT)

    def test_json_stdout_and_json_file(self):
        """--json still prints JSON; the file gets the same report."""
        code, stdout = self._run('--json', '--json-file', self.out)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout), REPORT)
        self.assertEqual(self._written(), REPORT)

    def test_written_in_upload_mode(self):
        """Upload mode writes the file too."""
        with patch('membrowse.commands.report._handle_upload_and_alerts',
                   return_value=0) as upload:
            code, stdout = self._run(
                '--json-file', self.out, '--upload', '--no-git',
                '--api-key', 'k', '--target-name', 't')
        self.assertEqual(code, 0)
        self.assertEqual(stdout, '')
        upload.assert_called_once()
        self.assertEqual(self._written(), REPORT)

    def test_unwritable_path_fails(self):
        """A path that cannot be written is an error."""
        self.out = os.path.join(self.tmp, 'missing', 'report.json')
        code, _ = self._run('--json-file', self.out)
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
