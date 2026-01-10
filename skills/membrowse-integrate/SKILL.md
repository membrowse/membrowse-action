---
name: membrowse-integrate
description: Integrate MemBrowse memory tracking into an embedded firmware project. Use when the user wants to set up MemBrowse, add memory analysis GitHub workflows, or create membrowse-targets.json for tracking RAM/Flash usage.
allowed-tools: Read, Glob, Grep, Write, Edit, Bash, Task, AskUserQuestion
---

# MemBrowse Integration Skill

You are integrating MemBrowse memory analysis into an embedded firmware project. Follow these steps to identify build targets, create the configuration file, and set up GitHub workflows.

## Step 1: Explore the Codebase to Identify Build Targets

First, understand what the project builds and how.

### 1.1 Search for Build System Files

```bash
# Find build configuration files
find . -name "Makefile*" -o -name "CMakeLists.txt" -o -name "*.mk" 2>/dev/null | head -20

# Look for board/port directories
find . -name "boards" -type d 2>/dev/null
find . -name "ports" -type d 2>/dev/null

# Check existing CI workflows for build patterns
ls -la .github/workflows/ 2>/dev/null
```

### 1.2 Analyze Existing CI Workflows

Read existing workflow files to understand:
- What targets are currently built
- What setup commands are used
- Where ELF files are output

### 1.3 Find Linker Scripts

```bash
# Find all linker scripts
find . -name "*.ld" -o -name "*.lds" 2>/dev/null

# Check Makefiles for linker script references
grep -r "LDSCRIPT\|\.ld\|-T " --include="Makefile*" --include="*.mk" 2>/dev/null | head -20
```

### 1.4 Find ELF Output Locations

```bash
# Check for ELF references in CI
grep -r "\.elf\|firmware" .github/workflows/ --include="*.yml" 2>/dev/null | head -20

# Common patterns to look for:
# - build/firmware.elf
# - build-BOARDNAME/firmware.elf
# - build/PROJECT_NAME.elf
```

## Step 2: Collect Target Information

For each target you identify, gather:

| Field | Description |
|-------|-------------|
| `target_name` | Unique identifier (e.g., `stm32-pybv10`, `esp32-devkit`) |
| `port` | Platform folder name (for ccache key) |
| `board` | Board variant name (for ccache key) |
| `setup_cmd` | Commands to install build dependencies |
| `build_cmd` | Commands to compile the firmware |
| `elf` | Path to output ELF file after build |
| `ld` | Space-separated linker script paths (can be empty) |
| `linker_vars` | Optional: variable definitions for linker parsing |

### Platform-Specific Setup Commands

**ARM Cortex-M (STM32, SAMD, NXP, etc.):**
```bash
sudo apt-get update && sudo apt-get install -y gcc-arm-none-eabi libnewlib-arm-none-eabi
```

**ESP32/ESP8266:**
```bash
# Usually handled by project CI scripts or ESP-IDF setup
. $IDF_PATH/export.sh
```

**RISC-V:**
```bash
# Check project docs for specific toolchain
sudo apt-get update && sudo apt-get install -y gcc-riscv64-unknown-elf
```

**x86/Unix builds:**
```bash
sudo apt-get update && sudo apt-get install -y build-essential libffi-dev pkg-config
```

## Step 3: Ask User to Confirm Targets

Before creating files, present the discovered targets to the user and ask them to confirm or modify:

- Which targets should be included?
- Are the paths correct?
- Any missing setup commands?
- What is the default branch name (main/master)?

## Step 4: Create membrowse-targets.json

Create `.github/membrowse-targets.json` with the confirmed targets:

```json
[
  {
    "target_name": "target-identifier",
    "port": "port-name",
    "board": "BOARD_NAME",
    "setup_cmd": "setup commands here",
    "build_cmd": "build commands here",
    "elf": "path/to/firmware.elf",
    "ld": "path/to/linker.ld",
    "linker_vars": "optional_var=value"
  }
]
```

### Field Notes

- `target_name`: Must be unique, used in artifact names
- `ld`: Space-separated if multiple scripts; empty string `""` if none
- `linker_vars`: Only needed if linker scripts use undefined variables
- `port` and `board`: Used for ccache keys, can be empty strings

## Step 5: Create GitHub Workflows

Create three workflow files in `.github/workflows/`:

### 5.1 membrowse-report.yml

```yaml
name: Membrowse Memory Report

on:
  pull_request:
  push:
    branches:
      - main  # IMPORTANT: Change to match the project's default branch

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  load-targets:
    runs-on: ubuntu-22.04
    outputs:
      matrix: ${{ steps.set-matrix.outputs.matrix }}
    steps:
      - name: Checkout repository
        uses: actions/checkout@v5

      - name: Load target matrix
        id: set-matrix
        run: echo "matrix=$(jq -c '.' .github/membrowse-targets.json)" >> $GITHUB_OUTPUT

  analyze:
    needs: load-targets
    runs-on: ubuntu-22.04
    strategy:
      fail-fast: false
      matrix:
        include: ${{ fromJson(needs.load-targets.outputs.matrix) }}

    steps:
      - name: Checkout repository
        uses: actions/checkout@v5
        with:
          fetch-depth: 0
          submodules: recursive

      - name: Install packages
        run: ${{ matrix.setup_cmd }}

      - name: Setup ccache
        uses: hendrikmuhs/ccache-action@v1.2
        with:
          key: ${{ matrix.port }}-${{ matrix.board }}

      - name: Build firmware
        run: ${{ matrix.build_cmd }}

      - name: Run Membrowse PR Action
        id: analyze
        continue-on-error: true
        uses: membrowse/membrowse-action@v1
        with:
          target_name: ${{ matrix.target_name }}
          elf: ${{ matrix.elf }}
          ld: ${{ matrix.ld }}
          linker_vars: ${{ matrix.linker_vars }}
          api_key: ${{ secrets.MEMBROWSE_API_KEY }}
          api_url: ${{ vars.MEMBROWSE_API_URL }}
          verbose: INFO

      - name: Upload report artifact
        if: ${{ steps.analyze.outcome == 'success' }}
        uses: actions/upload-artifact@v4
        with:
          name: membrowse-report-${{ matrix.target_name }}
          path: ${{ steps.analyze.outputs.report_path }}
```

### 5.2 membrowse-comment.yml

```yaml
name: Membrowse PR Comment

on:
  workflow_run:
    workflows: [Membrowse Memory Report]
    types: [completed]

permissions:
  contents: read
  actions: read
  pull-requests: write

jobs:
  comment:
    runs-on: ubuntu-22.04
    if: github.event.workflow_run.event == 'pull_request' && github.event.workflow_run.conclusion == 'success'
    steps:
      - name: Checkout repository
        uses: actions/checkout@v5

      - name: Download report artifacts
        id: download-reports
        uses: actions/github-script@v7
        with:
          result-encoding: string
          script: |
            const fs = require('fs');

            const allArtifacts = await github.rest.actions.listWorkflowRunArtifacts({
              owner: context.repo.owner,
              repo: context.repo.repo,
              run_id: context.payload.workflow_run.id,
            });

            const reportArtifacts = allArtifacts.data.artifacts.filter(
              artifact => artifact.name.startsWith('membrowse-report-')
            );

            if (reportArtifacts.length === 0) {
              console.log('No report artifacts found');
              return 'skip';
            }

            fs.mkdirSync('reports', { recursive: true });

            for (const artifact of reportArtifacts) {
              console.log(`Downloading ${artifact.name}...`);
              const download = await github.rest.actions.downloadArtifact({
                owner: context.repo.owner,
                repo: context.repo.repo,
                artifact_id: artifact.id,
                archive_format: 'zip',
              });

              const zipPath = `${artifact.name}.zip`;
              fs.writeFileSync(zipPath, Buffer.from(download.data));
              await exec.exec('unzip', ['-o', zipPath, '-d', 'reports']);
            }

            return 'ok';

      - name: Post combined PR comment
        if: steps.download-reports.outputs.result == 'ok'
        uses: membrowse/membrowse-action/comment-action@v1
        with:
          json_files: "reports/*.json"
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### 5.3 membrowse-onboard.yml

```yaml
name: Onboard to Membrowse

on:
  workflow_dispatch:
    inputs:
      num_commits:
        description: 'Number of commits to process'
        required: true
        default: '100'
        type: string

jobs:
  load-targets:
    runs-on: ubuntu-22.04
    outputs:
      matrix: ${{ steps.set-matrix.outputs.matrix }}
    steps:
      - name: Checkout repository
        uses: actions/checkout@v5

      - name: Load target matrix
        id: set-matrix
        run: echo "matrix=$(jq -c '.' .github/membrowse-targets.json)" >> $GITHUB_OUTPUT

  onboard:
    needs: load-targets
    runs-on: ubuntu-22.04
    strategy:
      fail-fast: false
      matrix:
        include: ${{ fromJson(needs.load-targets.outputs.matrix) }}

    steps:
      - name: Checkout repository
        uses: actions/checkout@v5
        with:
          fetch-depth: 0
          submodules: recursive

      - name: Install packages
        run: ${{ matrix.setup_cmd }}

      - name: Setup ccache
        uses: hendrikmuhs/ccache-action@v1.2
        with:
          key: ${{ matrix.port }}-${{ matrix.board }}

      - name: Run Membrowse Onboard Action
        uses: membrowse/membrowse-action/onboard-action@v1
        with:
          target_name: ${{ matrix.target_name }}
          num_commits: ${{ github.event.inputs.num_commits }}
          build_script: ${{ matrix.build_cmd }}
          elf: ${{ matrix.elf }}
          ld: ${{ matrix.ld }}
          linker_vars: ${{ matrix.linker_vars }}
          api_key: ${{ secrets.MEMBROWSE_API_KEY }}
          api_url: ${{ vars.MEMBROWSE_API_URL }}
```

## Step 6: Inform User About Secrets

After creating the files, tell the user they need to configure:

1. **Repository Secret**: `MEMBROWSE_API_KEY` - API key from MemBrowse dashboard
2. **Repository Variable**: `MEMBROWSE_API_URL` - API URL (optional, defaults to `https://www.membrowse.com`)

Location: Repository Settings → Secrets and variables → Actions

## Step 7: Provide Testing Instructions

Tell the user how to test:

1. **Test Report Workflow**: Create a PR to trigger `membrowse-report.yml`
2. **Test Onboard Workflow**: Go to Actions → "Onboard to Membrowse" → Run workflow with 10 commits first

## Troubleshooting Reference

If builds fail:
- Ensure all dependencies are in `setup_cmd`
- Check if submodules need `git submodule update --init --recursive`
- Verify paths are relative to repository root

If linker parsing fails:
- Add required variables to `linker_vars`
- Check linker scripts exist at specified paths
- Empty `ld` field is valid but limits analysis

If ELF not found:
- Verify build completes before analysis step
- Check board name in output path
- Add `ls -la path/to/build/` after build step to debug
