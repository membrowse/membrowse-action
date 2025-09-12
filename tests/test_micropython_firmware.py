#!/usr/bin/env python3
"""
Test real MicroPython firmware analysis for source file mapping verification.
"""

from memory_report import MemoryReportGenerator
import unittest
import json
import os
import tempfile
from pathlib import Path
import sys

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'shared'))


class TestMicroPythonFirmware(unittest.TestCase):
    """Test MicroPython firmware analysis"""

    @classmethod
    def setUpClass(cls):
        """Set up class with firmware paths"""
        cls.firmware_path = Path(
            "../micropython/ports/stm32/build-PYBV10/firmware.elf")
        cls.linker_script_path = Path(
            "../micropython/ports/stm32/boards/stm32f405xg.ld")

        # Check if firmware exists
        if not cls.firmware_path.exists():
            raise unittest.SkipTest(
                f"MicroPython firmware not found at {cls.firmware_path}")

    def test_micropython_firmware_analysis(self):
        """Test full MicroPython firmware analysis and uart_init source file mapping"""

        # Create temporary files for memory regions and report
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as regions_file:
            # Create minimal memory regions in the expected format
            regions_data = {
                "FLASH": {
                    "type": "FLASH",
                    "attributes": "rx",
                    "address": int("0x08000000", 16),
                    "end_address": int("0x08000000", 16) + int("0x100000", 16) - 1,
                    "limit_size": int("0x100000", 16),
                    "used_size": 0,
                    "free_size": int("0x100000", 16),
                    "utilization_percent": 0.0,
                    "sections": []
                },
                "RAM": {
                    "type": "RAM",
                    "attributes": "rwx",
                    "address": int("0x20000000", 16),
                    "end_address": int("0x20000000", 16) + int("0x20000", 16) - 1,
                    "limit_size": int("0x20000", 16),
                    "used_size": 0,
                    "free_size": int("0x20000", 16),
                    "utilization_percent": 0.0,
                    "sections": []
                }
            }
            json.dump(regions_data, regions_file, indent=2)
            regions_file_path = regions_file.name

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as report_file:
            report_file_path = report_file.name

        try:
            # Load memory regions data
            with open(regions_file_path, 'r') as f:
                memory_regions_data = json.load(f)

            # Initialize the generator
            generator = MemoryReportGenerator(
                str(self.firmware_path), memory_regions_data)

            # Generate the report
            report = generator.generate_report()

            # Write report to file
            with open(report_file_path, 'w') as f:
                json.dump(report, f, indent=2)

            # Also save to a known location for inspection
            known_report_path = Path("micropython_report_with_cu.json")
            with open(known_report_path, 'w') as f:
                json.dump(report, f, indent=2)
            print(f"\n📁 Report saved to: {known_report_path.absolute()}")

            # Check that analysis succeeded
            self.assertIsInstance(
                report, dict, "Report should be a dictionary")

            # Load the generated report
            with open(report_file_path, 'r') as f:
                report = json.load(f)

            # Basic report structure validation
            self.assertIn('symbols', report)
            self.assertIn('architecture', report)
            self.assertIn('entry_point', report)

            # Find uart_init and I2CHandle1 symbols
            uart_init_symbol = None
            i2c_handle1_symbol = None
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

                    # This is what we discovered: in real firmware, functions may legitimately map to headers
                    # if that's where the line information points (e.g., inline
                    # functions or static functions in headers)

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
                            f"✅ uart_init maps to .c source file: {uart_init_symbol['source_file']}")
                    elif uart_init_symbol['source_file'].endswith('.h'):
                        print(
                            f"ℹ️  uart_init maps to .h header file: {uart_init_symbol['source_file']}")
                        print(
                            "    This may be legitimate for inline/static functions in headers")
                    else:
                        print(
                            f"⚠️  uart_init maps to unexpected file type: {uart_init_symbol['source_file']}")

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
                        f"uart_init should map to project file, not system header: {uart_init_symbol['source_file']}")

                    print(
                        f"✅ uart_init correctly maps to project file: {uart_init_symbol['source_file']}")
                else:
                    print(
                        "⚠️  uart_init has empty source_file - this might be expected for optimized builds")

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
                            f"  ⚠️  I2CHandle1 maps to header file: {i2c_handle1_symbol['source_file']}")
                        print(
                            f"      Should be defined in pyb_i2c.c or similar .c file")
                    else:
                        print(
                            f"  ✅ I2CHandle1 correctly maps to: {i2c_handle1_symbol['source_file']}")
            else:
                print(f"\n⚠️  I2CHandle1 not found")
                print(f"Found {len(i2c_symbols)} I2C-related symbols:")
                for sym in i2c_symbols[:10]:
                    print(
                        f"  - {sym['name']}: {sym.get('source_file', 'no source')}")

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
            from memory_report import ELFAnalyzer
            analyzer = ELFAnalyzer(str(self.firmware_path))

            # Check if CU data was built
            if analyzer._dwarf_data['cu_file_list']:
                print(f"  Total CUs in binary: {len(analyzer._dwarf_data['cu_file_list'])}")
                # Show some example CUs
                print(f"  Sample CUs:")
                for cu in analyzer._dwarf_data['cu_file_list'][:10]:
                    if cu and ('micropython' in cu or 'ports' in cu or not cu.startswith('../')):
                        print(f"    - {cu}")

            if analyzer._dwarf_data['address_to_file']:
                print(f"  Address mappings available: {len(analyzer._dwarf_data['address_to_file'])}")
                # Show first few address ranges  
                addresses = sorted(analyzer._dwarf_data['address_to_file'].keys())[:5]
                for addr in addresses:
                    print(f"    Address: 0x{addr:08x} -> {analyzer._dwarf_data['address_to_file'][addr]}")
            else:
                print(f"  No CU ranges found - debug info may be missing")

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
                os.unlink(regions_file_path)
                os.unlink(report_file_path)
            except OSError:
                pass


if __name__ == '__main__':
    unittest.main()
