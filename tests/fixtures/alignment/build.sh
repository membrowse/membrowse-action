#!/bin/sh
# Rebuild the fixtures: fw.elf/fw.map with GNU ld (needs arm-none-eabi-gcc)
# and fw-lld.elf/fw-lld.map with ld.lld (needs clang and ld.lld).
set -e
cd "$(dirname "$0")"
arm-none-eabi-gcc -mcpu=cortex-m4 -mthumb -O2 \
    -ffunction-sections -fdata-sections -c -o fw.o fw.c
arm-none-eabi-gcc -mcpu=cortex-m4 -mthumb -nostdlib \
    -Wl,-z,max-page-size=0x200 \
    -T fw.ld -Wl,-Map=fw.map -o fw.elf fw.o
rm fw.o
clang --target=arm-none-eabi -mcpu=cortex-m4 -mthumb -O2 \
    -ffunction-sections -fdata-sections -c -o fw.o fw.c
ld.lld -z max-page-size=0x200 -T fw.ld -Map=fw-lld.map -o fw-lld.elf fw.o
rm fw.o
