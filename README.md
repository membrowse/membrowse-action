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
- **Cloud Integration**: Upload reports to [MemBrowse](https://membrowse.com) for historical tracking, diffs and monitoring

## Installation

### From PyPI

```bash
pip install membrowse
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
# Generate a human-readable report (default)
membrowse report \
  build/firmware.elf \
  "src/linker.ld src/memory.ld"

# Output JSON format instead
membrowse report \
  build/firmware.elf \
  "src/linker.ld src/memory.ld" \
  --json

# Show all symbols (not just top 20)
membrowse report \
  build/firmware.elf \
  "src/linker.ld src/memory.ld" \
  --all-symbols

# With verbose output to see progress messages
membrowse -v INFO report \
  build/firmware.elf \
  "src/linker.ld src/memory.ld"
```

By default, this generates a **human-readable report** with memory regions, sections, and top symbols. Use `--json` to output structured JSON data instead. Use `-v INFO` or `-v DEBUG` before the subcommand to see progress messages (default is `WARNING` which only shows warnings and errors).

**Example output:**

```
ELF Metadata: build/firmware.elf  |  Arch: ELF32  |  Machine: EM_ARM  |  Entry: 0x0802015d  |  Type: ET_EXEC
=======================================================================================================================================

Region               Address Range                                Size                Used                Free  Utilization
--------------------------------------------------------------------------------------------------------------------------------------------
FLASH                0x08000000-0x08100000             1,048,576 bytes       365,192 bytes       683,384 bytes  [██████░░░░░░░░░░░░░░] 34.8%
  └─ FLASH_START     0x08000000-0x08004000                16,384 bytes        14,708 bytes         1,676 bytes  [█████████████████░░░] 89.8%
     • .isr_vector              392 bytes
     • .isr_extratext        14,316 bytes
  └─ FLASH_FS        0x08004000-0x08020000               114,688 bytes             0 bytes       114,688 bytes  [░░░░░░░░░░░░░░░░░░░░] 0.0%
  └─ FLASH_TEXT      0x08020000-0x08100000               917,504 bytes       350,484 bytes       567,020 bytes  [███████░░░░░░░░░░░░░] 38.2%
     • .text                350,476 bytes
     • .ARM                       8 bytes
RAM                  0x20000000-0x20020000               131,072 bytes        26,960 bytes       104,112 bytes  [████░░░░░░░░░░░░░░░░] 20.6%
  • .data                       52 bytes
  • .bss                     8,476 bytes
  • .heap                   16,384 bytes
  • .stack                   2,048 bytes

Top 20 Largest Symbols
======================

Name                                     Address                    Size  Type       Section              Source
--------------------------------------------------------------------------------------------------------------------------------------------
usb_device                               0x20000a30          5,444 bytes  OBJECT     .bss                 usb.c
mp_qstr_const_pool                       0x08062b70          4,692 bytes  OBJECT     .text                qstr.c
mp_execute_bytecode                      0x080392f9          4,208 bytes  FUNC       .text                vm.c
fresh_pybcdc_inf                         0x0806ffaa          2,598 bytes  OBJECT     .text                factoryreset.c
emit_inline_thumb_op                     0x0802ac25          2,476 bytes  FUNC       .text                emitinlinethumb.c
mp_qstr_const_hashes                     0x08061b36          2,334 bytes  OBJECT     .text                qstr.c
stm_module_globals_table                 0x08073478          2,096 bytes  OBJECT     .text                modstm.c
stm32_help_text                          0x08072366          2,067 bytes  OBJECT     .text                help.c
mp_lexer_to_next                         0x080229ed          1,768 bytes  FUNC       .text                lexer.c
f_mkfs                                   0x080020ed          1,564 bytes  FUNC       .isr_extratext       ff.c
...
```

### Upload Reports to MemBrowse Platform

```bash
# Upload mode - uploads report to MemBrowse platform (https://membrowse.com)
membrowse report \
  build/firmware.elf \
  "src/linker.ld" \
  --upload \
  --target-name esp32 \
  --api-key your-membrowse-api-key

# GitHub Actions mode - auto-detects Git metadata from CI environment
membrowse report \
  build/firmware.elf \
  "src/linker.ld" \
  --github \
  --target-name esp32 \
  --api-key your-membrowse-api-key
```

When uploading, MemBrowse will fail the build (exit code 1) if budget alerts are detected. Use `--dont-fail-on-alerts` to continue despite alerts.

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

MemBrowse provides GitHub Actions for seamless CI integration. The main action is available on the [GitHub Marketplace](https://github.com/marketplace/actions/membrowse-pr-memory-report).

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
        uses: membrowse/membrowse-action@v1
        with:
          elf: build/firmware.elf
          ld: "src/linker.ld"
          target_name: stm32f4
          api_key: ${{ secrets.MEMBROWSE_API_KEY }}
          # Optional inputs:
          # pr_comment: true                    # Post PR comments with memory changes (default: true)
          # dont_fail_on_alerts: true           # Continue even if budget alerts are detected (default: false)
          # verbose: INFO                       # Set logging level: DEBUG, INFO, or WARNING (default: WARNING)
```

**Features:**
- Automatically uploads memory reports to MemBrowse
- Posts PR comments showing memory changes, budget alerts, and comparison links (enabled by default)
- Fails CI if memory budgets are exceeded (unless `dont_fail_on_alerts: true`)
- Auto-detects Git metadata from GitHub Actions environment
- **Fork PR Support**: For public repositories, fork PRs can upload reports without an API key (tokenless mode)

#### Fork PR Support (Public Repositories)

Fork PRs cannot access repository secrets like `MEMBROWSE_API_KEY`. For public repositories, MemBrowse supports **tokenless uploads** that authenticate using GitHub's pull request context.

```yaml
name: Memory Analysis
on: pull_request

jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Build firmware
        run: make all

      - name: Analyze memory
        uses: membrowse/membrowse-action@v1
        with:
          elf: build/firmware.elf
          ld: "src/linker.ld"
          target_name: stm32f4
          # api_key not required for fork PRs to public repos!
```

**How it works:**
- When running in a fork PR context without an API key, the action automatically uses tokenless upload mode
- The server validates the upload using GitHub's PR metadata (repository, PR number, commit SHA, author)
- This only works for **public repositories** - private repos always require an API key

**Behavior Summary:**
| Context | API Key | Upload Mode |
|---------|---------|-------------|
| Fork PR | None | Tokenless (public repos only) |
| Fork PR | Provided | Authenticated |
| Same-repo PR | Required | Authenticated |
| Push event | Required | Authenticated |

#### Multi-Target Combined Comments

When analyzing multiple targets, use a matrix strategy with the comment action to post a single combined PR comment:

```yaml
name: Multi-Target Analysis
on: pull_request

jobs:
  analyze:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        target: [esp32, stm32f4, nrf52]
    steps:
      - uses: actions/checkout@v3

      - name: Build firmware
        run: make TARGET=${{ matrix.target }}

      - name: Analyze memory
        id: analyze
        uses: membrowse/membrowse-action@v1
        with:
          elf: build/${{ matrix.target }}/firmware.elf
          ld: "linker/${{ matrix.target }}.ld"
          target_name: ${{ matrix.target }}
          api_key: ${{ secrets.MEMBROWSE_API_KEY }}

      - name: Upload report artifact
        uses: actions/upload-artifact@v4
        with:
          name: report-${{ matrix.target }}
          path: ${{ steps.analyze.outputs.report_path }}

  comment:
    needs: analyze
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Download all reports
        uses: actions/download-artifact@v4
        with:
          path: reports
          pattern: report-*
          merge-multiple: true

      - name: Post combined PR comment
        uses: membrowse/membrowse-action/comment-action@v1
        with:
          json_files: "reports/*.json"
```

#### Historical Onboarding

For onboarding historical commits, use the onboard action from the subdirectory:

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
        uses: membrowse/membrowse-action/onboard-action@v1
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

## Advanced Usage

### Custom GitHub Integration

For custom GitHub integration (e.g., posting PR comments with custom formatting), use `--output-raw-response`:

```bash
# Output raw API response as JSON to stdout (for piping)
membrowse report \
  build/firmware.elf \
  "src/linker.ld" \
  --github \
  --target-name esp32 \
  --api-key your-api-key \
  --output-raw-response | python -m your_custom_pr_comment_script
```

This outputs a JSON object with:
- `comparison_url`: URL to the build comparison page on MemBrowse
- `api_response`: Full API response including memory changes and alerts
- `target_name`: The target name specified

### Verbose Logging

Control logging verbosity with the global `-v/--verbose` flag (must come before the subcommand):

```bash
# Default (WARNING): Only warnings and errors
membrowse report firmware.elf "linker.ld"

# INFO: Show progress messages
membrowse -v INFO report firmware.elf "linker.ld"

# DEBUG: Show detailed analysis information
membrowse --verbose DEBUG report firmware.elf "linker.ld"
```

## Platform Support

MemBrowse is **platform agnostic** and works with any embedded architecture that produces ELF files and uses GNU LD linker scripts. The tool automatically detects the target architecture and applies appropriate parsing strategies for optimal results.


## License

See [LICENSE](LICENSE) file for details.

## Support

- **Issues**: https://github.com/membrowse/membrowse-action/issues
- **Documentation**: This README and inline code documentation
- **MemBrowse Support**: support@membrowse.com
