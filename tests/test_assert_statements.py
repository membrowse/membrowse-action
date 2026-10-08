"""
Tests for ASSERT statements in GNU LD linker scripts.

Reproduces the bug where the variable-assignment regex in VariableExtractor
matches the first '=' of an '==' comparison inside an ASSERT. The garbage
capture is stored as a complex variable and overwrites the real
expression-defined value, so every MEMORY region depending on it fails to
resolve.
"""

import tempfile
import unittest
from pathlib import Path

from membrowse.linker.parser import (
    LinkerScriptParser, RegionParsingError, ScriptContentCleaner,
    VariableExtractor, ExpressionEvaluator)


MEM_WITH_ASSERT = '''
flash_end   = 0x100000;
flash_size  = 512K;
flash_start = flash_end - flash_size;
ASSERT (
    (flash_start == 0x80000) && (flash_size > 0),
    "Invalid flash memory map!"
);
'''

MEM_WITH_ASSERT_LITERAL = '''
flash_end   = 0x100000;
flash_size  = 512K;
flash_start = 0x80000;
ASSERT (
    (flash_start == 0x80000) && (flash_size > 0),
    "Invalid flash memory map!"
);
'''

LINKER = '''
MEMORY
{
    APP_FLASH (rx) : ORIGIN = flash_start, LENGTH = flash_size
}
'''


class TestAssertStatements(unittest.TestCase):
    """ASSERT comparisons must not be parsed as variable assignments"""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.test_files = []

    def tearDown(self):
        for file_path in self.test_files:
            if file_path.exists():
                file_path.unlink()
        if self.temp_dir.exists():
            self.temp_dir.rmdir()

    def create_test_file(self, content: str, filename: str) -> Path:
        """Create a temporary linker script with the given content"""
        file_path = self.temp_dir / filename
        file_path.write_text(content, encoding='utf-8')
        self.test_files.append(file_path)
        return file_path

    def _make_parser(self, mem_content: str, **kwargs) -> LinkerScriptParser:
        linker = self.create_test_file(LINKER, 'linker.ld')
        mem = self.create_test_file(mem_content, 'mem.ld')
        return LinkerScriptParser([str(linker), str(mem)], **kwargs)

    def test_assert_does_not_clobber_expression_variable(self):
        """flash_start = flash_end - flash_size must survive a later ASSERT"""
        parser = self._make_parser(MEM_WITH_ASSERT)
        parser._extract_all_variables()  # pylint: disable=protected-access

        self.assertEqual(
            parser.variable_extractor.variables['flash_start'], 0x80000,
            "ASSERT '==' comparison was captured as an assignment")

    def test_region_resolves_with_assert_present(self):
        """MEMORY region depending on an expression variable resolves"""
        parser = self._make_parser(MEM_WITH_ASSERT)
        regions = parser.parse_memory_regions()

        self.assertIn('APP_FLASH', regions)
        self.assertEqual(regions['APP_FLASH']['address'], 0x80000)
        self.assertEqual(regions['APP_FLASH']['limit_size'], 512 * 1024)

    def test_literal_variable_survives_assert(self):
        """Control: a literal-defined variable is unaffected by the ASSERT"""
        parser = self._make_parser(MEM_WITH_ASSERT_LITERAL)
        regions = parser.parse_memory_regions()

        self.assertEqual(regions['APP_FLASH']['address'], 0x80000)
        self.assertEqual(regions['APP_FLASH']['limit_size'], 512 * 1024)

    def test_user_variables_with_assert_present(self):
        """--def scenario from the bug report resolves once ASSERT is ignored"""
        parser = self._make_parser(
            MEM_WITH_ASSERT, user_variables={'flash_start': 0x80000})
        try:
            regions = parser.parse_memory_regions()
        except RegionParsingError as exc:
            self.fail(f"user-defined flash_start was overridden: {exc}")

        self.assertEqual(regions['APP_FLASH']['address'], 0x80000)


class TestAssertStripping(unittest.TestCase):
    """ScriptContentCleaner removes ASSERT statements with balanced parens"""

    def test_nested_parens_and_string_with_parens(self):
        """Nested conditions and parentheses inside the message are handled"""
        content = (
            'a = 1; ASSERT(((a == 1) && (b >= 2)), "bad (map)"); b = 2;'
        )
        cleaned = ScriptContentCleaner.clean_content(content)
        self.assertNotIn('ASSERT', cleaned)
        self.assertNotIn('==', cleaned)
        self.assertIn('a = 1;', cleaned)
        self.assertIn('b = 2;', cleaned)

    def test_assert_without_trailing_semicolon(self):
        """ASSERT without ';' is still removed and leaves neighbours intact"""
        cleaned = ScriptContentCleaner.clean_content(
            'x = 4; ASSERT(x > 0, "x") y = 5;')
        self.assertEqual(cleaned.strip(), 'x = 4; y = 5;')

    def test_unbalanced_assert_is_left_untouched(self):
        """A malformed ASSERT is not stripped so nothing after it is lost"""
        content = 'x = 4; ASSERT((x > 0, "x");'
        cleaned = ScriptContentCleaner.clean_content(content)
        self.assertIn('ASSERT', cleaned)
        self.assertIn('x = 4;', cleaned)


class TestAssignmentRegex(unittest.TestCase):
    """Comparison operators are never captured as assignments"""

    def _extract(self, content: str):
        with tempfile.NamedTemporaryFile('w', suffix='.ld', delete=False) as f:
            f.write(content)
            path = f.name
        try:
            extractor = VariableExtractor(ExpressionEvaluator())
            extractor.extract_from_script(path)
            return extractor.variables
        finally:
            Path(path).unlink()

    def test_bare_comparisons_are_not_assignments(self):
        """`x >= 1;` must not be captured as `x = 1;` (and must not clobber x)"""
        variables = self._extract(
            'a = 0x10; b = a + 1; '
            'a >= 0x99; b <= 0x99; a == 0x99; b != 0x99; c == 0x99;'
        )
        self.assertEqual(variables['a'], 0x10)
        self.assertEqual(variables['b'], 0x11)
        self.assertNotIn('c', variables)

    def test_assignment_of_comparison_result_still_captured(self):
        """`c = (a >= 1);` is a real assignment; the operator is in the value"""
        variables = self._extract('a = 0x10; c = (a >= 0x10);')
        self.assertEqual(variables['a'], 0x10)
        self.assertIn('c', variables)


if __name__ == '__main__':
    unittest.main()
