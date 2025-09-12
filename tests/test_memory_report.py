#!/usr/bin/env python3
"""
Test script for memory_report.py
Compiles test firmware and verifies memory analysis output
"""

import json
import subprocess
import sys
from pathlib import Path


def run_command(cmd, cwd=None):
    """Run a command and return output"""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd,
        check=False)
    if result.returncode != 0:
        print(f"Command failed with return code {result.returncode}")
        print(f"STDOUT: {result.stdout}")
        print(f"STDERR: {result.stderr}")
        return None
    return result.stdout


def compile_test_firmware(test_dir):
    """Compile the test firmware"""
    # Check if arm-none-eabi-gcc is available
    gcc_check = subprocess.run(
        ['which', 'arm-none-eabi-gcc'], capture_output=True, check=False)
    if not gcc_check.returncode == 0:
        print("arm-none-eabi-gcc not found, trying gcc")
        gcc_cmd = 'gcc'
        target_flags = ['-m32']  # Use 32-bit for testing
    else:
        gcc_cmd = 'arm-none-eabi-gcc'
        target_flags = ['-mcpu=cortex-m4', '-mthumb']
    # Compile command
    cmd = [
        gcc_cmd,
        '-c',
        '-O2',
        '-g',
        '-Wall',
        *target_flags,
        '-o', str(test_dir / 'test_firmware.o'),
        str(test_dir / 'test_firmware.c')
    ]
    output = run_command(cmd)
    if output is None:
        return False
    # Link command
    cmd = [
        gcc_cmd,
        *target_flags,
        '-nostdlib',
        '-T', str(test_dir / 'test_firmware.ld'),
        '-Wl,-Map,' + str(test_dir / 'test_firmware.map'),
        '-o', str(test_dir / 'test_firmware.elf'),
        str(test_dir / 'test_firmware.o')
    ]
    output = run_command(cmd)
    return output is not None


def run_memory_report(test_dir):
    """Run memory_report.py on the test files"""
    script_dir = Path(__file__).parent.parent / 'shared'
    elf_path = test_dir / 'test_firmware.elf'
    ld_path = test_dir / 'test_firmware.ld'
    regions_path = test_dir / 'memory_regions.json'
    report_path = test_dir / 'memory_report.json'

    # First generate memory regions from linker script
    regions_cmd = [
        'python3',
        str(script_dir / 'memory_regions.py'),
        str(ld_path)
    ]

    regions_output = run_command(regions_cmd)
    if regions_output is None:
        return None

    # Save regions to file
    with open(regions_path, 'w', encoding='utf-8') as f:
        f.write(regions_output)

    # Now run memory report
    cmd = [
        'python3',
        str(script_dir / 'memory_report.py'),
        '--elf-path', str(elf_path),
        '--memory-regions', str(regions_path),
        '--output', str(report_path)
    ]
    output = run_command(cmd)
    if output is None:
        return None
    # Read the generated report
    with open(report_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def verify_memory_report(report):  # pylint: disable=too-many-branches
    """Verify the memory report contains expected content"""
    errors = []
    # Check basic structure
    required_fields = [
        'file_path', 'architecture', 'machine', 'symbols',
        'memory_layout', 'total_sizes'
    ]
    for field in required_fields:
        if field not in report:
            errors.append(f"Missing required field: {field}")
    # Check architecture info
    if 'architecture' in report:
        if not report['architecture'].startswith('ELF'):
            errors.append(f"Invalid architecture: {report['architecture']}")
    # Check symbols
    if 'symbols' in report:
        symbols = report['symbols']
        if not isinstance(symbols, list):
            errors.append("Symbols should be a list")
        else:
            # Check that we have some meaningful symbols
            symbol_names = [s.get('name', '') for s in symbols]
            expected_symbols = [
                'main',
                'init_hardware',
                'process_data',
                'global_data']
            found_symbols = [
                name for name in expected_symbols
                if any(name in sym for sym in symbol_names)
            ]

            if len(found_symbols) == 0:
                errors.append(
                    f"No expected symbols found. Got: {symbol_names[:10]}")

            # Check that debug symbols are filtered out
            debug_symbols = [
                s for s in symbols
                if '[section .debug' in s.get('name', '')
            ]
            if debug_symbols:
                debug_names = [s['name'] for s in debug_symbols[:5]]
                errors.append(
                    f"Debug symbols should be filtered out: {debug_names}")
    # Check memory layout
    if 'memory_layout' in report:
        layout = report['memory_layout']
        if not isinstance(layout, dict):
            errors.append("Memory layout should be a dictionary")
        else:
            # Check for expected memory regions
            expected_regions = ['FLASH', 'RAM']
            found_regions = [
                region for region in expected_regions
                if region in layout
            ]
            if len(found_regions) == 0:
                errors.append(
                    f"No expected memory regions found. Got: {list(layout.keys())}")
    # Check total sizes
    if 'total_sizes' in report:
        sizes = report['total_sizes']
        if not isinstance(sizes, dict):
            errors.append("Total sizes should be a dictionary")
        else:
            # Check for reasonable sizes
            text_size = sizes.get('text_size', 0)
            if text_size == 0:
                errors.append("Text size should be > 0")
    return errors


def main():
    """Main test function"""
    test_dir = Path(__file__).parent
    print("=== Memory Report Test ===")
    print(f"Test directory: {test_dir}")
    # Step 1: Compile test firmware
    print("\n1. Compiling test firmware...")
    if not compile_test_firmware(test_dir):
        print("❌ Failed to compile test firmware")
        return 1
    print("✅ Test firmware compiled successfully")
    # Step 2: Run memory report
    print("\n2. Running memory report...")
    report = run_memory_report(test_dir)
    if report is None:
        print("❌ Failed to generate memory report")
        return 1
    print("✅ Memory report generated successfully")
    # Step 3: Verify report content
    print("\n3. Verifying report content...")
    errors = verify_memory_report(report)
    if errors:
        print("❌ Report verification failed:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("✅ Report verification passed")
    # Print summary
    print("\n=== Test Summary ===")
    print(f"Architecture: {report.get('architecture', 'Unknown')}")
    print(f"Machine: {report.get('machine', 'Unknown')}")
    print(f"Symbols found: {len(report.get('symbols', []))}")
    print(f"Memory regions: {list(report.get('memory_layout', {}).keys())}")
    if 'total_sizes' in report:
        sizes = report['total_sizes']
        print(f"Text size: {sizes.get('text_size', 0)} bytes")
        print(f"Data size: {sizes.get('data_size', 0)} bytes")
        print(f"BSS size: {sizes.get('bss_size', 0)} bytes")
    print("\n🎉 All tests passed!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
