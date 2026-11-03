#!/usr/bin/env python3
"""
Reports for firmware of projects tracked on MemBrowse: Meshtastic,
TinyUSB, NuttX and wolfSSL.

Each fixture directory holds the ELF, the linker scripts and the linker
map file of one target, plus memory_layout.json: the memory layout the
report gave when the fixture was added (identical in v1.2.17).
Source locations checked below agree with arm-none-eabi-addr2line.
"""

import json
import unittest
from functools import lru_cache
from pathlib import Path

from membrowse.core import ReportGenerator
from membrowse.linker.parser import LinkerScriptParser

FIXTURES = Path(__file__).parent / "fixtures"

TARGETS = {
    'meshtastic-picow': (
        'meshtastic/picow', 'firmware.elf', ['memmap_default.ld'], 'firmware.map'),
    'tinyusb-stm32f407disco': (
        'tinyusb/stm32f407disco', 'cdc_msc.elf',
        ['STM32F407VGTx_FLASH.ld'], 'cdc_msc.map'),
    'tinyusb-feather_nrf52840_express': (
        'tinyusb/feather_nrf52840_express', 'cdc_msc.elf',
        ['nrf52840_s140_v6.ld', 'nrf_common.ld'], 'cdc_msc.map'),
    'nuttx-nucleo-f103rb': (
        'nuttx/nucleo-f103rb', 'nuttx.elf', ['ld.script'], 'nuttx.map'),
    'nuttx-arduino-mega2560': (
        'nuttx/arduino-mega2560', 'nuttx.elf', ['flash.ld'], 'nuttx.map'),
    'wolfssl-cortex-m4-min-ecc': (
        'wolfssl/cortex-m4-min-ecc', 'WolfCryptTest.elf',
        ['linker.ld'], 'WolfCryptTest.map'),
}


@lru_cache(maxsize=None)
def _report(target, use_map=True):
    directory, elf, scripts, map_file = TARGETS[target]
    base = FIXTURES / directory
    elf_path = str(base / elf)
    regions = LinkerScriptParser(
        [str(base / s) for s in scripts], elf_file=elf_path).parse_memory_regions()
    return ReportGenerator(
        elf_path, regions,
        map_file_path=str(base / map_file) if use_map else None).generate_report()


def _symbols(target):
    """First symbol of each name"""
    symbols = {}
    for symbol in _report(target)['symbols']:
        symbols.setdefault(symbol['name'], symbol)
    return symbols


class ProjectTestCase(unittest.TestCase):
    """Helpers shared by the per-project tests"""

    def assert_source(self, target, expected):
        """Symbols map to the expected (source_file, source_line)"""
        symbols = _symbols(target)
        for name, location in expected.items():
            with self.subTest(target=target, symbol=name):
                symbol = symbols[name]
                self.assertEqual(
                    (symbol['source_file'], symbol['source_line']), location)

    def assert_object(self, target, expected):
        """Symbols map to the expected (archive basename, object file suffix)"""
        symbols = _symbols(target)
        for name, (archive, obj) in expected.items():
            with self.subTest(target=target, symbol=name):
                symbol = symbols[name]
                self.assertEqual(Path(symbol['archive']).name, archive)
                self.assertTrue(
                    symbol['object_file'].endswith(obj), symbol['object_file'])


class TestMemoryLayout(unittest.TestCase):
    """Regions and sections match the recorded layout, with or without map"""

    def test_layout(self):
        """Every target's layout equals memory_layout.json"""
        for target, (directory, *_) in TARGETS.items():
            expected = json.loads(
                (FIXTURES / directory / 'memory_layout.json').read_text())
            for use_map in (True, False):
                with self.subTest(target=target, map_file=use_map):
                    self.assertEqual(
                        _report(target, use_map)['memory_layout'], expected)


class TestMeshtastic(ProjectTestCase):
    """RP2040 (picow), arduino-pico toolchain gcc 16, C++, linker veneers"""

    TARGET = 'meshtastic-picow'

    def test_report(self):
        """Architecture and symbol count"""
        report = _report(self.TARGET)
        self.assertEqual(report['architecture'], 'ARM')
        self.assertEqual(report['toolchain'], 'gcc-16.1.0')
        self.assertEqual(len(report['symbols']), 9749)

    def test_source_locations(self):
        """Library functions map to their line; code without line rows to none"""
        self.assert_source(self.TARGET, {
            'strcpy': ('strcpy.c', 44),
            '__sccl': ('sccl.c', 36),
            # Copied to RAM (.data)
            'next_unwind_byte': ('pr-support.c', 85),
            # Linker generated veneers have no source
            '__mutex_exit_veneer': ('', 0),
            '____freertos_idle_other_core_veneer': ('', 0),
            # Built without debug info: not the neighbouring CU's file
            'Adafruit_BusIO_Register::write(unsigned char*, unsigned char)': ('', 0),
            'lwip_freertos_init': ('', 0),
            '_init': ('', 0),
        })

    def test_map_file_objects(self):
        """Archive and object file come from the map file"""
        self.assert_object(self.TARGET, {
            'strcpy': ('libc.a', 'libc_a-strcpy.o'),
            'Adafruit_BusIO_Register::write(unsigned char*, unsigned char)': (
                'libAdafruit BusIO.a', 'Adafruit_BusIO_Register.cpp.o'),
            'setup': ('', 'src/main.cpp.o'),
            # Merged .str1.N sections are listed at these addresses too
            'DAYS_IN_MONTH': ('libc.a', 'libc_a-mktime.o'),
            'CSWTCH.56': ('', 'RedirectablePrint.cpp.o'),
            '__func__.2': ('', 'sleep.c.o'),
            'uxTopUsedPriority': ('libFrameworkArduino.a', 'tasks.c.o'),
        })


class TestTinyUSB(ProjectTestCase):
    """cdc_msc example on STM32F407 and nRF52840"""

    def test_report(self):
        """Symbol counts"""
        self.assertEqual(len(_report('tinyusb-stm32f407disco')['symbols']), 328)
        self.assertEqual(
            len(_report('tinyusb-feather_nrf52840_express')['symbols']), 376)

    def test_source_locations_stm32(self):
        """Functions map to their first line"""
        self.assert_source('tinyusb-stm32f407disco', {
            'main': ('main.c', 51),
            'tud_mount_cb': ('main.c', 74),
            'tud_task_ext': ('usbd.c', 690),
            # First row is DWC2_REG() inlined from dwc2_common.h:66
            'dcd_int_handler': ('dcd_dwc2.c', 1251),
        })

    def test_source_locations_nrf(self):
        """Functions map to their first line, linker symbols to nothing"""
        self.assert_source('tinyusb-feather_nrf52840_express', {
            'tud_mount_cb': ('main.c', 74),
            'dcd_int_handler': ('dcd_nrf5x.c', 939),
            # Starts with an inlined call
            'nrf_gpio_pin_port_decode': ('nrf_gpio.h', 1574),
            '__text_end': ('', 0),
        })

    def test_map_file_objects(self):
        """Object files and archives from the map files"""
        self.assert_object('tinyusb-stm32f407disco', {
            'tud_mount_cb': ('', 'cdc_msc.dir/src/main.c.obj'),
            'dcd_int_handler': ('', 'dcd_dwc2.c.obj'),
        })
        self.assert_object('tinyusb-feather_nrf52840_express', {
            'nrf_gpio_pin_port_decode': (
                'libboard_feather_nrf52840_express.a', 'nrfx_uarte.c.obj'),
        })


class TestNuttX(ProjectTestCase):
    """nsh on STM32F103 (ARM) and ATmega2560 (AVR, no debug info)"""

    def test_report(self):
        """Architectures and symbol counts"""
        arm = _report('nuttx-nucleo-f103rb')
        self.assertEqual(arm['architecture'], 'ARM')
        self.assertEqual(len(arm['symbols']), 511)
        avr = _report('nuttx-arduino-mega2560')
        self.assertEqual(avr['architecture'], 'AVR')
        self.assertEqual(len(avr['symbols']), 706)

    def test_source_locations_arm(self):
        """Functions map to their source; a tail-call stub without DWARF to none"""
        self.assert_source('nuttx-nucleo-f103rb', {
            'nx_start': ('nx_start.c', 504),
            'nsh_main': ('nsh_main.c', 54),
            'vasprintf': ('lib_vasprintf.c', 153),
            # 4 byte b.w outside every CU's ranges: no line rows
            'nx_vasprintf': ('', 0),
        })
        # Line is that of an inlined function from an #included .c file
        self.assertEqual(
            _symbols('nuttx-nucleo-f103rb')['stm32_clockconfig']['source_file'],
            'stm32_rcc.c')

    def test_avr_without_debug_info(self):
        """No source files, objects still come from the map file"""
        self.assertFalse(
            any(s['source_file'] for s in _report('nuttx-arduino-mega2560')['symbols']))
        self.assert_object('nuttx-arduino-mega2560', {
            'nx_start': ('libsched.a', 'nx_start.o'),
            'up_initialize': ('libarch.a', 'avr_initialize.o'),
        })


class TestWolfSSL(ProjectTestCase):
    """wolfCrypt min-ecc built with -flto and no -g: only libc has DWARF"""

    TARGET = 'wolfssl-cortex-m4-min-ecc'

    def test_report(self):
        """Toolchain and symbol count"""
        report = _report(self.TARGET)
        self.assertEqual(report['toolchain'], 'gcc-13.2.1')
        self.assertEqual(len(report['symbols']), 723)

    def test_source_locations(self):
        """Code without DWARF is not attributed to crt0.S"""
        self.assert_source(self.TARGET, {
            'main': ('', 0),
            'my_time': ('', 0),
            'wc_ecc_sign_hash': ('', 0),
            'frame_dummy': ('', 0),
            '_ctype_': ('ctype_.c', 0),
        })

    def test_map_file_objects(self):
        """LTO objects resolved from the map file"""
        self.assert_object(self.TARGET, {
            'main': ('', 'Build/test_main.o'),
            'wc_ecc_sign_hash': ('', 'Build/ecc.o'),
            '_ctype_': ('libc_nano.a', 'libc_a-ctype_.o'),
        })


class TestSourceLinePairing(ProjectTestCase):
    """The reported line is a line of the reported source file"""

    def test_line_from_included_c_file(self):
        """stm32_clockconfig is defined at stm32_rcc.c:153

        stm32_rcc.c #includes stm32f10xxx_rcc.c; the function's first line
        row is rcc_reset() inlined from that file at line 82, so the
        line comes from the DIE (v1.2.17 gave stm32_rcc.c:243).
        """
        self.assert_source('nuttx-nucleo-f103rb', {
            'stm32_clockconfig': ('stm32_rcc.c', 153),
        })

    def test_no_line_from_another_file(self):
        """No line when neither the first row nor the DIE is in the file

        sched_lock is defined in sched_lock.c, its first row is irq.h:418
        (inlined) and its DIE gives the prototype in sched.h:270.
        SystemInit's code is in system_nrf52.c, #included by the reported
        system_nrf52840.c.
        """
        self.assert_source('nuttx-nucleo-f103rb', {'sched_lock': ('sched_lock.c', 0)})
        self.assert_source('tinyusb-feather_nrf52840_express', {
            'SystemInit': ('system_nrf52840.c', 0)})

    def test_no_line_without_a_file(self):
        """Labels whose file is not found get no line either"""
        self.assert_source('meshtastic-picow', {'__default_isrs_start': ('', 0)})
        self.assert_source('tinyusb-stm32f407disco', {'Default_Handler': ('', 0)})


class TestDataWithoutDebugInfo(ProjectTestCase):
    """Meshtastic's own C++ is built without -g: its variables have no DIEs
    and get no source file, not that of a neighbour or a namesake."""

    TARGET = 'meshtastic-picow'

    def test_no_file_from_a_neighbouring_variable(self):
        """rtc_found (main.cpp) is 1 byte after rng_initialised (rand.c):
        the Thumb bit tolerance is for code only."""
        self.assert_source(self.TARGET, {
            'rng_initialised': ('rand.c', 43),
            'rtc_found': ('', 0),
            'kb_found': ('', 0),
            'cannedMessageModuleConfig': ('', 0),
            'channels': ('', 0),
        })

    def test_no_file_from_a_namesake(self):
        """Locals, extern declarations and C++ members of the same name"""
        self.assert_source(self.TARGET, {
            'owner': ('', 0),               # a local in mutex.c
            'bytes': ('', 0),               # a local in _mallocr.c
            '__lock___tz_mutex': ('', 0),   # extern declaration in tzlock.c
            'end': ('', 0),                 # std::string::end in string-inst.cc
        })

    def test_weak_stub_still_found_by_name(self):
        """A defining DIE without an address still names its function"""
        self.assert_source('tinyusb-stm32f407disco', {
            'tud_cdc_tx_complete_cb': ('cdc_device.c', 72)})

    def test_decl_line_without_line_rows(self):
        """Symbols without line rows take the line of their DW_AT_decl_line

        Data objects and weak stubs the line program does not cover. The
        stubs' DIEs have no address and are matched by name.
        """
        self.assert_source('tinyusb-stm32f407disco', {
            'desc_device': ('usb_descriptors.c', 38),
            'tud_cdc_tx_complete_cb': ('cdc_device.c', 72),
            'tud_cdc_notify_complete_cb': ('cdc_device.c', 76),
            'tud_descriptor_device_qualifier_cb': ('usbd.c', 41),
        })
        self.assert_source('nuttx-nucleo-f103rb', {
            'g_uart_ops': ('stm32_serial_m3m4_v1v2v3v4.c', 559),
            'g_uart_devs': ('stm32_serial_m3m4_v1v2v3v4.c', 1355),
        })


if __name__ == '__main__':
    unittest.main()
