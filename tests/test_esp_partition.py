#!/usr/bin/env python3
"""Tests for --partition-table: ESP-IDF flash measured against the app slot.

The ESP-IDF linker scripts describe the MMU windows the CPU sees flash
through (4 MB / 3.3 MB on the ESP32, up to 64 MB on the P4), not the app
partition the image must fit. With the build's partition table, the window
regions are replaced by one ``app_partition`` region holding the app image
as esptool lays it out.
"""

import json
import os
import struct
import tempfile
import unittest
from argparse import Namespace
from unittest.mock import patch

from elftools.elf.elffile import ELFFile

from membrowse.analysis.esp_partition import (
    APP_PARTITION_REGION, OVERHEAD_SECTION, SIGNATURE_SECTION, SIGNING_PAD_SECTION,
    EspPartitionError, ImageParams, Partition, _apply_report_sizes, image_params,
    layout_image, parse_partition_table, select_app_partition)
from membrowse.commands.onboard import _build_and_generate_report
from membrowse.commands.report import _validate_partition_input, generate_report

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')
STM32_DIR = os.path.join(FIXTURES, 'micropython', 'stm32')


def _entry(name, ptype, subtype, offset, size):
    return struct.pack('<2sBBII16sI', b'\xaa\x50', ptype, subtype, offset,
                       size, name.encode(), 0)


def _table(*entries, md5=True):
    data = b''.join(entries)
    if md5:
        data += b'\xeb\xeb' + b'\xff' * 14 + b'\x00' * 16
    return data + b'\xff' * 64


def _write(td, name, data):
    path = os.path.join(td, name)
    with open(path, 'wb') as f:
        f.write(data)
    return path


class TestParsePartitionTable(unittest.TestCase):
    """``partitions.bin`` is a list of 32-byte entries ending at the first
    entry without the ``AA 50`` magic."""

    def test_reads_entries_until_md5_entry(self):
        """Entries are read up to the MD5 entry."""
        with tempfile.TemporaryDirectory() as td:
            path = _write(td, 'partitions.bin', _table(
                _entry('nvs', 1, 2, 0x9000, 0x5000),
                _entry('app0', 0, 0x10, 0x10000, 0x1B0000),
                _entry('app1', 0, 0x11, 0x1C0000, 0x1B0000)))
            parts = parse_partition_table(path)
        self.assertEqual([p.name for p in parts], ['nvs', 'app0', 'app1'])
        self.assertEqual(parts[1], Partition('app0', 0, 0x10, 0x10000, 0x1B0000))

    def test_csv_is_refused(self):
        """The CSV is not the compiled table: a clear error, not 0 entries."""
        with tempfile.TemporaryDirectory() as td:
            path = _write(td, 'partitions.csv',
                          b'# Name, Type, SubType, Offset, Size\n'
                          b'app0, app, ota_0, 0x10000, 0x1B0000\n')
            with self.assertRaisesRegex(EspPartitionError, 'not the CSV'):
                parse_partition_table(path)

    def test_missing_file(self):
        """A missing table is an EspPartitionError."""
        with self.assertRaisesRegex(EspPartitionError, 'not found'):
            parse_partition_table('/nonexistent/partitions.bin')


class TestSelectAppPartition(unittest.TestCase):
    """The image must fit any app slot it can be flashed to, so the limit is
    the smallest app partition unless one is named."""

    PARTS = [
        Partition('nvs', 1, 2, 0x9000, 0x6000),
        Partition('factory', 0, 0x00, 0x10000, 0x100000),
        Partition('ota_0', 0, 0x10, 0x110000, 0x180000),
        Partition('ota_1', 0, 0x11, 0x290000, 0x180000),
        Partition('spiffs', 1, 0x82, 0x410000, 0x3F0000),
    ]

    def test_smallest_app_partition(self):
        """factory (1 MB) is smaller than the OTA slots."""
        self.assertEqual(select_app_partition(self.PARTS).name, 'factory')

    def test_data_partitions_are_ignored(self):
        """nvs and spiffs are smaller or larger but never chosen."""
        parts = [self.PARTS[0], self.PARTS[2], self.PARTS[4]]
        self.assertEqual(select_app_partition(parts).name, 'ota_0')

    def test_named_partition(self):
        """A named slot wins over the smallest."""
        self.assertEqual(select_app_partition(self.PARTS, 'ota_1').name, 'ota_1')

    def test_unknown_name(self):
        """A name that is not an app partition is an error."""
        with self.assertRaisesRegex(EspPartitionError, "No app partition named 'app9'"):
            select_app_partition(self.PARTS, 'app9')

    def test_uneven_slots_are_logged(self):
        """A small second app slot (meshtastic's flashApp OTA loader) is
        still the default, but the choice is logged with the way out."""
        parts = [Partition('app', 0, 0x10, 0x10000, 0x250000),
                 Partition('flashApp', 0, 0x11, 0x260000, 0xA0000)]
        with self.assertLogs('membrowse.analysis.esp_partition', 'WARNING') as logs:
            self.assertEqual(select_app_partition(parts).name, 'flashApp')
        self.assertIn('partition_name', logs.output[0])

    def test_even_slots_are_not_logged(self):
        """Two equal OTA slots: no warning."""
        parts = [self.PARTS[2], self.PARTS[3]]
        with patch('membrowse.analysis.esp_partition.logger') as log:
            select_app_partition(parts)
        log.warning.assert_not_called()  # assertNoLogs needs Python 3.10

    def test_no_app_partition(self):
        """A table without app partitions is an error."""
        with self.assertRaisesRegex(EspPartitionError, 'no app partition'):
            select_app_partition([self.PARTS[0], self.PARTS[4]])


def _esp32_flash(addr):
    return 0x3F400000 <= addr < 0x3F800000 or 0x400D0000 <= addr < 0x40400000


class TestLayoutImage(unittest.TestCase):
    """The image layout follows esptool's elf2image."""

    def test_flash_segments_land_on_their_mmu_offset(self):
        """Each flash segment's data starts at the file offset matching its
        virtual address within a 64 KB page; the gap before it is filled
        with RAM segments, cut where needed, and the rest of RAM follows."""
        sections = [
            ('.flash.rodata', 0x3F400020, 0x1000),
            ('.dram0.data', 0x3FFB0000, 0x2000),
            ('.iram0.text', 0x40080000, 0x20000),
            ('.flash.text', 0x400D0020, 0x3000),
        ]
        chunks, size = layout_image(sections, _esp32_flash)
        placed = [(c.vaddr, c.length, c.file_offset) for c in chunks]
        self.assertEqual(placed[0], (0x3F400020, 0x1000, 0x20))
        flash_text = [c for c in chunks if c.vaddr == 0x400D0020][0]
        self.assertEqual(flash_text.file_offset % 0x10000, 0x20)
        ram_bytes = sum(c.length for c in chunks
                        if c.vaddr is not None and not _esp32_flash(c.vaddr))
        self.assertEqual(ram_bytes, 0x22000)
        # .iram0.text is split: part fills the gap, the rest goes last
        iram = [c for c in chunks if c.vaddr and 0x40080000 <= c.vaddr < 0x400A0000]
        self.assertEqual(len(iram), 2)
        self.assertEqual(chunks[-1].vaddr, iram[1].vaddr)
        self.assertEqual(size % 16, 0)

    def test_sections_are_padded_to_four_bytes_and_merged(self):
        """Contiguous sections of an odd size merge into one segment once
        each is padded to 4 bytes, as esptool does."""
        sections = [
            ('.flash.text', 0x400D0020, 0x101),
            ('.phyiram.0', 0x400D0124, 0x2B),
            ('.dram0.data', 0x3FFB0000, 0x10),
        ]
        chunks, _ = layout_image(sections, _esp32_flash)
        flash = [c for c in chunks if c.vaddr and _esp32_flash(c.vaddr)]
        self.assertEqual(len(flash), 1)
        self.assertEqual(flash[0].length, 0x104 + 0x2C)

    def test_signed_image_ends_on_a_page_then_the_signature_sector(self):
        """Secure Boot V2: a padding segment makes the image (with its
        checksum and digest) end on a page boundary; the 4 KB signature
        sector follows."""
        sections = [('.flash.text', 0x400D0020, 0x3000),
                    ('.dram0.data', 0x3FFB0000, 0x123)]
        _, unsigned = layout_image(sections, _esp32_flash)
        for page in (0x10000, 0x8000):
            with self.subTest(page=page):
                chunks, size = layout_image(
                    sections, _esp32_flash,
                    ImageParams(mmu_page_size=page, signed_sbv2=True))
                self.assertEqual((size - 4096) % page, 0)
                self.assertGreater(size - 4096, unsigned)
                pad, sig = chunks[-2], chunks[-1]
                self.assertEqual((pad.name, sig.name),
                                 (SIGNING_PAD_SECTION, SIGNATURE_SECTION))
                self.assertEqual(pad.file_offset + pad.length + 16 + 32, size - 4096)
                self.assertEqual((sig.file_offset, sig.length), (size - 4096, 4096))


class TestValidatePartitionInput(unittest.TestCase):
    """CLI checks for --partition-table / --partition-name."""

    def test_name_needs_table(self):
        """--partition-name alone is refused."""
        self.assertIn('requires --partition-table',
                      _validate_partition_input(None, 'ota_0', ['memory.ld']))

    def test_table_needs_linker_scripts(self):
        """The window regions come from the linker scripts."""
        self.assertIn('linker scripts',
                      _validate_partition_input('partitions.bin', None, []))

    def test_valid(self):
        """Both set, or neither, is accepted."""
        self.assertIsNone(
            _validate_partition_input('partitions.bin', 'ota_0', ['memory.ld']))
        self.assertIsNone(_validate_partition_input(None, None, []))


class TestNotAnEspIdfApp(unittest.TestCase):
    """A partition table on a target that is not an ESP-IDF app is a
    configuration error, not a silent no-op."""

    def test_stm32_elf_is_refused(self):
        """An ELF without .flash.appdesc is refused."""
        with tempfile.TemporaryDirectory() as td:
            table = _write(td, 'partitions.bin', _table(
                _entry('factory', 0, 0, 0x10000, 0x100000)))
            with self.assertRaisesRegex(EspPartitionError, '.flash.appdesc'):
                generate_report(
                    os.path.join(STM32_DIR, 'firmware.elf'),
                    os.path.join(STM32_DIR, 'linker', 'stm32f405.ld'),
                    skip_line_program=True, partition_table=table)


class TestOnboardTreatsPartitionErrorsAsFailedBuilds(unittest.TestCase):
    """During onboarding an old commit may predate the partition table or the
    ESP-IDF app descriptor. That commit is a failed build; the onboard goes
    on, and the target's history never mixes the two layouts."""

    @patch('membrowse.commands.onboard.subprocess.run')
    @patch('membrowse.commands.onboard.git_clean')
    @patch('membrowse.commands.onboard.git_submodule_update')
    @patch('membrowse.commands.onboard.git_checkout')
    @patch('membrowse.commands.onboard.generate_report')
    def test_missing_partition_table(self, mock_report, _checkout, _submodules,
                                     _clean, mock_run):
        """The commit is uploaded as a failed build instead of aborting."""
        mock_run.return_value.returncode = 0
        mock_report.side_effect = EspPartitionError('Partition table not found')
        with tempfile.TemporaryDirectory() as td:
            elf = _write(td, 'app.elf', b'\x7fELF')
            args = Namespace(build_script='true', elf_path=elf,
                             ld_scripts='memory.ld',
                             partition_table=os.path.join(td, 'partitions.bin'),
                             partition_name=None)
            report, build_failed = _build_and_generate_report('abc123', args, None)
        self.assertTrue(build_failed)
        self.assertEqual(report['memory_layout'], {})
        self.assertEqual(mock_report.call_args.kwargs['partition_table'],
                         args.partition_table)


ESP_FIXTURES = os.path.join(FIXTURES, 'esp-idf')

# name: (linker scripts, partition table, flash window regions it replaces)
ESP_TARGETS = {
    # ESP-IDF 6.0.3 builds (idf.py), default "Single factory app" table
    'hello-esp32': (['memory.ld', 'sections.ld'], 'partition-table.bin',
                    {'iram0_2_seg', 'drom0_0_seg'}),
    'hello-esp32s3': (['memory.ld', 'sections.ld'], 'partition-table.bin',
                      {'iram0_2_seg', 'drom0_0_seg'}),
    'hello-esp32c6': (['memory.ld', 'sections.ld'], 'partition-table.bin',
                      {'irom_seg', 'drom_seg'}),
    'hello-esp32p4': (['memory.ld', 'sections.ld'], 'partition-table.bin',
                      {'irom_seg', 'drom_seg'}),
    # factory + two OTA slots
    'simple-ota-esp32': (['memory.ld', 'sections.ld'], 'partition-table.bin',
                         {'iram0_2_seg', 'drom0_0_seg'}),
    # PlatformIO, Arduino-ESP32 2.0 (IDF 4.4), custom two-slot OTA table
    'diybms-controller-pio': (['memory.ld'], 'partitions.bin',
                              {'iram0_2_seg', 'drom0_0_seg'}),
    # muse-gadget-sdk, ESP-IDF 6.0.3, signed app (Secure Boot V2 scheme)
    'signed-esp32c3': (['memory.ld', 'sections.ld'], 'partition-table.bin',
                       {'iram0_2_seg', 'drom0_0_seg'}),
}


def _esp_report(name, partition=True, partition_name=None, **kwargs):
    scripts, table, _ = ESP_TARGETS[name]
    base = os.path.join(ESP_FIXTURES, name)
    return generate_report(
        os.path.join(base, 'app.elf'),
        ' '.join(os.path.join(base, s) for s in scripts),
        skip_line_program=True,
        partition_table=os.path.join(base, table) if partition else None,
        partition_name=partition_name, **kwargs)


def _image(name):
    with open(os.path.join(ESP_FIXTURES, name, 'image.json'), encoding='utf-8') as f:
        return json.load(f)


class TestRealBuilds(unittest.TestCase):
    """Real builds: the app_partition region must match the .bin esptool
    wrote (image.json: its size and segment table)."""

    def test_used_size_is_the_bin_size(self):
        """used_size equals the .bin size, and the entries add up to it."""
        for name in ESP_TARGETS:
            with self.subTest(name):
                region = _esp_report(name)['memory_layout'][APP_PARTITION_REGION]
                self.assertEqual(region['used_size'], _image(name)['bin_size'])
                self.assertEqual(
                    region['used_size'], sum(s['size'] for s in region['sections']))

    def test_segments_sit_at_their_offset_in_the_bin(self):
        """Each .bin segment holding section data starts at the partition
        offset + its file offset in the report."""
        for name in ESP_TARGETS:
            with self.subTest(name):
                region = _esp_report(name)['memory_layout'][APP_PARTITION_REGION]
                starts = {s['address'] for s in region['sections']
                          if s['name'] not in (OVERHEAD_SECTION, SIGNING_PAD_SECTION)}
                for seg in _image(name)['segments']:
                    if seg['load_address'] == 0:
                        continue  # zero padding segment
                    self.assertIn(region['address'] + seg['file_offset'], starts,
                                  f"segment at 0x{seg['load_address']:x}")

    def test_windows_replaced_and_other_regions_kept(self):
        """Only the window regions go; app_partition is the only new one."""
        for name, (_, _, windows) in ESP_TARGETS.items():
            with self.subTest(name):
                before = set(_esp_report(name, partition=False)['memory_layout'])
                after = set(_esp_report(name)['memory_layout'])
                self.assertEqual(before - after, windows)
                self.assertEqual(after - before, {APP_PARTITION_REGION})

    def test_without_partition_table_the_report_is_unchanged(self):
        """Opt-in: no input, no change."""
        layout = _esp_report('hello-esp32', partition=False)['memory_layout']
        self.assertNotIn(APP_PARTITION_REGION, layout)
        self.assertEqual(layout['drom0_0_seg']['limit_size'], 0x400000 - 0x20)

    def test_limit_is_the_smallest_app_partition(self):
        """factory 1 MB in the default table; the OTA example's three slots
        are 0x1A9000 each and the factory one comes first."""
        hello = _esp_report('hello-esp32')['memory_layout'][APP_PARTITION_REGION]
        self.assertEqual((hello['address'], hello['limit_size']), (0x10000, 0x100000))
        self.assertEqual(hello['type'], 'R')
        ota = _esp_report('simple-ota-esp32')['memory_layout'][APP_PARTITION_REGION]
        self.assertEqual((ota['address'], ota['limit_size']), (0x20000, 0x1A9000))

    def test_named_partition(self):
        """--partition-name moves the region to that slot."""
        ota = _esp_report('simple-ota-esp32', partition_name='ota_1')
        region = ota['memory_layout'][APP_PARTITION_REGION]
        table = parse_partition_table(
            os.path.join(ESP_FIXTURES, 'simple-ota-esp32', 'partition-table.bin'))
        ota_1 = [p for p in table if p.name == 'ota_1'][0]
        self.assertEqual(region['address'], ota_1.offset)

    def test_psram_region_over_the_constants_window_is_kept(self):
        """On the S3, extern_ram_seg (RWX) is declared over the same range as
        drom0_0_seg (R). Only the read-only window goes."""
        layout = _esp_report('hello-esp32s3')['memory_layout']
        self.assertIn('extern_ram_seg', layout)
        self.assertFalse(any(s['name'].startswith('.flash.')
                             for s in layout['extern_ram_seg']['sections']))

    def test_address_placeholders_are_dropped_from_psram(self):
        """.flash_rodata_dummy and .ext_ram.dummy only reserve the window's
        addresses: not PSRAM use. DRAM's .dram0.dummy (the IRAM share of the
        shared SRAM) is not a window section and stays."""
        layout = _esp_report('hello-esp32s3')['memory_layout']
        before = _esp_report('hello-esp32s3', partition=False)['memory_layout']
        self.assertIn('.ext_ram.dummy',
                      {s['name'] for s in before['drom0_0_seg']['sections']})
        names = {s['name'] for s in layout['extern_ram_seg']['sections']}
        self.assertFalse(names & {'.flash_rodata_dummy', '.ext_ram.dummy'})
        self.assertEqual(layout['extern_ram_seg']['used_size'], 0)
        self.assertIn('.dram0.dummy',
                      {s['name'] for s in layout['dram0_0_seg']['sections']})

    def test_mmu_page_size_from_the_app_descriptor(self):
        """The C6 build has 2 MB flash and 32 KB MMU pages: its code segment
        starts at a 32 KB boundary + 0x20, not 64 KB."""
        with open(os.path.join(ESP_FIXTURES, 'hello-esp32c6', 'app.elf'), 'rb') as f:
            self.assertEqual(image_params(ELFFile(f)).mmu_page_size, 0x8000)
        with open(os.path.join(ESP_FIXTURES, 'hello-esp32', 'app.elf'), 'rb') as f:
            params = image_params(ELFFile(f))
        self.assertEqual(params.mmu_page_size, 0x10000)
        self.assertTrue(params.esp32_tail_pad)

    def test_app_descriptor_segment_comes_first(self):
        """On the P4 the constants window is above the code window, but the
        app descriptor's segment is written first, at offset 0x20."""
        region = _esp_report('hello-esp32p4')['memory_layout'][APP_PARTITION_REGION]
        desc = [s for s in region['sections'] if s['name'] == '.flash.appdesc'][0]
        self.assertEqual(desc['address'], region['address'] + 0x20)

    def test_iram_and_data_count_in_flash(self):
        """IRAM code and .data initial values are in the image, so they count
        against the partition as well as against RAM."""
        region = _esp_report('diybms-controller-pio')['memory_layout'][APP_PARTITION_REGION]
        names = {s['name'] for s in region['sections']}
        self.assertTrue({'.iram0.text', '.dram0.data', '.flash.text',
                         '.flash.rodata'} <= names)
        self.assertNotIn('.flash.rodata_noload', names)  # NOBITS: not in the image


class TestReportOptions(unittest.TestCase):
    """--skip-section and --exclude-alignment apply to app_partition too:
    the layout comes from the whole ELF, the counted bytes from the
    report's sections."""

    def test_skipped_section_is_not_counted(self):
        """Skipping .dram0.data drops its bytes from the partition; the
        other entries keep their addresses."""
        full = _esp_report('hello-esp32')['memory_layout'][APP_PARTITION_REGION]
        skipped = _esp_report('hello-esp32', skip_sections=['.dram0.data'])[
            'memory_layout'][APP_PARTITION_REGION]
        data = sum(s['size'] for s in full['sections'] if s['name'] == '.dram0.data')
        self.assertGreater(data, 0)
        self.assertEqual(skipped['used_size'], full['used_size'] - data)
        self.assertEqual(
            {(s['name'], s['address'], s['size']) for s in full['sections']
             if s['name'] != '.dram0.data'},
            {(s['name'], s['address'], s['size']) for s in skipped['sections']})

    def test_skipping_flash_sections_keeps_the_windows(self):
        """Skipping the only section of a window (.flash.text), or every
        .flash.* section, still replaces both windows and keeps the layout:
        the windows are found from the unfiltered ELF."""
        full = _esp_report('hello-esp32')['memory_layout']
        region = full[APP_PARTITION_REGION]
        flash = sorted({s['name'] for s in region['sections']
                        if s['name'].startswith('.flash.')})
        for skip in (['.flash.text'], flash):
            with self.subTest(skip=skip):
                layout = _esp_report('hello-esp32', skip_sections=skip)['memory_layout']
                self.assertEqual(set(layout), set(full))
                skipped = layout[APP_PARTITION_REGION]
                dropped = sum(s['size'] for s in region['sections'] if s['name'] in skip)
                self.assertEqual(skipped['used_size'], region['used_size'] - dropped)
                self.assertEqual(
                    {(s['name'], s['address']) for s in region['sections']
                     if s['name'] not in skip},
                    {(s['name'], s['address']) for s in skipped['sections']})

    def test_excluded_padding_is_trimmed_from_the_end(self):
        """A section split in two pieces loses its excluded padding from
        the higher-addressed piece; overhead and signing entries stay."""
        entries = [
            {'name': '.iram0.text', 'address': 0x100, 'size': 0x40,
             'type': 'unknown', 'end_address': 0x140},
            {'name': '.iram0.text', 'address': 0x400, 'size': 0x20,
             'type': 'unknown', 'end_address': 0x420},
            {'name': OVERHEAD_SECTION, 'address': 0, 'size': 0x18,
             'type': 'unknown', 'end_address': 0x18},
            {'name': '.skipped', 'address': 0x200, 'size': 0x10,
             'type': 'unknown', 'end_address': 0x210},
        ]
        kept = _apply_report_sizes(entries, {'.iram0.text': (0x50, 'text')})
        by_addr = {e['address']: e for e in kept}
        self.assertEqual(sorted(by_addr), [0, 0x100, 0x400])
        self.assertEqual((by_addr[0x100]['size'], by_addr[0x400]['size']), (0x40, 0x10))
        self.assertEqual(by_addr[0x400]['end_address'], 0x410)
        self.assertEqual(by_addr[0x100]['type'], 'text')


class TestSignedBuild(unittest.TestCase):
    """A signed app's .bin carries esptool's signing padding and the
    signature sector; both count against the partition."""

    def test_signing_is_detected_from_the_elf(self):
        """Only the signed build links the Secure Boot V2 verifier."""
        for name in ESP_TARGETS:
            with self.subTest(name):
                with open(os.path.join(ESP_FIXTURES, name, 'app.elf'), 'rb') as f:
                    signed = image_params(ELFFile(f)).signed_sbv2
                self.assertEqual(signed, name == 'signed-esp32c3')

    def test_signing_is_detected_without_the_verifier(self):
        """A signed app without OTA has the verifier dropped by
        --gc-sections; the other function from the same file still marks
        it as signed."""
        verifier = 'esp_secure_boot_verify_sbv2_signature_block'
        with open(os.path.join(ESP_FIXTURES, 'signed-esp32c3', 'app.elf'), 'rb') as f:
            elf = ELFFile(f)
            symtab = elf.get_section_by_name('.symtab')
            real_iter = symtab.iter_symbols

            def without_verifier():
                return (s for s in real_iter() if s.name != verifier)

            with patch.object(symtab, 'iter_symbols', without_verifier):
                self.assertNotIn(verifier, {s.name for s in symtab.iter_symbols()})
                with patch.object(elf, 'get_section_by_name',
                                  lambda name: symtab if name == '.symtab'
                                  else ELFFile.get_section_by_name(elf, name)):
                    self.assertTrue(image_params(elf).signed_sbv2)

    def test_padding_and_signature_entries(self):
        """The padding entry is the .bin's address-0 segment; the signature
        sector is the last 4 KB of the image."""
        region = _esp_report('signed-esp32c3')['memory_layout'][APP_PARTITION_REGION]
        by_name = {s['name']: s for s in region['sections']}
        pad_seg = _image('signed-esp32c3')['segments'][-1]
        self.assertEqual(pad_seg['load_address'], 0)
        pad = by_name[SIGNING_PAD_SECTION]
        self.assertEqual((pad['address'], pad['size']),
                         (region['address'] + pad_seg['file_offset'], pad_seg['length']))
        sig = by_name[SIGNATURE_SECTION]
        self.assertEqual((sig['size'], sig['end_address']),
                         (4096, region['address'] + region['used_size']))

    def test_unsigned_builds_have_no_signing_entries(self):
        """No padding or signature entries without signing."""
        names = {s['name'] for s in _esp_report('hello-esp32s3')['memory_layout']
                 [APP_PARTITION_REGION]['sections']}
        self.assertFalse(names & {SIGNING_PAD_SECTION, SIGNATURE_SECTION})


class TestConstants(unittest.TestCase):
    """Names the platform sees; changing them breaks targets' histories."""

    def test_names(self):
        """Fixed region and overhead names."""
        self.assertEqual(APP_PARTITION_REGION, 'app_partition')
        self.assertEqual(OVERHEAD_SECTION, 'esp_image_overhead')


if __name__ == '__main__':
    unittest.main()
