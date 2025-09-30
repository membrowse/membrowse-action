# MemBrowse GitHub Actions

A comprehensive collection of GitHub Actions for analyzing memory usage in embedded firmware projects. Provides deep ELF analysis, linker script parsing, and automated memory reporting with optional integration to the MemBrowse SaaS platform for tracking memory usage trends over time.

## Actions

### 🔍 PR Memory Report (`pr-action`)

Analyzes memory usage of embedded firmware ELF files in pull requests and pushes, generating memory reports to catch regressions before merging.

**Usage:**
```yaml
- uses: membrowse/membrowse-action/pr-action@v1.0.0
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

**Complete workflow examples:**

<details>
<summary><strong>ESP32 Project (ESP-IDF)</strong></summary>

```yaml
name: ESP32 Memory Analysis
on:
  pull_request:
    types: [opened, synchronize, reopened]
  push:
    branches: [main, develop]

jobs:
  memory-analysis:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup ESP-IDF
        uses: espressif/esp-idf-ci-action@v1
        with:
          esp_idf_version: v5.1
          target: esp32
          
      - name: Build firmware
        run: |
          . $IDF_PATH/export.sh
          idf.py build
          
      - name: Analyze memory usage
        uses: membrowse/membrowse-action/pr-action@v1.0.0
        with:
          elf: build/firmware.elf
          ld: "build/esp-idf/esp32/esp32.project.ld build/ldgen_libraries"
          target_name: esp32
          api_key: ${{ secrets.MEMBROWSE_API_KEY }}
```
</details>

<details>
<summary><strong>STM32 Project (STM32CubeIDE)</strong></summary>

```yaml
name: STM32 Memory Analysis
on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  memory-analysis:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Install ARM toolchain
        run: |
          sudo apt-get update
          sudo apt-get install gcc-arm-none-eabi
          
      - name: Build firmware
        run: |
          make clean
          make all
          
      - name: Analyze memory usage
        uses: membrowse/membrowse-action/pr-action@v1.0.0
        with:
          elf: build/firmware.elf
          ld: "STM32F746ZGTx_FLASH.ld"
          target_name: stm32f746zg
          api_key: ${{ secrets.MEMBROWSE_API_KEY }}
```
</details>

<details>
<summary><strong>Arduino Project</strong></summary>

```yaml
name: Arduino Memory Analysis
on: [push, pull_request]

jobs:
  memory-analysis:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Arduino CLI
        uses: arduino/setup-arduino-cli@v1
        
      - name: Install Arduino core
        run: |
          arduino-cli core update-index
          arduino-cli core install arduino:avr
          
      - name: Build sketch
        run: |
          arduino-cli compile --fqbn arduino:avr:uno sketch/
          
      - name: Analyze memory usage
        uses: membrowse/membrowse-action/pr-action@v1.0.0
        with:
          elf: sketch/build/arduino.avr.uno/sketch.ino.elf
          ld: "sketch/build/arduino.avr.uno/sketch.ino.with_bootloader.ld"
          target_name: arduino_uno
          api_key: ${{ secrets.MEMBROWSE_API_KEY }}
```
</details>

### 📊 Historical Analysis (`onboard-action`)

Analyzes memory usage across historical commits for onboarding, building firmware at each commit and uploading memory reports to initialize full memory history.

**Usage:**
```yaml
- uses: membrowse/membrowse-action/onboard-action@v1.0.0
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

**Advanced onboarding workflow:**
```yaml
name: MemBrowse Historical Onboarding
on:
  workflow_dispatch:
    inputs:
      num_commits:
        description: 'Number of commits to analyze (max 100)'
        required: true
        default: '50'
      branch:
        description: 'Branch to analyze (default: main)'
        required: false
        default: 'main'

jobs:
  historical-analysis:
    runs-on: ubuntu-latest
    timeout-minutes: 180  # Allow up to 3 hours for large histories
    steps:
      - uses: actions/checkout@v3
        with:
          fetch-depth: 0  # Required for full history
          
      - name: Setup build environment
        run: |
          # Add any necessary build dependencies
          sudo apt-get update
          sudo apt-get install gcc-arm-none-eabi make
          
      - name: Run historical memory analysis
        uses: membrowse/membrowse-action/onboard-action@v1.0.0
        with:
          num_commits: ${{ github.event.inputs.num_commits }}
          build_script: |
            make clean
            make TARGET=release all
          elf: build/firmware.elf
          ld: "linker/memory.ld linker/sections.ld"
          target_name: stm32f4
          api_key: ${{ secrets.MEMBROWSE_API_KEY }}
          
      - name: Upload analysis artifacts
        uses: actions/upload-artifact@v3
        if: always()
        with:
          name: memory-reports
          path: |
            *.json
            build-logs/
          retention-days: 30
```

## Requirements

- **GitHub Actions runners**: Linux, macOS, and Windows are all supported
- **Python 3.7+**: Automatically installed by the actions
- **Dependencies**: pyelftools and requests (automatically installed)
- **Git history**: Full git history is fetched automatically for historical analysis
- **ELF with debug symbols**: Required for source file mapping (compile with `-g` flag)

## Troubleshooting

### Common Issues

**❌ "ELF file not found"**
```bash
# Verify your build produces an ELF file
ls -la build/
# Ensure the path matches your build output
```

**❌ "No memory regions found"**
- Check linker script paths are correct
- Ensure scripts contain `MEMORY { }` blocks
- Verify files are accessible during the action

**❌ "Architecture detection failed"**
- Ensure ELF file is valid: `file firmware.elf`
- Check ELF was built for embedded target (not host system)

**❌ "Upload failed" (MemBrowse integration)**
- Verify API key is set in repository secrets
- Check `MEMBROWSE_UPLOAD_URL` is configured in repository variables
- Ensure network connectivity allows HTTPS requests

### Debug Mode

Enable detailed logging by setting environment variables:

```yaml
- name: Analyze memory usage
  env:
    MEMBROWSE_DEBUG: "1"
  uses: membrowse/membrowse-action/pr-action@v1.0.0
  # ... other inputs
```

### Manual Testing

Test the analysis locally before using in GitHub Actions:

```bash
# Clone the repository
git clone https://github.com/membrowse/membrowse-action.git
cd membrowse-action

# Install the package
pip install -e .

# Run analysis on your firmware
python -m membrowse.core.cli \
  --elf-path /path/to/firmware.elf \
  --memory-regions /path/to/regions.json \
  --output report.json

# Or use the orchestration script
bash scripts/collect_report.sh \
  /path/to/firmware.elf \
  "/path/to/linker.ld" \
  target_name \
  "" \
  $(git rev-parse HEAD)
```

### Running Onboarding Locally

Process historical commits and generate memory reports locally without GitHub Actions:

```bash
# Navigate to your firmware project directory
cd /path/to/your/firmware-project

# Install membrowse
pip install /path/to/membrowse-action

# Ensure you have full git history
git fetch --unshallow || true
git fetch --all

# Run historical analysis
# Syntax: onboard.sh <num_commits> <build_script> <elf_path> <ld_paths> <target_name> <api_key>
bash /path/to/membrowse-action/scripts/onboard.sh \
  50 \
  "make clean && make all" \
  "build/firmware.elf" \
  "src/linker.ld src/memory.ld" \
  "stm32f4" \
  "$MEMBROWSE_API_KEY"
```

**Example: ESP32 Project**
```bash
# ESP32 with ESP-IDF build system
export MEMBROWSE_UPLOAD_URL="https://membrowse.appspot.com/api/upload"
bash /path/to/membrowse-action/scripts/onboard.sh \
  100 \
  "idf.py build" \
  "build/firmware.elf" \
  "build/esp-idf/esp32/esp32.project.ld" \
  "esp32" \
  "$MEMBROWSE_API_KEY"
```

**Example: STM32 with ARM GCC**
```bash
export MEMBROWSE_UPLOAD_URL="https://membrowse.appspot.com/api/upload"
bash /path/to/membrowse-action/scripts/onboard.sh \
  25 \
  "make clean && make" \
  "build/firmware.elf" \
  "STM32F746ZGTx_FLASH.ld" \
  "stm32f746zg" \
  "$MEMBROWSE_API_KEY"
```

**Notes:**
- The script will checkout each commit sequentially, build it, analyze it, and upload results
- Build failures will stop the onboarding process
- Make sure your build script works from a clean checkout
- The script processes commits from oldest to newest
- Set `MEMBROWSE_UPLOAD_URL` environment variable if using a custom API endpoint
- Use empty string `""` for `api_key` to skip uploading and only generate local JSON reports
```

## Key Features

### 🔬 Advanced ELF Analysis
- **Multi-architecture Support**: ARM Cortex-M, Xtensa (ESP32), RISC-V, x86, and more
- **Symbol-level Analysis**: Extracts individual symbols with sizes, types, and memory locations
- **DWARF Debug Integration**: Maps symbols to source files using debug information
- **Section Mapping**: Automatically maps ELF sections to memory regions

### 📋 Intelligent Linker Script Parsing
- **GNU LD Compatibility**: Supports standard GNU linker script syntax
- **Expression Evaluation**: Handles complex expressions with variables and arithmetic
- **Architecture-specific Patterns**: Optimized parsing for ESP-IDF, STM32, Nordic nRF, and other platforms
- **Hierarchical Memory Regions**: Supports parent-child memory relationships

### 📊 Comprehensive Reporting
- **Memory Utilization**: Detailed usage statistics for Flash, RAM, and custom regions
- **JSON Schema**: Structured output compatible with analysis tools
- **Source File Mapping**: Links memory usage back to specific source files
- **Trend Analysis**: Historical memory usage tracking (with MemBrowse integration)

### 🏗️ CI/CD Integration
- **Pull Request Analysis**: Catch memory regressions before merging
- **Historical Onboarding**: Bulk analysis of commit history
- **Cross-platform Support**: Works on Linux, macOS, and Windows runners
- **Zero Configuration**: Automatic architecture detection and memory layout analysis

### ⚡ Performance Optimization
- **Fast Mode**: Optional `--skip-line-program` flag for 24-31% faster analysis
- **Configurable Coverage**: Balance between speed and source file coverage
- **Efficient Processing**: Optimized for large firmware files (>10MB)
- **ARM**: 97% → 88% coverage, 9.3s → 7.1s (24% faster)
- **ESP32**: 76% → 65% coverage, 30.1s → 20.8s (31% faster)

## Architecture Support

Automatically detects and optimizes parsing for:

| Platform | Architecture | Linker Features | Status |
|----------|--------------|-----------------|--------|
| **ESP32/ESP8266** | Xtensa | ESP-IDF memory layout, custom variables | ✅ Full Support |
| **STM32** | ARM Cortex-M | HAL memory regions, hierarchical layout | ✅ Full Support |
| **Nordic nRF** | ARM Cortex-M | SoftDevice awareness, bootloader regions | ✅ Full Support |
| **RISC-V** | RISC-V | QEMU and embedded targets | ✅ Full Support |
| **Arduino** | Various | Standard Arduino memory layouts | ✅ Full Support |
| **Custom** | ARM/x86/Others | Generic GNU LD parsing | ✅ Full Support |

## Package Structure

The project is organized as a proper Python package:

```
membrowse/                          # Main Python package
├── core/                           # Core coordination & CLI
│   ├── cli.py                      # Command-line interface
│   ├── generator.py                # Memory report generation
│   ├── analyzer.py                 # Main ELF analysis coordination
│   ├── models.py                   # Data classes
│   └── exceptions.py               # Exception hierarchy
│
├── analysis/                       # Analysis components
│   ├── dwarf.py                    # DWARF debug information
│   ├── sources.py                  # Source file resolution
│   ├── symbols.py                  # ELF symbol extraction
│   ├── sections.py                 # ELF section analysis
│   └── mapper.py                   # Section-to-region mapping
│
├── linker/                         # Linker script parsing
│   ├── parser.py                   # GNU LD parser
│   ├── cli.py                      # Linker parser CLI
│   └── elf_info.py                 # Architecture detection
│
└── api/                            # API client
    └── client.py                   # MemBrowse integration

scripts/                            # Shell orchestration
└── collect_report.sh               # Main workflow script
```

## Output Format

Generates comprehensive JSON reports with:

```json
{
  "memory_regions": {
    "FLASH": {
      "address": "0x08000000",
      "size": 524288,
      "used": 245760,
      "utilization": 46.9,
      "sections": [".text", ".rodata"]
    },
    "RAM": {
      "address": "0x20000000", 
      "size": 131072,
      "used": 12345,
      "utilization": 9.4,
      "sections": [".data", ".bss"]
    }
  },
  "symbols": [
    {
      "name": "main",
      "size": 234,
      "type": "FUNC",
      "address": "0x08001234",
      "source_file": "src/main.c"
    }
  ],
  "architecture": "arm",
  "target": "stm32f4",
  "commit_info": {
    "sha": "abc123...",
    "message": "Add new feature",
    "timestamp": "2024-01-15T10:30:00Z"
  }
}
```

## Development

### Installation

```bash
# Install in development mode
pip install -e .

# Or install with development dependencies
pip install -e ".[dev]"
```

### Testing

```bash
# Run all tests
python -m pytest tests/

# Run specific test categories
python -m pytest tests/test_static_variable_source_mapping.py -v
python -m pytest tests/test_micropython_firmware.py -v

# Run with verbose output
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=membrowse
```

### Code Quality

```bash
# Lint membrowse package
pylint membrowse/

# Lint tests
pylint tests/

# Check all code with scores
pylint membrowse/ tests/ --score=yes
```

### Local Testing

```bash
# Test linker script parsing directly
python -m membrowse.linker.cli path/to/linker.ld

# Test complete ELF analysis
python -m membrowse.core.cli \
  --elf-path firmware.elf \
  --memory-regions regions.json \
  --output report.json

# Fast mode: skip line program processing (24-31% faster)
python -m membrowse.core.cli \
  --elf-path firmware.elf \
  --memory-regions regions.json \
  --output report.json \
  --skip-line-program

# Test full workflow
bash scripts/collect_report.sh \
  firmware.elf \
  "linker.ld" \
  target_name \
  api_key
```

## License

See [LICENSE](LICENSE) file for details.