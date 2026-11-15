/*
 * SPDX-FileCopyrightText: 2022 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */
/**
 *                    ESP32-C6 Linker Script Memory Layout
 * This file describes the memory layout (memory blocks) by virtual memory addresses.
 * This linker script is passed through the C preprocessor to include configuration options.
 * Please use preprocessor features sparingly!
 * Restrict to simple macros with numeric values, and/or #if/#endif blocks.
 */
/*
 * Automatically generated file. DO NOT EDIT.
 * Espressif IoT Development Framework (ESP-IDF) 6.0.3 Configuration Header
 */
       
/* List of deprecated options */
/*
 * SPDX-FileCopyrightText: 2021-2024 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */
/* CPU instruction prefetch padding size for flash mmap scenario */
/*
 * PMP region granularity size
 * Software may determine the PMP granularity by writing zero to pmp0cfg, then writing all ones
 * to pmpaddr0, then reading back pmpaddr0. If G is the index of the least-significant bit set,
 * the PMP granularity is 2^G+2 bytes.
 */
/* CPU instruction prefetch padding size for memory protection scenario */
/* Memory alignment size for PMS */
    /* rtc timer data (s_rtc_timer_retain_mem, see esp_clk.c files). For rtc_timer_data_in_rtc_mem section. */
/*
 * IDRAM0_2_SEG_SIZE_DEFAULT is used when page size is 64KB
 */
MEMORY
{
  /**
   *  All these values assume the flash cache is on, and have the blocks this uses subtracted from the length
   *  of the various regions. The 'data access port' dram/drom regions map to the same iram/irom regions but
   *  are connected to the data port of the CPU and eg allow byte-wise access.
   */
  /* Flash mapped instruction data */
  irom_seg (RX) : org = 0x42000020, len = (0x8000 << 8) - 0x20
  /**
   * (0x20 offset above is a convenience for the app binary image generation.
   * Flash cache has 64KB pages. The .bin file which is flashed to the chip
   * has a 0x18 byte file header, and each segment has a 0x08 byte segment
   * header. Setting this offset makes it simple to meet the flash cache MMU's
   * constraint that (paddr % 64KB == vaddr % 64KB).)
   */
  /**
   * Shared data RAM, excluding memory reserved for ROM bss/data/stack.
   * Enabling Bluetooth & Trace Memory features in menuconfig will decrease the amount of RAM available.
   */
  sram_seg (RWX) : org = (0x40800000), len = 0x4086E610 - (0x40800000)
  /* Flash mapped instruction data */
  drom_seg (R) : org = 0x42000020, len = (0x8000 << 8) - 0x20
  /* (See irom_seg for meaning of 0x20 offset in the above.) */
/**
 *  LP RAM (RTC Memory) Layout for ESP32-C6
 *  Total Size: 16KB (0x4000)
 *  Address Range: 0x50000000 - 0x50004000
 *
 *  The LP RAM persists over deep sleep and is used for:
 *  - ULP coprocessor code and data (optional)
 *  - RTC wake stub code and data
 *  - Data that needs to survive deep sleep
 *  - Bootloader retain memory (for reboot counter, OTA info, etc.)
 *
 *  +-----------------------------+ 0x50004000 (LP RAM end)
 *  | Secure Boot Image Digest    |
 *  | for fast wake secure boot.  | ( For ROM using, must keep it at the end CONFIG_SECURE_BOOT_ROM_FAST_WAKE_RESERVE_SIZE bytes of LP RAM)
 *  |(only if CONFIG_SECURE_BOOT) |
 *  |- - - - - - - - - - - - - - -|
 *  | bootloader_data_rtc_mem     |
 *  | (ESP_BOOTLOADER_RESERVE_RTC)| lp_reserved_seg (RESERVE_RTC_MEM)
 *  |- - - - - - - - - - - - - - -|
 *  | rtc_timer_data_in_rtc_mem   |
 *  | (RTC_TIMER_RESERVE_RTC=24B) |
 *  +-----------------------------+ 0x50004000 - RESERVE_RTC_MEM
 *  | .rtc.force_slow             |
 *  | .rtc_noinit (NOLOAD)        |
 *  | .rtc.bss (NOLOAD)           |
 *  | .rtc.data                   | lp_ram_seg (= rtc_iram_seg = rtc_data_seg = rtc_slow_seg)
 *  | .rtc.force_fast             |
 *  |- - - - - - - - - - - - - - -|
 *  | .rtc.text                   | RTC wake stub code
 *  +-----------------------------+ 0x50000000 + CONFIG_ULP_COPROC_RESERVE_MEM (if ULP enabled)
 *  | ULP Coprocessor Reserve     | (Optional, CONFIG_ULP_COPROC_RESERVE_MEM)
 *  | (code + data)               |
 *  +-----------------------------+ 0x50000000 (LP RAM start)
 */
  /**
   * lp ram memory (RWX). Persists over deep sleep. // TODO: IDF-5667
   */
  lp_ram_seg(RW) : org = 0x50000000, len = 0x4000 - (0 + (24) + 0)
  /* We reduced the size of lp_ram_seg by RESERVE_RTC_MEM value.
     It reserves the amount of LP memory that we use for this memory segment.
     This segment is intended for keeping:
       - (lower addr) rtc timer data (s_rtc_timer_retain_mem, see esp_clk.c files).
       - (higher addr) bootloader rtc data (s_bootloader_retain_mem, when a Kconfig option is on).
     The aim of this is to keep data that will not be moved around and have a fixed address.
  */
  lp_reserved_seg(RW) : org = 0x50000000 + 0x4000 - (0 + (24) + 0), len = (0 + (24) + 0)
}
/* Heap ends at top of sram_seg */
_heap_end = 0x40000000;
/**
 *  The lines below define location alias for .rtc.data section
 *  C6 has no distinguished LP(RTC) fast and slow memory sections, instead, there is a unified LP_RAM section
 *  Thus, the following region segments are not configurable like on other targets
 */
REGION_ALIAS("rtc_text_seg", lp_ram_seg);
REGION_ALIAS("rtc_data_seg", lp_ram_seg);
REGION_ALIAS("rtc_slow_seg", lp_ram_seg);
REGION_ALIAS("rtc_force_fast_seg", lp_ram_seg);
REGION_ALIAS("rtc_force_slow_seg", lp_ram_seg);
REGION_ALIAS("rtc_reserved_seg", lp_reserved_seg );
REGION_ALIAS("iram_text_seg", sram_seg);
REGION_ALIAS("dram_seg", sram_seg);
  REGION_ALIAS("flash_text_seg", irom_seg);
  REGION_ALIAS("flash_rodata_seg", drom_seg);
ALIGN_VECTOR_TABLE = 0x100;
OFFSET_TEE = 0x2e0;
