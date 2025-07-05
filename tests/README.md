# Memory Analysis Tests

This directory contains tests for the memory analysis functionality.

## Test Files

### `simple_program.c`
A basic C program designed to test memory analysis functionality. It contains:
- **Global variables** (`.data` section) - initialized data
- **Uninitialized arrays** (`.bss` section) - zero-initialized data  
- **Constant arrays** (`.rodata` section) - read-only data
- **Functions** (`.text` section) - executable code
- **Interrupt handlers** - additional code patterns

### `simple_program.ld`
A linker script that defines a typical embedded system memory layout:
- **FLASH (512KB)** at `0x08000000` - for code and constants
- **RAM (128KB)** at `0x20000000` - for data and stack
- **SRAM2 (32KB)** at `0x20020000` - additional RAM region

The script demonstrates realistic embedded memory organization with proper section placement.

### `test_memory_analysis.py`
Comprehensive test suite that:

1. **Checks Prerequisites** - Verifies GCC and other tools are available
2. **Compiles Test Program** - Builds the C program with custom linker script
3. **Parses Linker Script** - Tests memory region extraction
4. **Generates Bloaty Data** - Creates size analysis (or mock data if Bloaty unavailable)
5. **Creates Memory Report** - Tests full report generation pipeline
6. **Verifies Results** - Validates report structure and content
7. **Integration Test** - Runs the complete `collect_report.sh` workflow

## Running the Tests

### Prerequisites
```bash
# Install a C compiler (one of these)
sudo apt-get install gcc                    # Standard GCC
sudo apt-get install gcc-arm-none-eabi      # ARM cross-compiler

# Python dependencies
pip install python-dateutil
```

### Run Tests
```bash
cd tests
python3 test_memory_analysis.py
```

### Expected Output
```
Memory Analysis Test Suite
========================================
test_01_check_prerequisites ... ok
test_02_compile_test_program ... ok  
test_03_parse_linker_script ... ok
test_04_generate_bloaty_data ... ok
test_05_generate_memory_report ... ok

============================================================
RUNNING FULL INTEGRATION TEST
============================================================
✓ Compiled test program: /tmp/tmpXXXXXX/simple_program.elf
✓ Integration test PASSED

🎉 ALL TESTS PASSED!
```

## Test Coverage

The tests verify:

### ✅ Linker Script Parsing
- Memory region detection (`FLASH`, `RAM`, `SRAM2`)
- Address and size parsing (`0x08000000`, `512K`)
- Region type classification (`FLASH`, `RAM`)
- Validation and overlap detection

### ✅ ELF Compilation
- Custom linker script usage
- Section placement verification
- ELF file format validation

### ✅ Bloaty Integration
- CSV output generation for sections, symbols, segments
- Mock data fallback when Bloaty unavailable
- Size analysis parsing

### ✅ Memory Report Generation
- JSON schema compliance
- Memory region mapping
- Section categorization (`.text`→FLASH, `.data`/`.bss`→RAM)
- Symbol analysis
- Utilization calculations

### ✅ End-to-End Workflow
- Complete `collect_report.sh` execution
- Error handling and validation
- Output format verification

## Troubleshooting

### "No suitable GCC compiler found"
Install GCC or ARM GCC:
```bash
sudo apt-get install gcc
# OR for ARM targets
sudo apt-get install gcc-arm-none-eabi
```

### "Compilation failed"
Check that the linker script syntax is valid:
```bash
arm-none-eabi-ld --verbose
```

### "Bloaty not found"
The test includes mock data fallback, but for full testing install Bloaty:
```bash
sudo apt-get install bloaty
```

### "Import error"
Ensure you're running from the tests directory:
```bash
cd tests
python3 test_memory_analysis.py
```

## Adding New Tests

To add new test cases:

1. **Create new test files** in this directory
2. **Add test methods** to `TestMemoryAnalysis` class
3. **Follow naming convention** `test_XX_description`
4. **Verify prerequisites** before running tests
5. **Clean up resources** in `tearDown()`