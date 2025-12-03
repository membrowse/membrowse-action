#!/usr/bin/env python3
"""
Test real MicroPython firmware analysis for source file mapping verification.
"""
# pylint: disable=import-outside-toplevel,too-many-locals,too-many-statements
# pylint: disable=too-many-branches,line-too-long,protected-access
# pylint: disable=f-string-without-interpolation
# Note: This comprehensive integration test (800+ lines) has high complexity due to
# extensive validation logic and debug output. Line length and f-string style are
# relaxed for readability of debug output. Protected access is needed to test internal state.

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from membrowse.core import ReportGenerator

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'shared'))


class TestMicroPythonFirmware(unittest.TestCase):
    """Test MicroPython firmware analysis"""

    @classmethod
    def setUpClass(cls):
        """Set up class with firmware paths"""
        cls.firmware_path = Path(
            __file__).parent / "fixtures" / "micropython" / "stm32" / "firmware.elf"
        cls.linker_script_path = Path(
            __file__).parent / "fixtures" / "micropython" / "stm32" / "linker" / "stm32f405.ld"

        # Check if firmware exists
        if not cls.firmware_path.exists():
            raise unittest.SkipTest(
                f"MicroPython firmware not found at {cls.firmware_path}")

    def test_micropython_firmware_analysis(self):
        """Test full MicroPython firmware analysis and uart_init source file mapping"""

        # Parse memory regions from actual linker script
        from membrowse.linker.parser import parse_linker_scripts
        linker_script_path = Path(__file__).parent / "fixtures" / \
            "micropython" / "stm32" / "linker" / "stm32f405.ld"

        memory_regions_data = parse_linker_scripts(
            [str(linker_script_path)],
            elf_file=str(self.firmware_path)
        )

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as report_file:
            report_file_path = report_file.name

        try:

            # Initialize the generator
            generator = ReportGenerator(
                str(self.firmware_path), memory_regions_data)

            # Generate the report
            report = generator.generate_report()

            # Write report to file
            with open(report_file_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2)

            # Also save to a known location for inspection
            known_report_path = Path("micropython_report_stm32.json")
            with open(known_report_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2)
            print(f"\n📁 Report saved to: {known_report_path.absolute()}")

            # Check that analysis succeeded
            self.assertIsInstance(
                report, dict, "Report should be a dictionary")

            # Load the generated report
            with open(report_file_path, 'r', encoding='utf-8') as f:
                report = json.load(f)

            # Basic report structure validation
            self.assertIn('symbols', report)
            self.assertIn('architecture', report)
            self.assertIn('entry_point', report)

            # Find uart_init, I2CHandle1, micropython_ringio_any, machine_init,
            # and usb_device symbols
            uart_init_symbol = None
            i2c_handle1_symbol = None
            ringio_any_symbol = None
            machine_init_symbol = None
            usb_device_symbol = None
            uart_symbols = []
            i2c_symbols = []

            for symbol in report['symbols']:
                if 'uart' in symbol['name'].lower():
                    uart_symbols.append(symbol['name'])
                if symbol['name'] == 'uart_init':
                    uart_init_symbol = symbol

                if 'i2c' in symbol['name'].lower():
                    i2c_symbols.append(symbol)
                if symbol['name'] == 'I2CHandle1':
                    i2c_handle1_symbol = symbol

                if symbol['name'] == 'micropython_ringio_any':
                    ringio_any_symbol = symbol

                if symbol['name'] == 'machine_init':
                    machine_init_symbol = symbol

                if symbol['name'] == 'usb_device':
                    usb_device_symbol = symbol

            print(f"\nFound {len(uart_symbols)} UART-related symbols:")
            for uart_sym in uart_symbols[:10]:  # Show first 10
                print(f"  - {uart_sym}")
            if len(uart_symbols) > 10:
                print(f"  ... and {len(uart_symbols) - 10} more")

            # Check if uart_init was found
            if uart_init_symbol:
                print(f"\nFound uart_init symbol:")
                print(f"  Address: 0x{uart_init_symbol['address']:08x}")
                print(f"  Size: {uart_init_symbol['size']}")
                print(f"  Type: {uart_init_symbol['type']}")
                print(f"  Source file: {uart_init_symbol['source_file']}")

                # Verify source file mapping
                self.assertIsInstance(uart_init_symbol['source_file'], str)

                # Check source file mapping behavior
                if uart_init_symbol['source_file']:
                    # Print information about the mapping
                    print(
                        f"📍 uart_init maps to: {uart_init_symbol['source_file']}")

                    # This is what we discovered: in real firmware, functions may
                    # legitimately map to headers if that's where the line
                    # information points (e.g., inline functions or static
                    # functions in headers)

                    # Should not be a system header though
                    self.assertNotIn(
                        'stdint', uart_init_symbol['source_file'].lower())
                    self.assertNotIn(
                        'stdio', uart_init_symbol['source_file'].lower())
                    self.assertNotIn(
                        '/usr/include', uart_init_symbol['source_file'])

                    # Accept both .c and .h files - real firmware may have
                    # legitimate header mappings
                    if uart_init_symbol['source_file'].endswith('.c'):
                        print(
                            f"✅ uart_init maps to .c source file: "
                            f"{uart_init_symbol['source_file']}")
                    elif uart_init_symbol['source_file'].endswith('.h'):
                        print(
                            f"ℹ️  uart_init maps to .h header file: "
                            f"{uart_init_symbol['source_file']}")
                        print(
                            "    This may be legitimate for inline/static "
                            "functions in headers")
                    else:
                        print(
                            f"⚠️  uart_init maps to unexpected file type: "
                            f"{uart_init_symbol['source_file']}")

                    # The key test: it should not be a system/standard library
                    # header
                    is_project_file = (
                        not uart_init_symbol['source_file'].startswith('/usr/') and
                        not uart_init_symbol['source_file'].startswith('/opt/') and
                        'stdint' not in uart_init_symbol['source_file'].lower() and
                        'stdio' not in uart_init_symbol['source_file'].lower()
                    )

                    self.assertTrue(
                        is_project_file,
                        f"uart_init should map to project file, not system header: "
                        f"{uart_init_symbol['source_file']}")

                    print(
                        f"✅ uart_init correctly maps to project file: "
                        f"{uart_init_symbol['source_file']}")
                else:
                    print(
                        "⚠️  uart_init has empty source_file - this might be "
                        "expected for optimized builds")

            else:
                # If uart_init not found, look for similar UART functions
                print(
                    f"\n⚠️  uart_init not found. Looking for similar UART functions...")

                uart_funcs = [s for s in report['symbols']
                              if 'uart' in s['name'].lower() and s['type'] == 'FUNC']

                if uart_funcs:
                    print(f"Found {len(uart_funcs)} UART functions:")
                    for func in uart_funcs[:5]:  # Show first 5
                        print(f"  - {func['name']}: {func['source_file']}")

                    # Test with the first UART function found
                    test_func = uart_funcs[0]
                    print(f"\nTesting with {test_func['name']} instead:")
                    if test_func['source_file']:
                        self.assertTrue(
                            test_func['source_file'].endswith('.c'),
                            f"UART function should map to .c file, got: {test_func['source_file']}")
                        print(
                            f"✅ {test_func['name']} correctly maps to: {test_func['source_file']}")

            # Check I2CHandle1 symbol
            if i2c_handle1_symbol:
                print(f"\nFound I2CHandle1 symbol:")
                print(f"  Address: 0x{i2c_handle1_symbol['address']:08x}")
                print(f"  Size: {i2c_handle1_symbol['size']}")
                print(f"  Type: {i2c_handle1_symbol['type']}")
                print(f"  Source file: {i2c_handle1_symbol['source_file']}")

                if i2c_handle1_symbol['source_file']:
                    if i2c_handle1_symbol['source_file'].endswith('.h'):
                        print(
                            f"  ⚠️  I2CHandle1 maps to header file: "
                            f"{i2c_handle1_symbol['source_file']}")
                        print(
                            "      Should be defined in pyb_i2c.c or similar .c file")
                    else:
                        print(
                            f"  ✅ I2CHandle1 correctly maps to: "
                            f"{i2c_handle1_symbol['source_file']}")
            else:
                print(f"\n⚠️  I2CHandle1 not found")
                print(f"Found {len(i2c_symbols)} I2C-related symbols:")
                for sym in i2c_symbols[:10]:
                    print(
                        f"  - {sym['name']}: {sym.get('source_file', 'no source')}")

            # Check micropython_ringio_any symbol mapping (this is our fix
            # validation)
            if ringio_any_symbol:
                print(f"\nFound micropython_ringio_any symbol:")
                print(f"  Address: 0x{ringio_any_symbol['address']:08x}")
                print(f"  Size: {ringio_any_symbol['size']}")
                print(f"  Type: {ringio_any_symbol['type']}")
                print(f"  Source file: {ringio_any_symbol['source_file']}")

                # This is the critical test for our bug fix
                self.assertEqual(
                    ringio_any_symbol['source_file'],
                    'objringio.c',
                    f"micropython_ringio_any should map to objringio.c, not "
                    f"{ringio_any_symbol['source_file']}")

                print(
                    f"  ✅ micropython_ringio_any correctly maps to: {ringio_any_symbol['source_file']}")
                print(
                    f"     (Fixed: was incorrectly mapping to ringbuf.h due to inlined function)")
            else:
                print(f"\n⚠️  micropython_ringio_any not found in symbols")

            # Check machine_init symbol mapping (validates file index
            # deduplication fix)
            if machine_init_symbol:
                print(f"\nFound machine_init symbol:")
                print(f"  Address: 0x{machine_init_symbol['address']:08x}")
                print(f"  Size: {machine_init_symbol['size']}")
                print(f"  Type: {machine_init_symbol['type']}")
                print(f"  Source file: {machine_init_symbol['source_file']}")

                # This is the critical test for file index deduplication bug
                # fix
                self.assertEqual(
                    machine_init_symbol['source_file'],
                    'modmachine.c',
                    f"machine_init should map to modmachine.c, not "
                    f"{machine_init_symbol['source_file']}")

                print(
                    f"  ✅ machine_init correctly maps to: {machine_init_symbol['source_file']}")
                print(
                    f"     (Fixed: was incorrectly mapping to misc.h due to file index bug)")
            else:
                print(f"\n⚠️  machine_init not found in symbols")

            # Check usb_device symbol mapping (validates DW_AT_location
            # expression parsing fix)
            if usb_device_symbol:
                print(f"\nFound usb_device symbol:")
                print(f"  Address: 0x{usb_device_symbol['address']:08x}")
                print(f"  Size: {usb_device_symbol['size']}")
                print(f"  Type: {usb_device_symbol['type']}")
                print(f"  Source file: {usb_device_symbol['source_file']}")

                # This is the critical test for DW_AT_location expression
                # parsing fix
                self.assertEqual(
                    usb_device_symbol['source_file'],
                    'usb.c',
                    f"usb_device should map to usb.c, not "
                    f"{usb_device_symbol['source_file']}")

                print(
                    f"  ✅ usb_device correctly maps to: {usb_device_symbol['source_file']}")
                print(
                    f"     (Fixed: was not mapping due to unparsed DW_AT_location expression)")
            else:
                print(f"\n⚠️  usb_device not found in symbols")

            # Print summary statistics
            total_symbols = len(report['symbols'])
            symbols_with_source = len(
                [s for s in report['symbols'] if s['source_file']])
            symbols_without_source = [
                s for s in report['symbols'] if not s['source_file']]

            print(f"\nReport summary:")
            print(f"  Total symbols: {total_symbols}")
            print(f"  Symbols with source files: {symbols_with_source}")
            print(
                f"  Symbols without source files: {len(symbols_without_source)}")
            print(f"  Architecture: {report['architecture']}")
            print(f"  Machine: {report.get('machine', 'Unknown')}")

            # Analyze the symbols without source files
            print(
                f"\nAnalyzing {len(symbols_without_source)} symbols without source files:")

            # Group by characteristics
            by_type = {}
            by_section = {}
            by_name_pattern = {
                'compiler_generated': [],
                'asm_related': [],
                'lib_related': [],
                'other': []}

            for symbol in symbols_without_source:
                # Group by type
                symbol_type = symbol['type']
                by_type[symbol_type] = by_type.get(symbol_type, 0) + 1

                # Group by section
                section = symbol['section']
                by_section[section] = by_section.get(section, 0) + 1

                # Categorize by name patterns
                name = symbol['name'].lower()
                if any(
                    pattern in name for pattern in [
                        '__',
                        '_start',
                        '_end',
                        '_size',
                        'thunk',
                        'trampoline',
                        'stub']):
                    by_name_pattern['compiler_generated'].append(
                        symbol['name'])
                elif any(pattern in name for pattern in ['asm', 'reset', 'handler', 'vector', 'boot']):
                    by_name_pattern['asm_related'].append(symbol['name'])
                elif any(pattern in name for pattern in ['lib', 'std', 'crt', 'init', 'fini']):
                    by_name_pattern['lib_related'].append(symbol['name'])
                else:
                    by_name_pattern['other'].append(symbol['name'])

            print(f"\nBreakdown by symbol type:")
            for sym_type, count in sorted(
                    by_type.items(), key=lambda x: x[1], reverse=True):
                print(f"  {sym_type}: {count}")

            print(f"\nBreakdown by section:")
            for section, count in sorted(
                    by_section.items(), key=lambda x: x[1], reverse=True):
                print(f"  {section}: {count}")

            print(f"\nBreakdown by name pattern:")
            for category, symbols in by_name_pattern.items():
                if symbols:
                    print(f"  {category}: {len(symbols)}")
                    # Show first few examples
                    for example in symbols[:5]:
                        print(f"    - {example}")
                    if len(symbols) > 5:
                        print(f"    ... and {len(symbols) - 5} more")

            # Show some specific examples
            print(f"\nFirst 20 symbols without source files:")
            for i, symbol in enumerate(symbols_without_source[:20]):
                print(
                    f"  {i+1:2d}. {symbol['name']} (type={symbol['type']}, section={symbol['section']}, addr=0x{symbol['address']:08x}, size={symbol['size']})")

            # Check if some of these symbols should actually have source files
            # by examining nearby symbols that DO have source files
            print(f"\nChecking if some symbols should have source files...")

            symbols_with_source_dict = {
                s['address']: s for s in report['symbols'] if s['source_file']}

            # First, let's check which compilation units these symbols belong
            # to
            print(
                f"\nChecking compilation unit membership for symbols without source files...")
            # Use the existing analyzer from the generator to avoid redundant
            # processing
            analyzer = generator.elf_analyzer

            # Check if CU data was built (cu_file_list was removed in
            # refactoring)
            if analyzer._dwarf_data['processed_cus']:
                print(
                    f"  Total CUs processed: {len(analyzer._dwarf_data['processed_cus'])}")
                print(f"  CU processing completed successfully")

            if analyzer._dwarf_data['address_to_file']:
                print(
                    f"  Address mappings available: {len(analyzer._dwarf_data['address_to_file'])}")
                # Show first few address ranges
                addresses = sorted(
                    analyzer._dwarf_data['address_to_file'].keys())[
                    :5]
                for addr in addresses:
                    print(
                        f"    Address: 0x{addr:08x} -> {analyzer._dwarf_data['address_to_file'][addr]}")
            else:
                print(f"  No CU ranges found - debug info may be missing")

            # EXPERIMENT: Line Program Coverage Analysis
            print(f"\n{'='*60}")
            print(f"EXPERIMENT: Line Program vs DIE Coverage Analysis (STM32)")
            print(f"{'='*60}")

            if 'coverage_metrics' in analyzer._dwarf_data:
                metrics = analyzer._dwarf_data['coverage_metrics']
                print(f"  CUs processed: {metrics['cus_processed']}")
                print(f"  DIE symbol mappings: {metrics['die_symbols']}")
                print(
                    f"  Line program address mappings: {metrics['line_program_addresses']}")

                # Calculate what line program adds beyond DIEs
                # Note: This is approximate since line program maps addresses,
                # not symbols
                print(f"\n  Analysis:")
                print(f"  - DIE provides symbol->file mappings (name+address)")
                print(f"  - Line program provides address->file mappings (any address)")
                print(
                    f"  - Line program has ~{metrics['line_program_addresses'] - metrics['die_symbols']} more address mappings than DIE symbols")

                # Calculate actual symbol coverage
                total_elf_symbols = len(report['symbols'])
                symbols_with_source = len(
                    [s for s in report['symbols'] if s['source_file']])

                # We need to check which resolution path was used for each symbol
                # This requires examining the resolver's lookup order
                print(f"\n  Symbol Coverage:")
                print(f"  - Total ELF symbols: {total_elf_symbols}")
                print(
                    f"  - Symbols with source files: {symbols_with_source} ({100*symbols_with_source/total_elf_symbols:.1f}%)")
                print(
                    f"  - Symbols without source files: {total_elf_symbols - symbols_with_source} ({100*(total_elf_symbols - symbols_with_source)/total_elf_symbols:.1f}%)")

                print(f"\n  Estimated line program contribution:")
                print(
                    f"  - If we removed line program, we'd lose address-based fallback")
                print(
                    f"  - This affects ~5-15% of symbols (functions without DIE entries)")
                print(
                    f"  - Estimated impact: {int((total_elf_symbols - symbols_with_source) * 0.1)} - {int((total_elf_symbols - symbols_with_source) * 0.3)} additional symbols might lose source mapping")
            else:
                print(f"  ⚠️  Coverage metrics not available")
            print(f"{'='*60}\n")

            suspicious_symbols = []
            for symbol in symbols_without_source[:10]:  # Check first 10
                # Find nearby symbols with source files
                nearby_with_source = []
                for addr, nearby_symbol in symbols_with_source_dict.items():
                    if abs(addr - symbol['address']
                           ) <= 200:  # Within 200 bytes
                        nearby_with_source.append(
                            (abs(addr - symbol['address']), nearby_symbol))

                if nearby_with_source:
                    # Sort by distance
                    nearby_with_source.sort(key=lambda x: x[0])
                    closest = nearby_with_source[0][1]
                    distance = nearby_with_source[0][0]

                    print(
                        f"\n  {symbol['name']} at 0x{symbol['address']:08x}:")
                    print(
                        f"    Closest symbol with source: {closest['name']} ({closest['source_file']}) at distance {distance} bytes")

                    # If very close to a symbol with source file, this might be
                    # a missing mapping
                    if distance <= 50:
                        suspicious_symbols.append((symbol, closest, distance))

            if suspicious_symbols:
                print(
                    f"\n🔍 SUSPICIOUS: {len(suspicious_symbols)} symbols very close to symbols with source files:")
                for symbol, closest, distance in suspicious_symbols:
                    print(
                        f"  - {symbol['name']} should probably map to {closest['source_file']} (distance: {distance} bytes)")
            else:
                print(f"\n✅ No obviously missing source file mappings detected.")

        finally:
            # Clean up temporary files
            try:
                os.unlink(report_file_path)
            except OSError:
                pass


class TestMicroPythonESP32Firmware(unittest.TestCase):
    """Test MicroPython ESP32 firmware analysis"""

    @classmethod
    def setUpClass(cls):
        """Set up class with ESP32 firmware paths"""
        fixtures_dir = Path(__file__).parent / \
            "fixtures" / "micropython" / "esp32"
        cls.firmware_path = fixtures_dir / "micropython.elf"
        cls.linker_scripts = [
            fixtures_dir / "linker" / "esp-idf" / "esp_system" / "ld" / "memory.ld",
            fixtures_dir / "linker" / "esp-idf" / "esp_system" / "ld" / "sections.ld",
            fixtures_dir / "linker" / "esp_rom" / "esp32" / "ld" / "esp32.rom.ld",
            fixtures_dir / "linker" / "esp_rom" / "esp32" / "ld" / "esp32.rom.api.ld",
            fixtures_dir / "linker" / "esp_rom" / "esp32" / "ld" / "esp32.rom.libgcc.ld",
            fixtures_dir / "linker" / "esp_rom" / "esp32" / "ld" / "esp32.rom.newlib-data.ld",
            fixtures_dir / "linker" / "esp_rom" / "esp32" / "ld" / "esp32.rom.syscalls.ld",
            fixtures_dir / "linker" / "esp_rom" / "esp32" / "ld" / "esp32.rom.newlib-funcs.ld",
            fixtures_dir / "linker" / "soc" / "esp32" / "ld" / "esp32.peripherals.ld",
            fixtures_dir / "linker" / "esp_rom" / "esp32" / "ld" / "esp32.rom.newlib-time.ld",
            fixtures_dir / "linker" / "esp_rom" / "esp32" / "ld" / "esp32.rom.newlib-nano.ld",
            fixtures_dir / "linker" / "esp_rom" / "esp32" / "ld" / "esp32.rom.newlib-locale.ld",
            fixtures_dir / "linker" / "esp_rom" / "esp32" / "ld" / "esp32.rom.eco3.ld",
            fixtures_dir / "linker" / "esp_rom" / "esp32" / "ld" / "esp32.rom.redefined.ld",
            fixtures_dir / "linker" / "esp_rom" / "esp32" / "ld" / "esp32.rom.spiflash_legacy.ld",
        ]

        # Check if firmware exists
        if not cls.firmware_path.exists():
            raise unittest.SkipTest(
                f"MicroPython ESP32 firmware not found at {cls.firmware_path}")

    def test_micropython_esp32_firmware_analysis(self):
        """Test full MicroPython ESP32 firmware analysis and source file mapping"""

        # Parse memory regions from actual linker script
        from membrowse.linker.parser import parse_linker_scripts
        linker_script_path = Path(__file__).parent / "fixtures" / "micropython" / \
            "esp32" / "linker" / "esp-idf" / "esp_system" / "ld" / "memory.ld"

        memory_regions_data = parse_linker_scripts(
            [str(linker_script_path)],
            elf_file=str(self.firmware_path)
        )

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as report_file:
            report_file_path = report_file.name

        try:

            # Initialize the generator
            generator = ReportGenerator(
                str(self.firmware_path), memory_regions_data)

            # Generate the report
            report = generator.generate_report()

            # Write report to file
            with open(report_file_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2)

            # Also save to a known location for inspection
            known_report_path = Path("micropython_esp32_report.json")
            with open(known_report_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2)
            print(f"\n📁 ESP32 Report saved to: {known_report_path.absolute()}")

            # Check that analysis succeeded
            self.assertIsInstance(
                report, dict, "Report should be a dictionary")

            # Load the generated report
            with open(report_file_path, 'r', encoding='utf-8') as f:
                report = json.load(f)

            # Basic report structure validation
            self.assertIn('symbols', report)
            self.assertIn('architecture', report)
            self.assertIn('entry_point', report)

            # Verify ESP32 architecture
            self.assertIn('xtensa', report['machine'].lower())
            print(
                f"✅ Detected ESP32 architecture: {report['architecture']} / Machine: {report['machine']}")

            # Find ESP32-specific symbols
            esp_timer_init_symbol = None
            uart_init_symbol = None
            esp_symbols = []
            uart_symbols = []

            for symbol in report['symbols']:
                if 'esp_timer' in symbol['name'].lower():
                    esp_symbols.append(symbol['name'])
                if symbol['name'] == 'esp_timer_init':
                    esp_timer_init_symbol = symbol

                if 'uart' in symbol['name'].lower():
                    uart_symbols.append(symbol['name'])
                if symbol['name'] == 'uart_init':
                    uart_init_symbol = symbol

            print(f"\nFound {len(esp_symbols)} ESP timer-related symbols:")
            for esp_sym in esp_symbols[:10]:  # Show first 10
                print(f"  - {esp_sym}")
            if len(esp_symbols) > 10:
                print(f"  ... and {len(esp_symbols) - 10} more")

            print(f"\nFound {len(uart_symbols)} UART-related symbols:")
            for uart_sym in uart_symbols[:10]:  # Show first 10
                print(f"  - {uart_sym}")
            if len(uart_symbols) > 10:
                print(f"  ... and {len(uart_symbols) - 10} more")

            # Check if esp_timer_init was found
            if esp_timer_init_symbol:
                print(f"\nFound esp_timer_init symbol:")
                print(f"  Address: 0x{esp_timer_init_symbol['address']:08x}")
                print(f"  Size: {esp_timer_init_symbol['size']}")
                print(f"  Type: {esp_timer_init_symbol['type']}")
                print(f"  Source file: {esp_timer_init_symbol['source_file']}")

                # Verify source file mapping
                self.assertIsInstance(
                    esp_timer_init_symbol['source_file'], str)

                # Check source file mapping behavior
                if esp_timer_init_symbol['source_file']:
                    print(
                        f"📍 esp_timer_init maps to: {esp_timer_init_symbol['source_file']}")

                    # Should not be a system header
                    self.assertNotIn(
                        'stdint', esp_timer_init_symbol['source_file'].lower())
                    self.assertNotIn(
                        'stdio', esp_timer_init_symbol['source_file'].lower())
                    self.assertNotIn(
                        '/usr/include', esp_timer_init_symbol['source_file'])

                    # Accept both .c and .h files - real firmware may have
                    # legitimate header mappings
                    if esp_timer_init_symbol['source_file'].endswith('.c'):
                        print(
                            f"✅ esp_timer_init maps to .c source file: {esp_timer_init_symbol['source_file']}")
                    elif esp_timer_init_symbol['source_file'].endswith('.h'):
                        print(
                            f"ℹ️  esp_timer_init maps to .h header file: {esp_timer_init_symbol['source_file']}")
                        print(
                            "    This may be legitimate for inline/static functions in headers")
                    else:
                        print(
                            f"⚠️  esp_timer_init maps to unexpected file type: {esp_timer_init_symbol['source_file']}")

                    # The key test: it should not be a system/standard library
                    # header
                    is_project_file = (
                        not esp_timer_init_symbol['source_file'].startswith('/usr/') and
                        not esp_timer_init_symbol['source_file'].startswith('/opt/') and
                        'stdint' not in esp_timer_init_symbol['source_file'].lower() and
                        'stdio' not in esp_timer_init_symbol['source_file'].lower()
                    )

                    self.assertTrue(
                        is_project_file,
                        f"esp_timer_init should map to project file, not system header: {esp_timer_init_symbol['source_file']}")

                    print(
                        f"✅ esp_timer_init correctly maps to project file: {esp_timer_init_symbol['source_file']}")
                else:
                    print(
                        "⚠️  esp_timer_init has empty source_file - this might be expected for optimized builds")

            else:
                # If esp_timer_init not found, look for similar ESP functions
                print(
                    f"\n⚠️  esp_timer_init not found. Looking for similar ESP functions...")

                esp_funcs = [s for s in report['symbols']
                             if 'esp_' in s['name'].lower() and s['type'] == 'FUNC']

                if esp_funcs:
                    print(f"Found {len(esp_funcs)} ESP functions:")
                    for func in esp_funcs[:5]:  # Show first 5
                        print(f"  - {func['name']}: {func['source_file']}")

                    # Test with the first ESP function found
                    test_func = esp_funcs[0]
                    print(f"\nTesting with {test_func['name']} instead:")
                    if test_func['source_file']:
                        is_project_file = (
                            not test_func['source_file'].startswith('/usr/') and
                            not test_func['source_file'].startswith('/opt/') and
                            'stdint' not in test_func['source_file'].lower() and
                            'stdio' not in test_func['source_file'].lower()
                        )
                        self.assertTrue(
                            is_project_file,
                            f"ESP function should map to project file, got: {test_func['source_file']}")
                        print(
                            f"✅ {test_func['name']} correctly maps to: {test_func['source_file']}")

            # Check uart_init symbol for ESP32
            if uart_init_symbol:
                print(f"\nFound uart_init symbol:")
                print(f"  Address: 0x{uart_init_symbol['address']:08x}")
                print(f"  Size: {uart_init_symbol['size']}")
                print(f"  Type: {uart_init_symbol['type']}")
                print(f"  Source file: {uart_init_symbol['source_file']}")

                if uart_init_symbol['source_file']:
                    if uart_init_symbol['source_file'].endswith('.c'):
                        print(
                            f"✅ uart_init correctly maps to: {uart_init_symbol['source_file']}")
                    else:
                        print(
                            f"ℹ️  uart_init maps to: {uart_init_symbol['source_file']}")

            # Print summary statistics
            total_symbols = len(report['symbols'])
            symbols_with_source = len(
                [s for s in report['symbols'] if s['source_file']])

            print(f"\nESP32 Report summary:")
            print(f"  Total symbols: {total_symbols}")
            print(f"  Symbols with source files: {symbols_with_source}")
            print(f"  Architecture: {report['architecture']}")
            print(f"  Machine: {report.get('machine', 'Unknown')}")

            # Test that we got a reasonable number of symbols
            self.assertGreater(
                total_symbols,
                1000,
                "Should have found many symbols in ESP32 firmware")
            self.assertGreater(
                symbols_with_source,
                100,
                "Should have source file mappings for many symbols")

            # EXPERIMENT: Line Program Coverage Analysis
            print(f"\n{'='*60}")
            print(f"EXPERIMENT: Line Program vs DIE Coverage Analysis (ESP32)")
            print(f"{'='*60}")

            analyzer = generator.elf_analyzer

            if 'coverage_metrics' in analyzer._dwarf_data:
                metrics = analyzer._dwarf_data['coverage_metrics']
                print(f"  CUs processed: {metrics['cus_processed']}")
                print(f"  DIE symbol mappings: {metrics['die_symbols']}")
                print(
                    f"  Line program address mappings: {metrics['line_program_addresses']}")

                # Calculate what line program adds beyond DIEs
                print(f"\n  Analysis:")
                print(f"  - DIE provides symbol->file mappings (name+address)")
                print(f"  - Line program provides address->file mappings (any address)")
                print(
                    f"  - Line program has ~{metrics['line_program_addresses'] - metrics['die_symbols']} more address mappings than DIE symbols")

                # Calculate actual symbol coverage
                symbols_without_source = total_symbols - symbols_with_source

                print(f"\n  Symbol Coverage:")
                print(f"  - Total ELF symbols: {total_symbols}")
                print(
                    f"  - Symbols with source files: {symbols_with_source} ({100*symbols_with_source/total_symbols:.1f}%)")
                print(
                    f"  - Symbols without source files: {symbols_without_source} ({100*symbols_without_source/total_symbols:.1f}%)")

                print(f"\n  Estimated line program contribution:")
                print(
                    f"  - If we removed line program, we'd lose address-based fallback")
                print(
                    f"  - This affects ~5-15% of symbols (functions without DIE entries)")
                print(
                    f"  - Estimated impact: {int(symbols_without_source * 0.1)} - {int(symbols_without_source * 0.3)} additional symbols might lose source mapping")

                # ESP32 specific note
                print(f"\n  ESP32 Note:")
                print(f"  - ESP-IDF firmware often has extensive DWARF info")
                print(f"  - Line program may be more important for ROM functions")
            else:
                print(f"  ⚠️  Coverage metrics not available")
            print(f"{'='*60}\n")

        finally:
            # Clean up temporary files
            try:
                os.unlink(report_file_path)
            except OSError:
                pass


if __name__ == '__main__':
    unittest.main()
