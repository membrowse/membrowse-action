# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MemBrowse GitHub Actions is a collection of GitHub Actions for analyzing memory usage in embedded firmware and uploading reports to the MemBrowse SaaS platform. The repository contains two main actions:

- **pr-action**: Analyzes memory usage in pull requests and push events
- **onboard-action**: Performs historical analysis across multiple commits for onboarding

## Testing

### Run Tests
```bash
PYTHONPATH=shared python -m pytest tests/
```

### Run Specific Tests
```bash
# Run a specific test file
PYTHONPATH=shared python -m pytest tests/test_memory_regions.py -v

# Run a specific test class
PYTHONPATH=shared python -m pytest tests/test_memory_analysis.py::TestMemoryAnalysis -v

# Run with verbose output and stop on first failure
PYTHONPATH=shared python -m pytest tests/ -v -x
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

### Modular Design
The codebase is structured with a shared module approach:

```
shared/
├── collect_report.sh       # Main orchestrator script
├── memory_report.py        # ELF analysis and JSON report generation
├── memory_regions.py       # Linker script parser with architecture detection
├── elf_parser.py          # ELF file architecture detection
└── upload.py              # Report upload to MemBrowse platform
```

### Action Structure
Each action (`pr-action/`, `onboard-action/`) contains:
- `action.yml`: GitHub Actions definition
- `entrypoint.sh`: Action-specific entry point that calls shared scripts
- `requirements.txt`: Python dependencies

### Key Processing Flow
1. **Architecture Detection**: `elf_parser.py` analyzes ELF files to determine target architecture (ARM, Xtensa, RISC-V, etc.)
2. **Linker Script Parsing**: `memory_regions.py` parses GNU LD linker scripts using architecture-specific strategies
3. **Memory Analysis**: `memory_report.py` combines ELF analysis with memory regions to generate comprehensive reports
4. **Report Upload**: `upload.py` sends reports to MemBrowse platform (optional)

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
# Run pylint on shared modules
PYTHONPATH=shared:. pylint shared/*.py

# Run pylint on tests
PYTHONPATH=shared:. pylint tests/*.py

# Check all Python code
PYTHONPATH=shared:. pylint shared/*.py tests/*.py --score=yes
```

### Manual Testing
```bash
# Test linker script parsing
python shared/memory_regions.py path/to/linker.ld

# Test ELF analysis  
python shared/memory_report.py --elf-path firmware.elf --memory-regions regions.json --output report.json

# Test complete workflow
bash shared/collect_report.sh firmware.elf "linker1.ld linker2.ld" target_name api_key commit_sha base_sha branch repo
```

### Local Action Testing
```bash
# Test pr-action locally
bash pr-action/entrypoint.sh firmware.elf "linker.ld" esp32 api_key

# Test onboard-action locally  
bash onboard-action/entrypoint.sh 10 "make build" build/firmware.elf "src/linker.ld" stm32 api_key
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