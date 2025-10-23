# MemBrowse

[![PyPI version](https://badge.fury.io/py/membrowse.svg)](https://badge.fury.io/py/membrowse)
[![Python Versions](https://img.shields.io/pypi/pyversions/membrowse.svg)](https://pypi.org/project/membrowse/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Downloads](https://pepy.tech/badge/membrowse)](https://pepy.tech/project/membrowse)

A tool for analyzing memory footprint in embedded firmware. MemBrowse extracts detailed memory information from ELF files and linker scripts, providing symbol-level analysis with source file mapping for any embedded architecture. Use it standalone for local analysis or integrate with [MemBrowse](https://membrowse.com) for historical analysis and CI integration.


## Features

- **Architecture Agnostic**: Works with any embedded architecture by relying on the DWARF debug format
- **Source File Mapping**: Symbols are automatically mapped to their definition source files using DWARF debug information
- **Memory Region Extraction**: Memory region capacity and layout are extracted from GNU LD linker scripts
- **Intelligent Linker Script Parsing**: Handles complex GNU LD syntax with automatic architecture detection and expression evaluation
- **Cloud Integration**: Upload reports to [MemBrowse](https://membrowse.com) for historical tracking

## Installation

### From PyPI (Recommended)

```bash
pip install membrowse
```

### From GitHub

```bash
# Install directly from GitHub
pip install git+https://github.com/membrowse/membrowse-action.git
```

### For Development

```bash
# Clone and install in editable mode
git clone https://github.com/membrowse/membrowse-action.git
cd membrowse-action
pip install -e .
```

### Verify Installation

After installation, the `membrowse` command will be available:

```bash
membrowse --help              # Show main help
membrowse report --help       # Help for report subcommand
membrowse onboard --help      # Help for onboard subcommand
```

## Quick Start

### Analyze Your Firmware Locally

The simplest way to analyze your firmware (local mode - no upload):

```bash
# Generate a memory report (prints JSON to stdout)
membrowse report \
  build/firmware.elf \
  "src/linker.ld src/memory.ld"

# With verbose output to see progress
membrowse report \
  build/firmware.elf \
  "src/linker.ld src/memory.ld" \
  --verbose
```

This generates a JSON report with detailed memory analysis and prints it to stdout. Use `--verbose` to see progress messages.

### Upload Reports to MemBrowse Platform

```bash
# Upload mode - uploads report to MemBrowse platform (https://membrowse.com)
membrowse report \
  build/firmware.elf \
  "src/linker.ld" \
  --upload \
  --target-name esp32 \
  --api-key your-membrowse-api-key
```

### Analyze Historical Commits (Onboarding)

Analyzes memory footprints across multiple commits and uploads them to [MemBrowse](https://membrowse.com):

```bash
# Analyze and upload the last 50 commits
membrowse onboard \
  50 \
  "make clean && make all" \
  build/firmware.elf \
  "STM32F746ZGTx_FLASH.ld" \
  stm32f4 \
  your-membrowse-api-key
```


## CI/CD Integration

### GitHub Actions

MemBrowse provides two composite GitHub Actions for seamless integration.

#### PR/Push Analysis

```yaml
name: Memory Analysis
on: [push, pull_request]

jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Build firmware
        run: make all

      - name: Analyze memory
        uses: membrowse/membrowse-action/pr-action@main
        with:
          elf: build/firmware.elf
          ld: "src/linker.ld"
          target_name: stm32f4
          api_key: ${{ secrets.MEMBROWSE_API_KEY }}
```

#### Historical Onboarding

```yaml
name: Onboard to MemBrowse
on: workflow_dispatch

jobs:
  onboard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
        with:
          fetch-depth: 0

      - name: Historical analysis
        uses: membrowse/membrowse-action/onboard-action@main
        with:
          num_commits: 50
          build_script: "make clean && make"
          elf: build/firmware.elf
          ld: "linker.ld"
          target_name: my-target
          api_key: ${{ secrets.MEMBROWSE_API_KEY }}
```

### Other CI/CD

For other CI systems:

```bash
# Install MemBrowse
pip install membrowse

# Build your firmware
make all

# Analyze and upload memory report
membrowse report \
  build/firmware.elf \
  "linker.ld" \
  --upload \
  --target-name my-target \
  --api-key your-membrowse-api-key
```

## Platform Support

MemBrowse is **platform agnostic** and works with any embedded architecture that produces ELF files and uses GNU LD linker scripts. The tool automatically detects the target architecture and applies appropriate parsing strategies for optimal results.

## Output Format

MemBrowse generates comprehensive JSON reports:

```json
{
  "memory_regions": {
    "FLASH": {
      "address": "0x08000000",
      "size": 524288,
      "used": 245760,
      "utilization": 46.9,
      "sections": [".text", ".rodata"],
      "symbols": [...]
    },
    "RAM": {
      "address": "0x20000000",
      "size": 131072,
      "used": 12345,
      "utilization": 9.4,
      "sections": [".data", ".bss"],
      "symbols": [...]
    }
  },
  "symbols": [
    {
      "name": "main",
      "size": 234,
      "type": "FUNC",
      "address": "0x08001234",
      "source_file": "src/main.c",
      "region": "FLASH"
    }
  ],
  "architecture": "arm",
  "sections": [...],
  "compilation_units": [...]
}
```

## License

See [LICENSE](LICENSE) file for details.

## Support

- **Issues**: https://github.com/membrowse/membrowse-action/issues
- **Documentation**: This README and inline code documentation
- **MemBrowse Support**: support@membrowse.com
