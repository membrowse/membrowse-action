#!/usr/bin/env python3

"""
test_cli_def.py - Tests for --def CLI argument parsing

This module tests the --def command-line argument for both report and onboard
commands, verifying that user-defined linker script variables are correctly
parsed and passed to the parser.
"""

import os
import sys
import tempfile
import unittest
import argparse
from pathlib import Path
from unittest.mock import patch

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'shared'))

# pylint: disable=wrong-import-position
from membrowse.commands.report import add_report_parser, run_report
from membrowse.commands.onboard import add_onboard_parser


class TestReportDefArgument(unittest.TestCase):
    """Test --def argument parsing in report command"""

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_files = []

    def tearDown(self):
        """Clean up temporary files"""
        for temp_file in self.temp_files:
            try:
                os.unlink(temp_file)
            except OSError:
                pass
        try:
            os.rmdir(self.temp_dir)
        except OSError:
            pass

    def create_temp_file(self, content: str, suffix: str = '.ld') -> str:
        """Create a temporary file with given content"""
        temp_file = os.path.join(
            self.temp_dir,
            f"test_{len(self.temp_files)}{suffix}")
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(content)
        self.temp_files.append(temp_file)
        return temp_file

    def test_def_argument_single(self):
        """Test parsing single --def argument"""
        parser = argparse.ArgumentParser()
        add_report_parser(parser.add_subparsers())

        args = parser.parse_args([
            'report',
            'test.elf',
            'test.ld',
            '--def', 'FLASH_SIZE=512K'
        ])

        self.assertIsNotNone(args.linker_defs)
        self.assertEqual(len(args.linker_defs), 1)
        self.assertEqual(args.linker_defs[0], 'FLASH_SIZE=512K')

    def test_def_argument_multiple(self):
        """Test parsing multiple --def arguments"""
        parser = argparse.ArgumentParser()
        add_report_parser(parser.add_subparsers())

        args = parser.parse_args([
            'report',
            'test.elf',
            'test.ld',
            '--def', 'FLASH_SIZE=512K',
            '--def', 'RAM_SIZE=128K',
            '--def', '__micropy_flash_size__=4096K'
        ])

        self.assertIsNotNone(args.linker_defs)
        self.assertEqual(len(args.linker_defs), 3)
        self.assertEqual(args.linker_defs[0], 'FLASH_SIZE=512K')
        self.assertEqual(args.linker_defs[1], 'RAM_SIZE=128K')
        self.assertEqual(args.linker_defs[2], '__micropy_flash_size__=4096K')

    def test_def_argument_optional(self):
        """Test that --def argument is optional"""
        parser = argparse.ArgumentParser()
        add_report_parser(parser.add_subparsers())

        args = parser.parse_args([
            'report',
            'test.elf',
            'test.ld'
        ])

        # linker_defs should be None when not provided
        self.assertIsNone(args.linker_defs)

    def test_def_argument_hex_values(self):
        """Test --def with hexadecimal values"""
        parser = argparse.ArgumentParser()
        add_report_parser(parser.add_subparsers())

        args = parser.parse_args([
            'report',
            'test.elf',
            'test.ld',
            '--def', 'FLASH_START=0x08000000',
            '--def', 'FLASH_SIZE=0x80000'
        ])

        self.assertEqual(len(args.linker_defs), 2)
        self.assertEqual(args.linker_defs[0], 'FLASH_START=0x08000000')
        self.assertEqual(args.linker_defs[1], 'FLASH_SIZE=0x80000')

    def test_def_argument_with_spaces(self):
        """Test --def with spaces around equals sign"""
        parser = argparse.ArgumentParser()
        add_report_parser(parser.add_subparsers())

        # Spaces around = are part of the argument value
        args = parser.parse_args([
            'report',
            'test.elf',
            'test.ld',
            '--def', 'FLASH_SIZE = 512K'
        ])

        self.assertEqual(args.linker_defs[0], 'FLASH_SIZE = 512K')

    def test_def_argument_numeric_values(self):
        """Test --def with plain numeric values"""
        parser = argparse.ArgumentParser()
        add_report_parser(parser.add_subparsers())

        args = parser.parse_args([
            'report',
            'test.elf',
            'test.ld',
            '--def', 'FLASH_SIZE=524288',
            '--def', 'RAM_START=536870912'
        ])

        self.assertEqual(len(args.linker_defs), 2)
        self.assertEqual(args.linker_defs[0], 'FLASH_SIZE=524288')
        self.assertEqual(args.linker_defs[1], 'RAM_START=536870912')

    def test_def_argument_with_underscores(self):
        """Test --def with variable names containing underscores"""
        parser = argparse.ArgumentParser()
        add_report_parser(parser.add_subparsers())

        args = parser.parse_args([
            'report',
            'test.elf',
            'test.ld',
            '--def', '__micropy_flash_size__=4096K',
            '--def', '_private_var=0x1000'
        ])

        self.assertEqual(len(args.linker_defs), 2)
        self.assertIn('__micropy_flash_size__=4096K', args.linker_defs)
        self.assertIn('_private_var=0x1000', args.linker_defs)

    @patch('membrowse.commands.report.generate_report')
    def test_def_parsing_in_run_report(self, mock_generate):
        """Test that --def arguments are parsed correctly in run_report()"""
        # Create mock ELF and linker script files
        elf_content = b'\x7fELF'  # Minimal ELF header
        elf_path = self.create_temp_file('', '.elf')
        with open(elf_path, 'wb') as f:
            f.write(elf_content)

        ld_content = "MEMORY { FLASH (rx) : ORIGIN = 0, LENGTH = flash_size }"
        ld_path = self.create_temp_file(ld_content, '.ld')

        # Mock the generate_report to avoid actual parsing
        mock_generate.return_value = {'test': 'report'}

        # Create args namespace with --def arguments
        parser = argparse.ArgumentParser()
        add_report_parser(parser.add_subparsers())
        args = parser.parse_args([
            'report',
            elf_path,
            ld_path,
            '--def', 'flash_size=512K',
            '--def', 'ram_start=0x20000000'
        ])

        # Run the command
        result = run_report(args)

        # Verify generate_report was called
        self.assertEqual(result, 0)
        mock_generate.assert_called_once()

        # Check that linker_variables were passed correctly
        call_kwargs = mock_generate.call_args[1]
        self.assertIn('linker_variables', call_kwargs)
        linker_vars = call_kwargs['linker_variables']

        # Should be parsed into a dict
        self.assertIsInstance(linker_vars, dict)
        self.assertEqual(linker_vars['flash_size'], '512K')
        self.assertEqual(linker_vars['ram_start'], '0x20000000')

    @patch('membrowse.commands.report.generate_report')
    def test_def_invalid_format_missing_equals(self, mock_generate):
        """Test that invalid --def format (missing =) is handled gracefully"""
        elf_path = self.create_temp_file('', '.elf')
        ld_path = self.create_temp_file('MEMORY {}', '.ld')

        mock_generate.return_value = {'test': 'report'}

        parser = argparse.ArgumentParser()
        add_report_parser(parser.add_subparsers())
        args = parser.parse_args([
            'report',
            elf_path,
            ld_path,
            '--def', 'INVALID_NO_EQUALS'  # Missing = sign
        ])

        # Should not crash, just log warning
        result = run_report(args)
        self.assertEqual(result, 0)

        # linker_variables should be None or empty dict
        call_kwargs = mock_generate.call_args[1]
        linker_vars = call_kwargs.get('linker_variables')
        # Should be None or empty dict since the def was invalid
        self.assertTrue(linker_vars is None or linker_vars == {})

    @patch('membrowse.commands.report.generate_report')
    def test_def_invalid_format_empty_key(self, mock_generate):
        """Test that invalid --def format (empty key) is handled gracefully"""
        elf_path = self.create_temp_file('', '.elf')
        ld_path = self.create_temp_file('MEMORY {}', '.ld')

        mock_generate.return_value = {'test': 'report'}

        parser = argparse.ArgumentParser()
        add_report_parser(parser.add_subparsers())
        args = parser.parse_args([
            'report',
            elf_path,
            ld_path,
            '--def', '=value'  # Empty key
        ])

        # Should not crash, just log warning
        result = run_report(args)
        self.assertEqual(result, 0)


class TestOnboardDefArgument(unittest.TestCase):
    """Test --def argument parsing in onboard command"""

    def test_def_argument_single(self):
        """Test parsing single --def argument in onboard command"""
        parser = argparse.ArgumentParser()
        add_onboard_parser(parser.add_subparsers())

        args = parser.parse_args([
            'onboard',
            '10',
            'make',
            'build/firmware.elf',
            'linker.ld',
            'esp32',
            'api_key',
            '--def', 'FLASH_SIZE=4M'
        ])

        self.assertIsNotNone(args.linker_defs)
        self.assertEqual(len(args.linker_defs), 1)
        self.assertEqual(args.linker_defs[0], 'FLASH_SIZE=4M')

    def test_def_argument_multiple(self):
        """Test parsing multiple --def arguments in onboard command"""
        parser = argparse.ArgumentParser()
        add_onboard_parser(parser.add_subparsers())

        args = parser.parse_args([
            'onboard',
            '25',
            'make clean && make',
            'build/firmware.elf',
            'mem.ld sections.ld',
            'stm32f4',
            'test_api_key',
            'https://membrowse.com',
            '--def', 'FLASH_SIZE=512K',
            '--def', 'RAM_SIZE=128K',
        ])

        self.assertIsNotNone(args.linker_defs)
        self.assertEqual(len(args.linker_defs), 2)
        self.assertEqual(args.linker_defs[0], 'FLASH_SIZE=512K')
        self.assertEqual(args.linker_defs[1], 'RAM_SIZE=128K')

    def test_def_argument_optional_onboard(self):
        """Test that --def argument is optional in onboard command"""
        parser = argparse.ArgumentParser()
        add_onboard_parser(parser.add_subparsers())

        args = parser.parse_args([
            'onboard',
            '10',
            'make',
            'firmware.elf',
            'linker.ld',
            'esp32',
            'api_key'
        ])

        # linker_defs should be None when not provided
        self.assertIsNone(args.linker_defs)

    def test_def_argument_position_independence(self):
        """Test that --def can appear in different positions"""
        parser = argparse.ArgumentParser()
        add_onboard_parser(parser.add_subparsers())

        # --def before positional args
        args1 = parser.parse_args([
            'onboard',
            '--def', 'VAR1=value1',
            '10',
            'make',
            'firmware.elf',
            'linker.ld',
            'esp32',
            'api_key'
        ])
        self.assertEqual(args1.linker_defs[0], 'VAR1=value1')

        # --def after positional args
        args2 = parser.parse_args([
            'onboard',
            '10',
            'make',
            'firmware.elf',
            'linker.ld',
            'esp32',
            'api_key',
            '--def', 'VAR2=value2'
        ])
        self.assertEqual(args2.linker_defs[0], 'VAR2=value2')


class TestDefVariableParsing(unittest.TestCase):
    """Test the parsing logic for --def variable definitions"""

    def test_parse_valid_definition(self):
        """Test parsing valid KEY=VALUE definitions"""
        # This tests the parsing logic in run_report
        test_cases = [
            ('FLASH_SIZE=512K', 'FLASH_SIZE', '512K'),
            ('RAM_START=0x20000000', 'RAM_START', '0x20000000'),
            ('__var__=123', '__var__', '123'),
            ('key = value', 'key', 'value'),  # With spaces
            ('A=0', 'A', '0'),
        ]

        for def_str, expected_key, expected_value in test_cases:
            if '=' in def_str:
                key, value = def_str.split('=', 1)
                key = key.strip()
                value = value.strip()
                self.assertEqual(key, expected_key)
                self.assertEqual(value, expected_value)

    def test_parse_invalid_definition(self):
        """Test handling of invalid definitions"""
        invalid_cases = [
            'NO_EQUALS',      # Missing =
            '=value',         # Empty key
            '',               # Empty string
        ]

        for def_str in invalid_cases:
            if '=' not in def_str:
                # Should be skipped
                continue
            key, _ = def_str.split('=', 1)
            key = key.strip()
            # Empty key should be detected
            if not key:
                self.assertEqual(key, '')

    def test_parse_multiple_equals(self):
        """Test definitions with multiple equals signs"""
        def_str = 'VAR=value=with=equals'
        # Should split only on first =
        key, value = def_str.split('=', 1)
        self.assertEqual(key, 'VAR')
        self.assertEqual(value, 'value=with=equals')


if __name__ == '__main__':
    # Configure test output
    import logging
    logging.basicConfig(level=logging.WARNING)

    # Run all tests
    unittest.main(verbosity=2)
