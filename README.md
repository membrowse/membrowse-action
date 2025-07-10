# MemBrowse GitHub Actions

A collection of GitHub Actions for analyzing memory usage in embedded firmware and uploading reports to MemBrowse SaaS platform.

## Actions

### 🔍 PR Memory Report (`pr-action`)

Analyzes memory usage of embedded firmware ELF files in pull requests and pushes, generating memory reports to catch regressions before merging.

**Usage:**
```yaml
- uses: yourorg/membrowse-action/pr-action@v1.0.0
  with:
    elf: path/to/firmware.elf
    ld: "path/to/linker.ld path/to/memory.ld"
    target_name: esp32
    api_key: ${{ secrets.MEMBROWSE_API_KEY }}  # optional
```

**Inputs:**
- `elf` (required): Path to ELF file
- `ld` (required): Space-separated list of linker script paths
- `target_name` (required): Target name like esp32, stm32f4
- `api_key` (optional): API key for MemBrowse

**Typical workflow:**
```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened]
  push:
    branches: [main]

jobs:
  memory-analysis:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Build firmware
        run: make build
      - uses: yourorg/membrowse-action/pr-action@v1.0.0
        with:
          elf: build/firmware.elf
          ld: "src/linker.ld src/memory.ld"
          target_name: esp32
          api_key: ${{ secrets.MEMBROWSE_API_KEY }}
```

### 📊 Historical Analysis (`onboard-action`)

Analyzes memory usage across historical commits for onboarding, building firmware at each commit and uploading memory reports to initialize full memory history.

**Usage:**
```yaml
- uses: yourorg/membrowse-action/onboard-action@v1.0.0
  with:
    num_commits: 50
    build_script: "make clean && make build"
    elf: build/firmware.elf
    ld: "src/linker.ld src/memory.ld"
    target_name: esp32
    api_key: ${{ secrets.MEMBROWSE_API_KEY }}
```

**Inputs:**
- `num_commits` (required): Number of historical commits to process
- `build_script` (required): Shell command to build the firmware
- `elf` (required): Path to generated ELF file after build
- `ld` (required): Space-separated list of linker script paths
- `target_name` (required): Target platform name
- `api_key` (required): API key for MemBrowse

**Typical workflow:**
```yaml
on:
  workflow_dispatch:
    inputs:
      num_commits:
        description: 'Number of commits to analyze'
        required: true
        default: '50'

jobs:
  historical-analysis:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: yourorg/membrowse-action/onboard-action@v1.0.0
        with:
          num_commits: ${{ github.event.inputs.num_commits }}
          build_script: "make clean && make build"
          elf: build/firmware.elf
          ld: "src/linker.ld src/memory.ld"
          target_name: esp32
          api_key: ${{ secrets.MEMBROWSE_API_KEY }}
```

## Requirements

- **GitHub Actions runners**: Linux, macOS, and Windows are all supported
- **Python 3.11+**: Automatically installed by the actions
- **Dependencies**: pyelftools and requests (automatically installed via requirements.txt)
- **Git history**: Full git history is fetched automatically for historical analysis

## Features

- **ELF Analysis**: Direct parsing of ELF files using pyelftools for comprehensive memory analysis
- **DWARF Debug Info**: Extracts source file information from DWARF debug symbols
- **Linker Script Parsing**: Advanced parsing of GNU LD linker scripts to understand memory layout
- **Architecture Detection**: Automatically detects target architecture from ELF files
- **Memory Mapping**: Maps ELF sections to memory regions based on addresses and types
- **JSON Reports**: Generates structured JSON reports with detailed memory usage data
- **MemBrowse Integration**: Uploads reports to MemBrowse SaaS platform (optional)

## Output

Both actions generate JSON reports containing:
- **Memory region usage**: RAM, Flash, and other regions with utilization percentages
- **Section-level breakdown**: ELF sections mapped to memory regions
- **Symbol-level analysis**: Individual symbols with sizes, types, and source files
- **DWARF debug information**: Source file mappings when debug symbols are present
- **Commit metadata**: SHA, message, timestamp, and branch information
- **Target architecture**: Detected from ELF headers (ARM, x86, RISC-V, etc.)

## Testing

Run the test suite:
```bash
cd tests
python -m pytest
```

## License

See [LICENSE](LICENSE) file for details.