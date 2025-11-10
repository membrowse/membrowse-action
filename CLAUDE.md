# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MemBrowse GitHub Actions is a collection of GitHub Actions for analyzing memory usage in embedded firmware and uploading reports to the MemBrowse SaaS platform. The repository contains two main actions:

- **pr-action**: Analyzes memory usage in pull requests and push events
- **onboard-action**: Performs historical analysis across multiple commits for onboarding

## Command-Line Interface

### Unified CLI (`membrowse`)

MemBrowse provides a single `membrowse` command with subcommands for different operations:

#### `membrowse report` - Generate Memory Footprint Reports

Core analysis tool that generates memory footprint reports from ELF files and linker scripts.

**Local Mode (Default)** - Generate JSON report without Git metadata or uploading:
```bash
# Minimal usage - outputs JSON to stdout (quiet mode, only errors shown)
membrowse report firmware.elf "linker.ld"

# Save to file
membrowse report firmware.elf "linker.ld" > report.json

# With verbose output to see progress
membrowse report firmware.elf "linker.ld" --verbose > report.json

# Multiple linker scripts
membrowse report firmware.elf "mem.ld sections.ld"
```

**Note**: By default, only errors are shown. Use `--verbose` to see progress messages.

**Upload Mode** - Upload report to MemBrowse platform:
```bash
# Upload without Git metadata
membrowse report firmware.elf "linker.ld" --upload \
    --api-key "$API_KEY" \
    --target-name "esp32" \
    --api-url "https://membrowse.com"

# Upload with Git metadata (manual)
membrowse report firmware.elf "linker.ld" --upload \
    --api-key "$API_KEY" \
    --target-name "stm32f4" \
    --api-url "https://membrowse.com" \
    --commit-sha "abc123" \
    --branch-name "main" \
    --repo-name "my-repo"
```

**GitHub Actions Mode** - Automatically detect Git metadata:
```bash
# Auto-detects Git metadata from GitHub environment
membrowse report firmware.elf "linker.ld" --github \
    --target-name "esp32" \
    --api-key "$API_KEY" \
    --api-url "https://membrowse.com"
```

**Modes:**
- **Local mode (default)**: Generates JSON report and outputs to stdout
- **Upload mode**: Uploads report to MemBrowse platform (requires `--upload` flag)
- **GitHub mode**: Auto-detects Git metadata and uploads (requires `--github` flag)

**Key Features:**
- Does NOT execute `git` commands unless `--github` flag is used
- Target name only required when uploading
- All Git metadata is optional

#### `membrowse onboard` - Historical Analysis

Analyzes memory footprints across multiple historical commits and uploads them to the MemBrowse platform:
```bash
# Analyze last 50 commits and upload to MemBrowse
membrowse onboard 50 "make clean && make" build/firmware.elf "linker.ld" \
    stm32f4 "$API_KEY" https://membrowse.com

# ESP-IDF project (API URL is optional, defaults to https://www.membrowse.com)
membrowse onboard 25 "idf.py build" build/firmware.elf \
    "build/esp-idf/esp32/esp32.project.ld" esp32 "$API_KEY"
```

### Performance Options

#### --skip-line-program flag

Skips DWARF line program processing for faster analysis at the cost of reduced source file coverage.

**When to use:**
- ✅ Build speed is critical (CI/CD, iterative development)
- ✅ 88% coverage acceptable (ARM) or 65% (ESP32)
- ✅ Large firmware (>10MB) with slow processing

**When to avoid:**
- ❌ Need 100% symbol coverage
- ❌ Processing time not a concern (<10s)
- ❌ Detailed profiling of compiler-optimized code

**Performance impact:**
- ARM Cortex-M (STM32): 9.3s → 7.1s (24% faster), 97% → 88% coverage
- Xtensa (ESP32): 30.1s → 20.8s (31% faster), 76% → 65% coverage

See `SKIP_LINE_PROGRAM_SUMMARY.md` for detailed analysis.

## Testing

### Run Tests
```bash
python -m pytest tests/
```

### Run Specific Tests
```bash
# Run a specific test file
python -m pytest tests/test_memory_regions.py -v

# Run a specific test class
python -m pytest tests/test_memory_analysis.py::TestMemoryAnalysis -v

# Run with verbose output and stop on first failure
python -m pytest tests/ -v -x
```

### Prerequisites
Install required system dependencies:
```bash
# Install C compiler (required for tests)
sudo apt-get install gcc                    # Standard GCC
# OR for ARM targets
sudo apt-get install gcc-arm-none-eabi      # ARM cross-compiler

# Python dependencies are in requirements.txt files
pip install -r onboard-action/requirements.txt
pip install -r pr-action/requirements.txt
```

### Test Structure
- Tests use mock ELF files and linker scripts in `tests/` directory
- Integration tests validate the complete `collect_report.sh` workflow
- Memory region parsing tests verify linker script parsing accuracy
- ELF analysis tests validate symbol extraction and architecture detection

## Architecture Overview

### Package Structure
The codebase is organized as a proper Python package:

```
membrowse/                          # Main Python package
├── __init__.py                     # Public API exports
│
├── core/                           # Core coordination
│   ├── __init__.py
│   ├── cli.py                      # CLI interface
│   ├── generator.py                # Memory report generation
│   ├── analyzer.py                 # Main ELF analysis coordination
│   ├── models.py                   # Data classes (MemoryRegion, Symbol, etc.)
│   └── exceptions.py               # Exception hierarchy
│
├── analysis/                       # Analysis components
│   ├── __init__.py
│   ├── dwarf.py                    # DWARF debug information processing
│   ├── sources.py                  # Source file resolution
│   ├── symbols.py                  # ELF symbol extraction
│   ├── sections.py                 # ELF section analysis
│   └── mapper.py                   # Section-to-region mapping
│
├── linker/                         # Linker script parsing
│   ├── __init__.py
│   ├── parser.py                   # Linker script parser (library)
│   ├── cli.py                      # Linker parser CLI
│   └── elf_info.py                 # ELF architecture detection
│
├── api/                            # API client
│   ├── __init__.py
│   └── client.py                   # Report upload to MemBrowse
│
├── cli.py                          # Main CLI entry point
│
├── commands/                       # CLI subcommands
│   ├── __init__.py
│   ├── report.py                   # 'report' subcommand
│   └── onboard.py                  # 'onboard' subcommand
│
├── utils/                          # Utilities
│   ├── __init__.py
│   └── git.py                      # Git metadata detection
│
scripts/                            # Shell wrappers
└── membrowse                       # Main CLI wrapper (calls membrowse.cli)
```

### CLI Architecture

**`membrowse` command** - Unified CLI interface:
- Single entry point with subcommands (`report`, `onboard`)
- Python-based with proper argument parsing and error handling
- Shell wrapper provides seamless installation via setup.py

**`membrowse report`** - Core analysis command:
- Parses linker scripts to extract memory regions
- Analyzes ELF files to generate memory footprint reports
- Outputs JSON to stdout (default) or uploads to platform
- `--github` flag enables automatic Git metadata detection from GitHub environment
- Does NOT execute `git` commands unless `--github` flag is used

**`membrowse onboard`** - Historical analysis command:
- Iterates through N commits, checking out each one
- Builds firmware at each commit
- Automatically extracts Git metadata for each commit
- Uploads memory footprint reports with full commit context

### Action Structure
Each action (`pr-action/`, `onboard-action/`) contains:
- `action.yml`: GitHub Actions definition
- `entrypoint.sh`: Action-specific entry point that calls scripts
- `requirements.txt`: Python dependencies

### Key Processing Flow
1. **Architecture Detection**: `linker/elf_info.py` analyzes ELF files to determine target architecture (ARM, Xtensa, RISC-V, etc.)
2. **Linker Script Parsing**: `linker/parser.py` parses GNU LD linker scripts using architecture-specific strategies
3. **Memory Analysis**: The modular analysis system combines ELF analysis with memory regions to generate comprehensive reports
4. **Report Upload**: `api/client.py` sends reports to MemBrowse platform (optional)

### Advanced Features
- **DWARF Debug Info**: Extracts source file mappings from debug symbols (prioritizes definition locations over declarations)
- **Multi-Architecture Support**: Handles different embedded platforms (STM32, ESP32, Nordic, etc.)
- **Expression Evaluation**: Safely evaluates linker script expressions and variables
- **Hierarchical Memory Regions**: Supports parent-child memory region relationships

## Architecture-Specific Parsing

The system automatically detects target architecture from ELF files and applies appropriate parsing strategies:

- **ESP32/ESP8266**: Handles Xtensa-specific linker script patterns and variables
- **STM32/ARM**: Processes standard ARM Cortex-M memory layouts  
- **Nordic nRF**: Supports SoftDevice and bootloader-aware memory regions
- **RISC-V**: Handles QEMU and embedded RISC-V targets

## Memory Region Validation

The parser includes intelligent validation that:
- Detects hierarchical memory relationships (e.g., FLASH parent with FLASH_APP child)
- Validates region overlaps and containment
- Provides architecture-specific default variables
- Handles complex linker script expressions with variable substitution

## Development Commands

### Code Quality
```bash
# Run pylint on membrowse package
pylint membrowse/

# Run pylint on tests
pylint tests/

# Check all Python code with scores
pylint membrowse/ tests/ --score=yes
```

### Manual Testing
```bash
# Test linker script parsing
python -m membrowse.linker.cli path/to/linker.ld

# Test report command - local mode (no Git, no upload)
membrowse report firmware.elf "linker1.ld linker2.ld" > report.json

# Test report command - upload mode
membrowse report firmware.elf "linker.ld" --upload \
    --api-key "$API_KEY" \
    --target-name "stm32f4" \
    --api-url "https://membrowse.com" \
    --commit-sha "$(git rev-parse HEAD)" \
    --branch-name "$(git branch --show-current)"

# Test report command - GitHub mode (auto-detects Git metadata and uploads)
membrowse report firmware.elf "linker.ld" --github \
    --target-name "esp32" \
    --api-key "$API_KEY"

# Test onboard command (analyzes and uploads historical commits)
membrowse onboard 10 "make build" build/firmware.elf "src/linker.ld" \
    stm32f4 "$API_KEY" https://membrowse.com
```

## Common Patterns

### Linker Script Support
The system handles various linker script formats:
- Standard GNU LD syntax with ORIGIN/LENGTH
- ESP-IDF style without parenthetical attributes
- Variable-based expressions and DEFINED() conditionals
- Architecture-specific memory layouts

### Error Handling
- Graceful degradation when DWARF debug info is unavailable
- Fallback strategies for unsupported linker script patterns
- Comprehensive logging for debugging parsing issues
- Validation warnings for unusual memory configurations