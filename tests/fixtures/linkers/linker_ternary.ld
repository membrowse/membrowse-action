/* Linker script with ternary (conditional) operations
 * Tests various ternary expression patterns found in real-world embedded linker scripts
 */

/* Base values */
FLASH_START = 0x08000000;
FLASH_LENGTH = 512K;
RAM_START = 0x20000000;
RAM_LENGTH = 128K;

/* Simple ternary with DEFINED - should use FLASH_IMAGE_LENGTH if defined, else FLASH_LENGTH */
/* Since FLASH_IMAGE_LENGTH is not defined, should evaluate to FLASH_LENGTH (512K) */
LIMITED_FLASH_LENGTH = DEFINED(FLASH_IMAGE_LENGTH) ? FLASH_IMAGE_LENGTH : FLASH_LENGTH;

/* Negated DEFINED ternary - should use 0 since OPTION_SETTING_LENGTH is not defined */
OPTION_FALLBACK = !DEFINED(OPTION_SETTING_LENGTH) ? 0 : OPTION_SETTING_LENGTH;

/* Variable that IS defined for testing the true branch */
CUSTOM_RAM_SIZE = 64K;
ACTUAL_RAM_LENGTH = DEFINED(CUSTOM_RAM_SIZE) ? CUSTOM_RAM_SIZE : RAM_LENGTH;

/* QSPI values for ABSOLUTE test */
QSPI_FLASH_LENGTH = 16M;
QSPI_FLASH_PRV_LENGTH = DEFINED(QSPI_FLASH_SIZE) ? QSPI_FLASH_SIZE : QSPI_FLASH_LENGTH;

/* Test nested ternary - FLASH_BOOTLOADER_LENGTH is not defined, so falls through */
FLASH_BOOTLOADER_LENGTH_DEFAULT = 32K;
NESTED_LENGTH = DEFINED(FLASH_IMAGE_LENGTH) ? FLASH_IMAGE_LENGTH :
                DEFINED(FLASH_BOOTLOADER_LENGTH) ? FLASH_BOOTLOADER_LENGTH :
                FLASH_BOOTLOADER_LENGTH_DEFAULT;

MEMORY
{
    /* FLASH region using ternary-computed origin and length */
    FLASH (rx) : ORIGIN = FLASH_START, LENGTH = LIMITED_FLASH_LENGTH

    /* RAM region using ternary that evaluates true branch (CUSTOM_RAM_SIZE is defined) */
    RAM (rwx) : ORIGIN = RAM_START, LENGTH = ACTUAL_RAM_LENGTH

    /* QSPI region using ternary with fallback */
    QSPI (rx) : ORIGIN = 0x90000000, LENGTH = QSPI_FLASH_PRV_LENGTH

    /* SRAM region using nested ternary result */
    SRAM (rwx) : ORIGIN = 0x24000000, LENGTH = NESTED_LENGTH
}

SECTIONS
{
    .text : { *(.text*) } > FLASH
    .data : { *(.data*) } > RAM
    .bss : { *(.bss*) } > RAM
}
