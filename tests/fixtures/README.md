# Test Fixtures

This directory contains test fixtures used by the MemBrowse test suite. These fixtures are real-world firmware binaries and linker scripts from the MicroPython project, used to validate the accuracy of MemBrowse's ELF analysis and linker script parsing.

## Directory Structure

```
fixtures/
└── micropython/
    ├── stm32/
    │   ├── firmware.elf          # STM32F405 MicroPython firmware (5.2MB)
    │   └── linker/
    │       └── stm32f405.ld      # STM32F405 linker script
    └── esp32/
        ├── micropython.elf       # ESP32 MicroPython firmware (20MB)
        └── linker/
            ├── esp-idf/          # ESP-IDF system linker scripts
            ├── esp_rom/          # ESP32 ROM linker scripts
            └── soc/              # ESP32 SOC linker scripts
└── tinygo/                       # examples/blinky1 built with TinyGo 0.44.0
    ├── pca10040.elf              # nRF52832, linked with --emit-relocs
    ├── arduino.elf               # ATmega328P, 2 byte DWARF addresses
    └── linker/                   # TinyGo linker scripts for both targets
└── stripped/
    └── main.elf                  # x86-64 gcc -g -O2, then strip: .eh_frame but no .debug_info
└── meshtastic/picow/             # firmware 2.8.2.c63238c, PlatformIO (arduino-pico, gcc 16.1)
└── tinyusb/                      # examples/device/cdc_msc, CMake, arm-none-eabi gcc 10.3
    ├── stm32f407disco/
    └── feather_nrf52840_express/ # nrf52840_s140_v6.ld INCLUDEs nrf_common.ld
└── nuttx/                        # nuttx 6bc061ed27 + apps 96a0030, configure.sh -l <board>:nsh
    ├── nucleo-f103rb/            # arm-none-eabi gcc 10.3
    └── arduino-mega2560/         # avr-gcc 5.4, no debug info
└── wolfssl/cortex-m4-min-ecc/    # 258f06e524, gcc-arm-cortex-m4-min-ecc target of
                                  # .github/membrowse-targets.json (gcc 13.2, -flto, no -g)
└── trice/f030_inst_uart/         # rokath/trice ed7f4858c9, examples/F030_inst_uart with TCOBS framing,
                                  # xPack arm-none-eabi gcc 15.2.1, -Og -flto -g -gdwarf-2
```

Each project fixture directory holds the ELF, its linker scripts, the GNU LD
map file and `memory_layout.json`, the memory layout the report gave when the
fixture was added. They are used by `test_project_firmware.py`.

## Git LFS

Large binary files (`.elf` files, and the map files of the project fixtures) are stored using **Git Large File Storage (Git LFS)** to avoid bloating the repository.

### Initial Setup

If you're cloning this repository for the first time:

```bash
# Install Git LFS (if not already installed)
# Ubuntu/Debian:
sudo apt-get install git-lfs

# macOS:
brew install git-lfs

# Initialize Git LFS in your repository
git lfs install

# Pull LFS objects
git lfs pull
```

### Verifying LFS Files

After cloning, verify that the ELF files were downloaded correctly:

```bash
# Check file sizes (should be ~5.2MB for STM32, ~20MB for ESP32)
ls -lh tests/fixtures/micropython/stm32/firmware.elf
ls -lh tests/fixtures/micropython/esp32/micropython.elf

# Verify they're actual binary files, not LFS pointers
file tests/fixtures/micropython/stm32/firmware.elf
# Should output: "ELF 32-bit LSB executable, ARM..."
```

If files appear to be small text files (~130 bytes), they're LFS pointer files. Run `git lfs pull` to download the actual binaries.

## Test Coverage

These fixtures are used by:

- `test_micropython_firmware.py` - Tests source file mapping accuracy on real STM32 and ESP32 firmware
- Future integration tests for memory analysis and reporting

## Fixture Details

### STM32 Firmware (`stm32/firmware.elf`)

- **Target**: STM32F405 (PYBV10 board)
- **Architecture**: ARM Cortex-M4
- **Size**: ~5.2MB
- **Purpose**: Tests DWARF debug info processing, symbol extraction, and source file mapping on ARM architecture
- **Key Test Cases**:
  - Static variable mapping (`micropython_ringio_any` → `objringio.c`)
  - Function source mapping (`uart_init`, `I2CHandle1`, `usb_device`)

### ESP32 Firmware (`esp32/micropython.elf`)

- **Target**: ESP32 (Generic board)
- **Architecture**: Xtensa LX6
- **Size**: ~20MB
- **Purpose**: Tests complex linker scripts with multiple included files (ESP-IDF framework)
- **Linker Scripts**: 15 linker scripts including ROM definitions, peripheral mappings, and memory layouts

## Updating Fixtures

To update fixtures with newer MicroPython builds:

1. Build MicroPython for the target platform
2. Copy the new `.elf` file to the appropriate directory
3. Copy any updated linker scripts
4. Commit the changes (Git LFS will handle the binary files)
5. Update test expectations if the firmware structure changed

```bash
# Example: Update STM32 firmware
cp /path/to/micropython/ports/stm32/build-PYBV10/firmware.elf \
   tests/fixtures/micropython/stm32/firmware.elf

# Git will automatically use LFS for .elf files
git add tests/fixtures/micropython/stm32/firmware.elf
git commit -m "Update STM32 test fixture to MicroPython vX.Y.Z"
```

## Size Considerations

**Total size**: ~25MB of binary files (stored in Git LFS)
**Repository impact**: Minimal (LFS pointers are ~130 bytes each)

Git LFS only downloads these files when needed, keeping clone times reasonable while ensuring tests have access to real-world firmware for validation.

## Source

These fixtures are derived from the [MicroPython project](https://github.com/micropython/micropython):
- STM32 port: `ports/stm32/`
- ESP32 port: `ports/esp32/`

MicroPython is licensed under the MIT License.
