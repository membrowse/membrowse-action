#!/usr/bin/env python3
"""
Test cases for source file mapping of GCC LTO builds.

With -flto the code is emitted in an "<artificial>" compilation unit whose
DIEs carry only DW_AT_abstract_origin, pointing at the DIE in the unit of the
source file that defined the symbol. That DIE's DW_AT_decl_file indexes the
file table of its own unit, not the one of the "<artificial>" unit.
"""

import platform
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from membrowse.core.generator import ReportGenerator
from tests.test_helpers import rmtree_robust

# exti.c includes two headers, so the file numbers of its unit differ from
# those of encode.c and main.c
SOURCES = {
    'a.h': 'static inline int a_helper(int x) { return x * 3 + 1; }\n',
    'b.h': 'static inline int b_helper(int x) { return x * 5 + 2; }\n',
    'exti.c': (
        '#include "a.h"\n'
        '#include "b.h"\n'
        'volatile int exti_state;\n'
        'int exti_init(int x) '
        '{ exti_state = a_helper(x) + b_helper(x); return exti_state; }\n'),
    'encode.c': (
        'volatile int enc_state;\n'
        'static int enc_local(int x) { enc_state += x; return enc_state * 7; }\n'
        'int Encode(int x) '
        '{ int r = 0; for (int i = 0; i < x; i++) r += enc_local(i); return r; }\n'),
    'main.c': (
        'int exti_init(int); int Encode(int);\n'
        'int main(int argc, char **argv) '
        '{ (void)argv; return exti_init(argc) + Encode(argc); }\n'),
}

EXPECTED = {
    'exti_init': ('exti.c', 4),
    'exti_state': ('exti.c', 3),
    'enc_local': ('encode.c', 2),
    'enc_state': ('encode.c', 1),
    'Encode': ('encode.c', 3),
    'main': ('main.c', 2),
}


@unittest.skipIf(platform.system() == 'Windows', 'native gcc does not produce ELF')
@unittest.skipUnless(shutil.which('gcc'), 'gcc not available')
class TestLTOSourceMapping(unittest.TestCase):
    """Symbols of an LTO build are reported in the file that defines them"""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        for name, text in SOURCES.items():
            (self.temp_dir / name).write_text(text)

    def tearDown(self):
        rmtree_robust(self.temp_dir)

    def _symbols(self, debug_flag):
        """Build with LTO and return {name: (source_file, source_line)}."""
        flags = ['-Og', debug_flag, '-flto', '-fno-inline',
                 '-ffunction-sections', '-fdata-sections']
        elf = self.temp_dir / 'lto.elf'
        result = subprocess.run(
            ['gcc', *flags, 'exti.c', 'encode.c', 'main.c', '-o', str(elf)],
            cwd=self.temp_dir, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            self.skipTest(f'LTO build failed: {result.stderr}')
        report = ReportGenerator(str(elf)).generate_report()
        return {s['name']: (s['source_file'], s['source_line'])
                for s in report['symbols'] if s['name'] in EXPECTED}

    def test_default_dwarf(self):
        """The compiler's default DWARF version"""
        self.assertEqual(self._symbols('-g'), EXPECTED)

    def test_dwarf2(self):
        """DWARF 2 line tables, whose file numbers are 1-based"""
        self.assertEqual(self._symbols('-gdwarf-2'), EXPECTED)


if __name__ == '__main__':
    unittest.main()
