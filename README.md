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

- **Linux or macOS runners**: Windows is not supported due to Google Bloaty dependency
- **Python 3.11**: Automatically installed by the actions
- **Google Bloaty**: Automatically installed via Homebrew
- **Git history**: Full git history is fetched automatically for historical analysis

## Features

- **Memory Analysis**: Uses Google Bloaty and custom ELF parsing to analyze memory usage
- **Linker Script Parsing**: Parses linker scripts to understand memory layout
- **Architecture Detection**: Automatically detects target architecture from ELF files
- **JSON Reports**: Generates structured JSON reports with memory usage data
- **MemBrowse Integration**: Uploads reports to MemBrowse SaaS platform (optional)

## Output

Both actions generate JSON reports containing:
- Memory region usage (RAM, Flash, etc.)
- Section-level memory breakdown
- Symbol-level memory usage
- Commit metadata and timestamps
- Target architecture information

## Testing

Run the test suite:
```bash
cd tests
python -m pytest
```

## License

See [LICENSE](LICENSE) file for details.