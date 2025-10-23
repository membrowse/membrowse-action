#!/usr/bin/env python3

"""
Generate a complete memory report for a MicroPython STM32 target.

This script:
1. Loads STM32 configurations from the linker metadata
2. Parses the linker scripts for a specific STM32 target
3. Generates a memory layout report showing regions and their usage
"""

import json
import sys
from pathlib import Path

from membrowse.linker.parser import parse_linker_scripts
from tests.test_utils import validate_memory_regions

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'shared'))


def generate_stm32_report(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        target_name='NUCLEO_F401RE_basic',
        output_file='stm32_memory_report.json'):
    """Generate memory report for specified STM32 target"""

    # Load metadata
    metadata_file = Path("../../micropython/linker_metadata.json")
    if not metadata_file.exists():
        print(f"ERROR: Metadata file not found: {metadata_file}")
        return False

    with open(metadata_file, 'r', encoding='utf-8') as f:
        metadata = json.load(f)

    # Get STM32 configurations
    stm32_configs = metadata.get('stm32', {})
    if target_name not in stm32_configs:
        print(f"ERROR: Target {target_name} not found in STM32 configurations")
        print(f"Available targets: {list(stm32_configs.keys())[:10]}...")
        return False

    config_data = stm32_configs[target_name]
    script_paths = config_data.get('linker_scripts', [])
    expected_regions = config_data.get('memory_regions', {})

    print(f"=== Generating Memory Report for {target_name} ===")
    print(f"Linker scripts: {script_paths}")
    print(f"Expected memory regions: {len(expected_regions)}")

    if not script_paths:
        print("ERROR: No linker scripts found for this target")
        return False

    # Check if linker scripts exist
    micropython_root = Path("../../micropython")
    valid_scripts = []
    for script_path in script_paths:
        full_path = micropython_root / script_path
        if full_path.exists():
            valid_scripts.append(str(full_path))
        else:
            print(f"WARNING: Linker script not found: {full_path}")

    if not valid_scripts:
        print("ERROR: No valid linker scripts found")
        return False

    print(f"Valid linker scripts: {len(valid_scripts)}")

    # Parse linker scripts
    try:
        print("Parsing linker scripts...")
        parsed_regions = parse_linker_scripts(valid_scripts)
        print(f"Successfully parsed {len(parsed_regions)} memory regions")

        # Validate regions
        validation_result = validate_memory_regions(parsed_regions)
        if isinstance(validation_result, dict):
            if validation_result.get('valid', False):
                print("✅ Memory regions validation passed")
            else:
                print("⚠️  Memory regions validation warnings:")
                for warning in validation_result.get('warnings', []):
                    print(f"  - {warning}")
        else:
            # Handle simple boolean result
            if validation_result:
                print("✅ Memory regions validation passed")
            else:
                print("⚠️  Memory regions validation failed")
            validation_result = {
                'valid': bool(validation_result),
                'warnings': []}

        # Create report
        report = {
            'target': target_name,
            'linker_scripts': valid_scripts,
            'memory_regions': parsed_regions,
            'expected_regions': expected_regions,
            'validation': validation_result,
            'statistics': {
                'total_regions': len(parsed_regions),
                'flash_regions': len([
                    r for r in parsed_regions.values()
                    if r.get('type', '').upper() in ['FLASH', 'ROM']
                ]),
                'ram_regions': len([
                    r for r in parsed_regions.values()
                    if r.get('type', '').upper() == 'RAM'
                ]),
                'total_flash_size': sum(
                    r.get('limit_size', 0) for r in parsed_regions.values()
                    if r.get('type', '').upper() in ['FLASH', 'ROM']
                ),
                'total_ram_size': sum(
                    r.get('limit_size', 0) for r in parsed_regions.values()
                    if r.get('type', '').upper() == 'RAM'
                )
            }
        }

        # Save report
        output_path = Path(output_file)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)

        print(f"✅ Memory report saved to: {output_path}")

        # Print summary
        stats = report['statistics']
        print("\n=== Memory Summary ===")
        print(f"Total regions: {stats['total_regions']}")
        print(
            f"FLASH regions: {stats['flash_regions']} "
            f"({stats['total_flash_size']:,} bytes)")
        print(
            f"RAM regions: {stats['ram_regions']} "
            f"({stats['total_ram_size']:,} bytes)")

        # Show region details
        print("\n=== Memory Regions ===")
        for name, region in parsed_regions.items():
            addr = region.get('address', 0)
            size = region.get('limit_size', 0)
            region_type = region.get('type', 'UNKNOWN')
            print(
                f"{name:20} {region_type:8} 0x{addr:08x} - "
                f"0x{addr+size-1:08x} ({size:8,} bytes)")

        return True

    except (OSError, IOError, json.JSONDecodeError) as e:
        print(f"ERROR: Failed to parse linker scripts: {e}")
        return False


if __name__ == '__main__':
    # Allow specifying target on command line
    target = sys.argv[1] if len(sys.argv) > 1 else 'NUCLEO_F401RE_basic'
    output = sys.argv[2] if len(sys.argv) > 2 else 'stm32_memory_report.json'

    result = generate_stm32_report(
        target, output)  # pylint: disable=invalid-name
    sys.exit(0 if result else 1)
