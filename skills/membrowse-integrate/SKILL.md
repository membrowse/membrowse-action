---
name: membrowse-integrate
description: Integrate MemBrowse memory tracking into a project that produces ELF binaries. Use when the user wants to set up MemBrowse, add memory analysis GitHub workflows, create membrowse-targets.json for tracking memory usage, or add a MemBrowse badge to the README. Works with embedded firmware (STM32, ESP32, nRF, RISC-V) and non-embedded ELF targets (Linux x86/x64, game engines, system software).
allowed-tools: Read, Glob, Grep, Write, Edit, Bash, Task, AskUserQuestion
---

# MemBrowse Integration Skill

You are integrating MemBrowse memory analysis into a project that produces ELF binaries. This works for both embedded firmware (STM32, ESP32, nRF, RISC-V) and non-embedded targets (Linux x86/x64 applications, game engines, system software). Follow these steps to identify build targets, create the configuration file, set up GitHub workflows, and optionally add a MemBrowse badge to the README.

## Step 1: Explore the Codebase to Identify Build Targets

First, understand what the project builds and how.

### 1.1 Search for Build System Files

```bash
# Find build configuration files
find . -name "Makefile*" -o -name "CMakeLists.txt" -o -name "*.mk" -o -name "meson.build" -o -name "Cargo.toml" 2>/dev/null | head -20

# For embedded projects: look for board/port directories
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

### 1.3 Find Linker Scripts (Embedded Projects)

Linker scripts define memory regions (FLASH, RAM, etc.) and are mainly used in embedded projects. Non-embedded projects typically don't have custom linker scripts — this is fine, MemBrowse will use default Code/Data regions based on ELF sections.

```bash
# Find all linker scripts
find . -name "*.ld" -o -name "*.lds" 2>/dev/null

# Check Makefiles for linker script references
grep -r "LDSCRIPT\|\.ld\|-T " --include="Makefile*" --include="*.mk" 2>/dev/null | head -20
```

### 1.4 Find ELF Output Locations

```bash
# Check for ELF references in CI
grep -r "\.elf\|\.out\|firmware\|build/" .github/workflows/ --include="*.yml" 2>/dev/null | head -20

# Common embedded patterns:
# - build/firmware.elf
# - build-BOARDNAME/firmware.elf
# - build/PROJECT_NAME.elf
#
# Common non-embedded patterns:
# - build/myapp (no extension — use `file` command to confirm it's ELF)
# - target/release/myapp (Rust)
# - builddir/myapp (Meson)
```

## Step 2: Collect Target Information

For each target you identify, gather:

| Field | Description |
|-------|-------------|
| `name` | Unique identifier (e.g., `stm32-pybv10`, `esp32-devkit`, `linux-x64`) |
| `setup_cmd` | Commands to install build dependencies |
| `build_script` | Commands to compile the project |
| `elf` | Path to output ELF file after build |
| `ld` | Space-separated linker script paths (can be empty) |
| `def` | Optional: variable definitions for linker parsing (e.g., `"__flash_size__=4096K"`) |

### Platform-Specific Setup Commands

**x86/x64 Linux (non-embedded):**
```bash
sudo apt-get update && sudo apt-get install -y build-essential
# Add project-specific libraries as needed (e.g., libssl-dev, libffi-dev)
```

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

## Step 3: Ask User to Confirm Targets and Project Details

Before creating files, present the discovered targets to the user and ask them to confirm or modify:

- Which targets should be included?
- Are the paths correct?
- Any missing setup commands?
- What is the default branch name (main/master)?
- **Is this an open-source project that accepts pull requests from forks?** (This determines the workflow pattern — open-source projects need a two-workflow setup so PR comments work for fork PRs.)
- **Does the project use git submodules?** (If yes, the checkout step will include `submodules: recursive`.)

## Step 4: Verify Targets Locally

Before adding targets to the configuration file, verify each target end-to-end: build succeeds, ELF is found, and `membrowse report` produces valid output.

### 4.1 Install membrowse

```bash
pip install membrowse  # if not already installed
```

### 4.2 Build and Verify ELF

For each target, run the build command and confirm the ELF file exists:

```bash
# Run the build
make clean && make BOARD=PYBV10                                      # embedded example
cmake -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo && cmake --build build  # non-embedded example

# Confirm the ELF file exists
ls -la build/firmware.elf         # embedded
file build/myapp                  # non-embedded — confirm "ELF" in output
```

If the ELF is not found, check the build output for the actual output path.

### 4.3 Run membrowse report

Run `membrowse report` on the built ELF to verify the full analysis pipeline. This is the single most important verification step — it catches bad ELF paths, unparseable linker scripts, missing linker variables, and unsupported binary formats all at once.

**With linker scripts (embedded):**
```bash
membrowse report path/to/firmware.elf "path/to/linker.ld"
```

**Without linker scripts (non-embedded or no custom layout):**
```bash
membrowse report path/to/binary
```

**With linker variable definitions:**
```bash
membrowse report path/to/firmware.elf "path/to/linker.ld" --def __flash_size__=4096K
```

#### What to check in the output

The human-readable output should show:
- **Memory regions** — either parsed from linker scripts (e.g., FLASH, RAM) or default Code/Data regions
- **Usage percentages** — non-zero usage for at least some regions
- **No errors** — if there are parsing errors or warnings, fix them before proceeding

To inspect the full JSON output (useful for debugging):
```bash
membrowse report path/to/firmware.elf "path/to/linker.ld" --json
```

Check that the JSON contains:
- `memory_regions` with non-zero `used` values
- `symbols` array (non-empty if built with `-g` debug symbols)
- `sections` array with expected ELF sections (`.text`, `.data`, `.bss`, etc.)

#### Common issues at this step

- **Linker parse error with undefined variable**: Add the variable via `--def VAR=VALUE`. Note the value for the `def` field in targets.json.
- **Linker script not found**: The path may be relative to a subdirectory or generated during build — check the build directory.
- **No symbols in output**: Binary was built without debug info. Add `-g` to compiler flags or use `-DCMAKE_BUILD_TYPE=RelWithDebInfo`. Sections and regions will still work, but source file attribution requires debug symbols.
- **"Unsupported binary format"**: The file is not ELF. Use `file path/to/binary` to check. Look for the intermediate ELF before any `objcopy` conversion.
- **Zero usage in all regions**: The linker scripts may define regions that don't match the ELF sections. Try running without linker scripts first (`membrowse report path/to/elf`) to see default Code/Data analysis, then compare.

### 4.4 Ask User to Verify

Show the user the `membrowse report` output and ask them to confirm:
- Does the output look reasonable?
- Are the memory regions correct?
- If symbols are missing, is that expected (no `-g` flag)?

Only proceed to create the configuration file after `membrowse report` runs successfully.

## Step 5: Create membrowse-targets.json

Create `.github/membrowse-targets.json` with the verified targets.

**Embedded example:**
```json
{
  "targets": [
    {
      "name": "stm32-pybv10",
      "setup_cmd": "sudo apt-get update && sudo apt-get install -y gcc-arm-none-eabi",
      "build_script": "make -C ports/stm32 BOARD=PYBV10",
      "elf": "ports/stm32/build-PYBV10/firmware.elf",
      "ld": "ports/stm32/boards/stm32f405.ld",
      "def": ""
    }
  ]
}
```

**Non-embedded example:**
```json
{
  "targets": [
    {
      "name": "linux-x64",
      "setup_cmd": "sudo apt-get update && sudo apt-get install -y build-essential",
      "build_script": "cmake -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo && cmake --build build",
      "elf": "build/myapp",
      "ld": "",
      "def": ""
    }
  ]
}
```

### Field Notes

- `name`: Must be unique across targets, used as the target name in MemBrowse and in artifact names
- `elf`: Path to any ELF binary — embedded firmware (`.elf`) or non-embedded executables/shared libraries (no extension or `.so`)
- `ld`: Space-separated linker script paths for embedded projects; empty string `""` for non-embedded (analysis will use default Code/Data regions based on ELF sections like `.text`, `.data`, `.bss`)
- `def`: Only needed if linker scripts use undefined variables (e.g., `"__flash_size__=4096K"`); leave empty for non-embedded
- `setup_cmd`: Commands to install build dependencies before building (skill-specific; the workflow runs this before the build step)
- `build_script`: Use `-g` or `-DCMAKE_BUILD_TYPE=RelWithDebInfo` to include debug symbols — this lets MemBrowse attribute memory to source files and symbols

## Step 6: Create GitHub Workflows

Based on the project type identified in Step 3, create workflows in `.github/workflows/`.

Choose the appropriate pattern:
- **Pattern A** (Single target, private repo): One workflow with inline comment
- **Pattern B** (Multiple targets, private repo): One workflow with matrix build + comment job
- **Pattern C** (Open-source / fork PRs): Two workflows — report + comment via `workflow_run`

---

### Pattern A: Single Target, Private Repo

Create one workflow file: `membrowse.yml`

Use this when there is only one target and the repo does not accept fork PRs.

```yaml
name: MemBrowse Memory Report

on:
  pull_request:
  push:
    branches:
      - main  # Change to match the project's default branch

permissions:
  contents: read
  pull-requests: write

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v5
        with:
          fetch-depth: 0
          # Only include submodules line if user confirmed submodules in Step 3
          # submodules: recursive

      - name: Install packages
        run: |
          # TARGET_SETUP_CMD goes here

      - name: Build
        run: |
          # TARGET_BUILD_SCRIPT goes here
          # For non-embedded: e.g., cmake -B build && cmake --build build
          # For embedded: e.g., make -C ports/stm32 BOARD=PYBV10

      - name: Run MemBrowse analysis
        uses: membrowse/membrowse-action@v1
        with:
          target_name: TARGET_NAME
          elf: TARGET_ELF
          ld: TARGET_LD
          # Only include linker_vars if the target has def values
          # linker_vars: TARGET_DEF
          api_key: ${{ secrets.MEMBROWSE_API_KEY }}
```

**Template substitutions:** Replace `TARGET_NAME`, `TARGET_SETUP_CMD`, `TARGET_BUILD_SCRIPT`, `TARGET_ELF`, `TARGET_LD`, and `TARGET_DEF` with values from the single target in `membrowse-targets.json`. Since there's only one target, values are inlined directly.

---

### Pattern B: Multiple Targets, Private Repo

Create one workflow file: `membrowse.yml`

Use this when there are multiple targets and the repo does not accept fork PRs.

```yaml
name: MemBrowse Memory Report

on:
  pull_request:
  push:
    branches:
      - main  # Change to match the project's default branch

permissions:
  contents: read
  pull-requests: write

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  setup:
    runs-on: ubuntu-latest
    outputs:
      targets: ${{ steps.set-matrix.outputs.targets }}
    steps:
      - name: Checkout repository
        uses: actions/checkout@v5

      - name: Load target matrix
        id: set-matrix
        run: echo "targets=$(jq -c '.targets' .github/membrowse-targets.json)" >> $GITHUB_OUTPUT

  analyze:
    needs: setup
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        target: ${{ fromJson(needs.setup.outputs.targets) }}

    steps:
      - name: Checkout repository
        uses: actions/checkout@v5
        with:
          fetch-depth: 0
          # Only include submodules line if user confirmed submodules in Step 3
          # submodules: recursive

      - name: Install packages
        run: ${{ matrix.target.setup_cmd }}

      - name: Build
        run: ${{ matrix.target.build_script }}

      - name: Run MemBrowse analysis
        id: analyze
        continue-on-error: true
        uses: membrowse/membrowse-action@v1
        with:
          target_name: ${{ matrix.target.name }}
          elf: ${{ matrix.target.elf }}
          ld: ${{ matrix.target.ld }}
          linker_vars: ${{ matrix.target.def }}
          api_key: ${{ secrets.MEMBROWSE_API_KEY }}

      - name: Upload report artifact
        if: ${{ steps.analyze.outcome == 'success' }}
        uses: actions/upload-artifact@v4
        with:
          name: membrowse-report-${{ matrix.target.name }}
          path: ${{ steps.analyze.outputs.report_path }}

  comment:
    needs: analyze
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v5

      - name: Download all report artifacts
        uses: actions/download-artifact@v4
        with:
          path: reports
          pattern: membrowse-report-*
          merge-multiple: true

      - name: Post combined PR comment
        uses: membrowse/membrowse-action/comment-action@v1
        with:
          json_files: "reports/*.json"
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

---

### Pattern C: Open Source / Fork PRs

Create two workflow files: `membrowse-report.yml` and `membrowse-comment.yml`

Use this when the project accepts PRs from forks. Fork PRs don't have access to secrets, so the report workflow runs without writing PR comments, and a separate `workflow_run`-triggered workflow posts the comment.

#### membrowse-report.yml

```yaml
name: MemBrowse Memory Report

on:
  pull_request:
  push:
    branches:
      - main  # Change to match the project's default branch

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  setup:
    runs-on: ubuntu-latest
    outputs:
      targets: ${{ steps.set-matrix.outputs.targets }}
    steps:
      - name: Checkout repository
        uses: actions/checkout@v5

      - name: Load target matrix
        id: set-matrix
        run: echo "targets=$(jq -c '.targets' .github/membrowse-targets.json)" >> $GITHUB_OUTPUT

  analyze:
    needs: setup
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        target: ${{ fromJson(needs.setup.outputs.targets) }}

    steps:
      - name: Checkout repository
        uses: actions/checkout@v5
        with:
          fetch-depth: 0
          # Only include submodules line if user confirmed submodules in Step 3
          # submodules: recursive

      - name: Install packages
        run: ${{ matrix.target.setup_cmd }}

      - name: Build
        run: ${{ matrix.target.build_script }}

      - name: Run MemBrowse analysis
        id: analyze
        continue-on-error: true
        uses: membrowse/membrowse-action@v1
        with:
          target_name: ${{ matrix.target.name }}
          elf: ${{ matrix.target.elf }}
          ld: ${{ matrix.target.ld }}
          linker_vars: ${{ matrix.target.def }}
          api_key: ${{ secrets.MEMBROWSE_API_KEY }}

      - name: Upload report artifact
        if: ${{ steps.analyze.outcome == 'success' }}
        uses: actions/upload-artifact@v4
        with:
          name: membrowse-report-${{ matrix.target.name }}
          path: ${{ steps.analyze.outputs.report_path }}
```

#### membrowse-comment.yml

**IMPORTANT:** The `workflows:` value below must exactly match the `name:` field of the report workflow above (`MemBrowse Memory Report`). If they don't match, the comment workflow will never trigger.

```yaml
name: MemBrowse PR Comment

on:
  workflow_run:
    workflows: ["MemBrowse Memory Report"]
    types: [completed]

permissions:
  contents: read
  actions: read
  pull-requests: write

jobs:
  comment:
    runs-on: ubuntu-latest
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

---

### Onboard Workflow (All Patterns)

Always create a separate `membrowse-onboard.yml` workflow for historical analysis:

```yaml
name: Onboard to MemBrowse

on:
  workflow_dispatch:
    inputs:
      num_commits:
        description: 'Number of commits to process'
        required: true
        default: '10'
        type: string

jobs:
  setup:
    runs-on: ubuntu-latest
    outputs:
      targets: ${{ steps.set-matrix.outputs.targets }}
    steps:
      - name: Checkout repository
        uses: actions/checkout@v5

      - name: Load target matrix
        id: set-matrix
        run: echo "targets=$(jq -c '.targets' .github/membrowse-targets.json)" >> $GITHUB_OUTPUT

  onboard:
    needs: setup
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        target: ${{ fromJson(needs.setup.outputs.targets) }}

    steps:
      - name: Checkout repository
        uses: actions/checkout@v5
        with:
          fetch-depth: 0
          # Only include submodules line if user confirmed submodules in Step 3
          # submodules: recursive

      - name: Install packages
        run: ${{ matrix.target.setup_cmd }}

      - name: Run MemBrowse Onboard Action
        uses: membrowse/membrowse-action/onboard-action@v1
        with:
          target_name: ${{ matrix.target.name }}
          num_commits: ${{ github.event.inputs.num_commits }}
          build_script: ${{ matrix.target.build_script }}
          elf: ${{ matrix.target.elf }}
          ld: ${{ matrix.target.ld }}
          linker_vars: ${{ matrix.target.def }}
          api_key: ${{ secrets.MEMBROWSE_API_KEY }}
```

## Step 7: Inform User About Secrets

After creating the files, tell the user they need to configure:

1. **Repository Secret**: `MEMBROWSE_API_KEY` — API key from the MemBrowse dashboard

   Location: Repository Settings → Secrets and variables → Actions → New repository secret

> **Enterprise / self-hosted users:** If your MemBrowse instance is not at the default `https://api.membrowse.com`, add the `api_url` input to the action steps pointing to your instance URL.

## Step 8: Provide Testing Instructions

Tell the user how to test:

1. **Test Report Workflow**: Create a PR to trigger the report workflow
2. **Test Onboard Workflow**: Go to Actions → "Onboard to MemBrowse" → Run workflow (start with 10 commits)
3. **Verify PR Comments**: After the report workflow completes, check the PR for a memory usage comment

## Step 9: Add MemBrowse Badge to README (Optional)

Before adding a badge, ask the user:
- **Is this project open source, or do you have public access enabled in the MemBrowse portal?**

If the project is private and public access is not enabled, **skip the badge** — it will return a 404. Inform the user they can enable public access later in Project Settings on the MemBrowse portal.

### 9.1 Find the README File

```bash
ls -la README* readme* 2>/dev/null
```

### 9.2 Determine the Badge URL

The badge URL format is:
```
[![MemBrowse](https://membrowse.com/badge.svg)](https://membrowse.com/public/{owner}/{repo})
```

Get the owner and repo name from the git remote:
```bash
git remote get-url origin
```

Parse the URL to extract `{owner}/{repo}` (e.g., `micropython/micropython`).

### 9.3 Add the Badge

Add the badge near the top of the README, typically:
- After the main title/heading
- Alongside other badges if present
- Before the project description

**Example placement:**

```markdown
# Project Name

[![MemBrowse](https://membrowse.com/badge.svg)](https://membrowse.com/public/owner/repo)

Project description here...
```

**If other badges exist, add it inline:**

```markdown
# Project Name

[![Build](https://img.shields.io/...)](...)
[![License](https://img.shields.io/...)](...)
[![MemBrowse](https://membrowse.com/badge.svg)](https://membrowse.com/public/owner/repo)
```

### 9.4 Ask User for Confirmation

Before modifying the README:
- Show the user the badge that will be added
- Ask where they want it placed (if multiple badge locations exist)
- Confirm the owner/repo extracted from git remote is correct
- Remind them that **public access must be enabled** in MemBrowse Project Settings for the badge to work

## Next Steps

After the integration is working, mention these optional features the user can explore:

- **Memory budgets**: Set RAM/Flash budgets in the MemBrowse portal. PRs that exceed budgets will show alerts. Use `dont_fail_on_alerts: true` in the action to prevent CI failure on budget alerts.
- **Onboard options**: The onboard action supports `build_dirs` (only rebuild when specific directories change) and `initial_commit` (start from a specific commit hash).
- **Skip unchanged commits**: Use the `identical` input with a paths-filter action to skip MemBrowse analysis on commits that don't touch source code (e.g., docs-only changes).
- **Custom PR comment template**: Use `comment_template` in the comment action to customize the PR comment format with a Jinja2 template.

## Troubleshooting Reference

### Symbols not appearing in report
Ensure the binary is compiled with debug symbols (`-g` flag, or `-DCMAKE_BUILD_TYPE=RelWithDebInfo` for CMake). Without debug info, MemBrowse can still report section-level usage but cannot attribute memory to individual source files and symbols.

### PR comments not appearing
- **Permissions**: Ensure the workflow has `pull-requests: write` permission.
- **Open-source projects**: Fork PRs cannot write comments directly. Use the two-workflow pattern (Pattern C) with `workflow_run`.
- **Workflow name mismatch**: In Pattern C, the `workflows:` value in `membrowse-comment.yml` must exactly match the `name:` field in `membrowse-report.yml` (i.e., `"MemBrowse Memory Report"`).

### API key issues
- Verify the secret is named exactly `MEMBROWSE_API_KEY` in repository settings.
- Fork PRs do not have access to repository secrets. The report will still be generated and uploaded on push events, but fork PR runs will skip the upload. The `workflow_run` comment workflow handles this by posting comments from the base repo context.

### Git metadata missing
Ensure `fetch-depth: 0` is set on the checkout step. Without full history, MemBrowse cannot detect branch and commit metadata correctly.

### Unsupported binary format
MemBrowse requires ELF binaries. If your build produces `.bin`, `.hex`, or other non-ELF formats, locate the intermediate ELF file (usually in the build directory before the final conversion step). For non-embedded projects, the output binary is typically already ELF — verify with `file path/to/binary` (should show "ELF").

### Builds fail in CI
- Ensure all dependencies are in `setup_cmd`
- Check if submodules need `submodules: recursive` on the checkout step
- Verify paths are relative to repository root

### Linker parsing fails
- Add required variables to `def` in `membrowse-targets.json`
- Check linker scripts exist at the specified paths (some are generated during build)
- Empty `ld` field is valid — analysis will use default Code/Data regions
