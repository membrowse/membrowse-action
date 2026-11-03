#!/usr/bin/env python3
"""
Tests for reading CU headers ahead of pyelftools: CUs with unsupported
address sizes are skipped one by one, and a stripped ELF has no CUs.
"""
# pylint: disable=protected-access

import io
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from elftools.dwarf.structs import DWARFStructs
from elftools.elf.elffile import ELFFile

from membrowse.analysis.dwarf import (
    DWARFProcessor, _iter_cu_headers, _iter_supported_cus)


def _cu_v4(address_size, body=b'\0'):
    rest = struct.pack('<HIB', 4, 0, address_size) + body
    return struct.pack('<I', len(rest)) + rest


def _cu_v5(address_size, body=b'\0'):
    rest = struct.pack('<HBBI', 5, 1, address_size, 0) + body
    return struct.pack('<I', len(rest)) + rest


def _cu_v4_64bit(address_size, body=b'\0'):
    rest = struct.pack('<HQB', 4, 0, address_size) + body
    return struct.pack('<IQ', 0xFFFFFFFF, len(rest)) + rest


def _dwarfinfo(data):
    return SimpleNamespace(
        debug_info_sec=SimpleNamespace(stream=io.BytesIO(data), size=len(data)),
        structs=DWARFStructs(little_endian=True, dwarf_format=32, address_size=4),
        config=SimpleNamespace(little_endian=True),
        get_CU_at=lambda offset: offset)


class TestCUHeaders(unittest.TestCase):
    """CU header iteration over synthetic .debug_info contents"""

    def test_mixed_address_sizes(self):
        """Only CUs with an unsupported address size are skipped, with one warning"""
        cus = [_cu_v4(4), _cu_v4(2), _cu_v5(8), _cu_v4_64bit(4), _cu_v4(2, b'\0\0')]
        data = b''.join(cus)
        offsets = [sum(len(c) for c in cus[:i]) for i in range(len(cus))]
        dwarfinfo = _dwarfinfo(data)

        headers = list(_iter_cu_headers(dwarfinfo))
        self.assertEqual([o for o, _ in headers], offsets)
        self.assertEqual([h['address_size'] for _, h in headers], [4, 2, 8, 4, 2])

        with self.assertLogs('membrowse.analysis.dwarf', level='WARNING') as logs:
            supported = list(_iter_supported_cus(dwarfinfo))
        self.assertEqual(supported, [offsets[0], offsets[2], offsets[3]])
        self.assertEqual(len(logs.output), 1)
        self.assertIn('unsupported address size 2', logs.output[0])

    def test_reserved_unit_length(self):
        """Iteration stops at a reserved unit_length instead of jumping past it"""
        data = _cu_v4(4) + struct.pack('<I', 0xFFFFFFF0) + b'\0' * 16
        with self.assertLogs('membrowse.analysis.dwarf', level='WARNING'):
            headers = list(_iter_cu_headers(_dwarfinfo(data)))
        self.assertEqual(len(headers), 1)

    def test_no_debug_info_section(self):
        """No .debug_info yields no CUs"""
        self.assertEqual(
            list(_iter_cu_headers(SimpleNamespace(debug_info_sec=None))), [])


@unittest.skipUnless(shutil.which('gcc') and shutil.which('strip'), 'needs gcc and strip')
class TestStrippedELF(unittest.TestCase):
    """Stripped ELF that keeps .eh_frame, so pyelftools reports DWARF info"""

    def test_process_dwarf_info(self):
        """Processing returns empty mappings instead of raising"""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'main.c'
            elf = Path(tmp) / 'main'
            src.write_text('int counter = 1;\nint main(void) { return counter; }\n')
            subprocess.run(['gcc', '-g', '-o', str(elf), str(src)], check=True)
            subprocess.run(['strip', str(elf)], check=True)

            with open(elf, 'rb') as f:
                elffile = ELFFile(f)
                self.assertTrue(elffile.has_dwarf_info())
                self.assertIsNone(elffile.get_dwarf_info().debug_info_sec)
                data = DWARFProcessor(elffile, set()).process_dwarf_info()
        self.assertEqual(data['symbol_to_file'], {})


if __name__ == '__main__':
    unittest.main()
