# MemBrowse

[![PyPI version](https://badge.fury.io/py/membrowse.svg)](https://badge.fury.io/py/membrowse)
[![Python Versions](https://img.shields.io/pypi/pyversions/membrowse.svg)](https://pypi.org/project/membrowse/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Downloads](https://pepy.tech/badge/membrowse)](https://pepy.tech/project/membrowse)

A tool for analyzing memory footprint in embedded firmware. MemBrowse extracts detailed memory information from ELF files and linker scripts, providing symbol-level analysis with source file mapping for multiple architectures. Use it standalone for local analysis or integrate with [MemBrowse](https://membrowse.com) for historical analysis and CI integration.


## Features

- **Architecture Agnostic**: Works with architectures that produce ELFs with DWARF debug format
- **Source File Mapping**: Symbols are mapped to their definition source files
- **Memory Region Extraction**: Memory region capacity and layout are extracted from GNU LD linker scripts
- **Cloud Integration**: Upload reports to [MemBrowse](https://membrowse.com) for historical tracking, diffs, monitoring and CI gating 

## CI/CD Integration

### GitHub Actions

MemBrowse provides GitHub Actions for CI integration.


#### PR/Push Analysis

Create a Github action for PR analysis that will call `membrowse/membrowse-action`:

```yaml
name: Memory Analysis
on: [push, pull_request]

jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Build firmware
        run: make all # your build commands

      - name: Analyze memory
        id: analyze
        uses: membrowse/membrowse-action@v1
        with:
          elf: build/firmware.elf # your elf
          ld: "src/linker.ld" # your ld scripts
          target_name: stm32f4 # the target name will be recognized by Membrowse
          api_key: ${{ secrets.MEMBROWSE_API_KEY }}

      - name: Post PR comment
        if: github.event_name == 'pull_request'
        uses: membrowse/membrowse-action/comment-action@v1
        with:
          json_files: ${{ steps.analyze.outputs.report_path }}
```

#### Historical Onboarding

For getting historical build data from day one upload the last N commits by
Creating an Onboard Github action in your repo that will call `membrowse/membrowse-action/onboard-action`:

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
          num_commits: 100
          build_script: "make clean && make" # your build commands
          elf: build/firmware.elf # your elf file
          ld: "components.ld memory.ld" #your ld scripts 
          target_name: my-target # the target name will be recognized by Membrowse
          api_key: ${{ secrets.MEMBROWSE_API_KEY }}
```

### Claude Code Integration

If you use [Claude Code](https://claude.ai/code), you can automatically set up MemBrowse integration using the membrowse-integrate skill.

First, add the MemBrowse plugin to Claude Code:

```
/plugin marketplace add membrowse@membrowse-action
```

Then run the skill in your project:

```
/membrowse-integrate
```

This will:
- Analyze your project's build system and targets
- Verify builds and linker scripts work locally
- Create `membrowse-targets.json` configuration
- Set up GitHub Actions workflows for PR analysis and onboarding
- Add a MemBrowse badge to your README

## Local Installation

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
  --upload \
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

## Platform Support

MemBrowse is with toolchains that produce ELF files and uses GNU LD linker scripts.
If you found that you're not getting optimal results please contact us: support@membrowse.com 
We are actively working on improving Membrowse.

## License

See [LICENSE](LICENSE) file for details.

## Support

- **Issues**: https://github.com/membrowse/membrowse-action/issues
- **Documentation**: This README and inline code documentation
- **MemBrowse Support**: support@membrowse.com
