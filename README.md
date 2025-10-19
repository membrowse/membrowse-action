# MemBrowse

A comprehensive Python package for analyzing memory usage in embedded firmware. MemBrowse extracts detailed memory information from ELF files and linker scripts, providing symbol-level analysis with source file mapping for any embedded architecture.

**Use it locally, in any CI/CD system, or with GitHub Actions.**

## Features

- **Multi-Architecture Support**: Works with any embedded architecture
- **Deep ELF Analysis**: Symbol extraction, DWARF debug information, section mapping
- **Intelligent Linker Script Parsing**: Handles GNU LD syntax with automatic architecture detection
- **Flexible Integration**: Command-line tools for local use, CI/CD scripts, Python API
- **Cloud Integration**: Upload reports to MemBrowse platform for historical tracking

## Installation

```bash
# Install directly from GitHub
pip install git+https://github.com/membrowse/membrowse-action.git
```

Or for development:

```bash
# Clone and install in editable mode
git clone https://github.com/membrowse/membrowse-action.git
cd membrowse-action
pip install -e .
```

### Verify Installation

After installation, two command-line scripts will be available:

```bash
membrowse_report.sh --help        # Single commit analysis (PR/push workflows)
membrowse_onboard.sh --help           # Historical analysis (onboarding)
```

Use `--help` to see usage information and examples.

## Quick Start

### Analyze Your Firmware Locally

The simplest way to analyze your firmware:

```bash
# Generate a memory report (prints JSON to stdout)
membrowse_report.sh --local \
  build/firmware.elf \
  "src/linker.ld src/memory.ld" \
  my-target
```

This generates a JSON report with detailed memory analysis and prints it to stdout.

### Analyze with MemBrowse Platform Integration

```bash
export MEMBROWSE_API_KEY="your-api-key"

membrowse_report.sh \
  build/firmware.elf \
  "src/linker.ld" \
  esp32-project \
  "$MEMBROWSE_API_KEY" \
  "https://membrowse.appspot.com/api/upload"
```

### Analyze Historical Commits (Onboarding)

```bash
# Analyze the last 50 commits
membrowse_onboard.sh \
  50 \
  "make clean && make all" \
  build/firmware.elf \
  "STM32F746ZGTx_FLASH.ld" \
  stm32f746 \
  "$MEMBROWSE_API_KEY" \
  "https://membrowse.appspot.com/api/upload"
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
        uses: membrowse/membrowse-action/pr-action@latest
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
        uses: membrowse/membrowse-action/onboard-action@latest
        with:
          num_commits: 50
          build_script: "make clean && make"
          elf: build/firmware.elf
          ld: "linker.ld"
          target_name: my-target
          api_key: ${{ secrets.MEMBROWSE_API_KEY }}
```

### Generic CI/CD

For any CI system with shell access:

```bash
# Install MemBrowse
pip install git+https://github.com/membrowse/membrowse-action.git

# Build your firmware
make all

# Analyze memory
membrowse_report.sh \
  build/firmware.elf \
  "linker.ld" \
  my-target \
  "$MEMBROWSE_API_KEY" \
  "https://membrowse.appspot.com/api/upload"
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

When uploaded to MemBrowse platform, reports are enriched with:
- Git commit information (SHA, message, timestamp)
- Branch and PR metadata
- Base commit for diff analysis
- Repository context

## License

See [LICENSE](LICENSE) file for details.

## Support

- **Issues**: https://github.com/membrowse/membrowse-action/issues
- **Documentation**: This README and inline code documentation
- **MemBrowse Platform**: Contact via platform for API support
