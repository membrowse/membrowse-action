/*
 * simple_program.ld - Simple linker script for testing memory analysis
 * 
 * This linker script defines a typical embedded system memory layout
 * with FLASH and RAM regions, suitable for testing our memory analysis tools.
 */

/* Entry point */
ENTRY(main)

/* Memory layout definition */
MEMORY
{
    /* Flash memory - typically used for code and constants */
    FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 512K
    
    /* RAM memory - used for data and stack */
    RAM (rw) : ORIGIN = 0x20000000, LENGTH = 128K
    
    /* Additional RAM region for testing multiple regions */
    SRAM2 (rw) : ORIGIN = 0x20020000, LENGTH = 32K
}

/* Section definitions */
SECTIONS
{
    /* Code section - goes into FLASH */
    .text :
    {
        . = ALIGN(4);
        *(.text)           /* Main code */
        *(.text.*)         /* Other code sections */
        *(.init)           /* Initialization code */
        *(.fini)           /* Finalization code */
        . = ALIGN(4);
    } > FLASH
    
    /* Read-only data section - goes into FLASH */
    .rodata :
    {
        . = ALIGN(4);
        *(.rodata)         /* Read-only data */
        *(.rodata.*)       /* Other read-only data sections */
        . = ALIGN(4);
    } > FLASH
    
    /* ARM exception table - goes into FLASH */
    .ARM.exidx :
    {
        *(.ARM.exidx*)
    } > FLASH
    
    /* Initialized data section - stored in FLASH, copied to RAM at startup */
    .data :
    {
        . = ALIGN(4);
        _sdata = .;        /* Start of data section in RAM */
        *(.data)           /* Initialized data */
        *(.data.*)         /* Other initialized data sections */
        . = ALIGN(4);
        _edata = .;        /* End of data section in RAM */
    } > RAM AT > FLASH
    
    /* Store the address where .data is stored in FLASH */
    _sidata = LOADADDR(.data);
    
    /* Uninitialized data section - goes into RAM */
    .bss :
    {
        . = ALIGN(4);
        _sbss = .;         /* Start of BSS section */
        *(.bss)            /* Uninitialized data */
        *(.bss.*)          /* Other uninitialized data sections */
        *(COMMON)          /* Common symbols */
        . = ALIGN(4);
        _ebss = .;         /* End of BSS section */
    } > RAM
    
    /* Stack section - goes into RAM */
    .stack :
    {
        . = ALIGN(8);
        _sstack = .;       /* Start of stack */
        . = . + 0x2000;    /* 8KB stack */
        _estack = .;       /* End of stack (top) */
    } > RAM
    
    /* Heap section - goes into remaining RAM */
    .heap :
    {
        . = ALIGN(4);
        _sheap = .;        /* Start of heap */
        . = ORIGIN(RAM) + LENGTH(RAM) - 0x100; /* Leave 256 bytes at end */
        _eheap = .;        /* End of heap */
    } > RAM
    
    /* Additional data section in SRAM2 for testing multiple regions */
    .sram2_data :
    {
        . = ALIGN(4);
        *(.sram2)          /* Data specifically placed in SRAM2 */
        . = ALIGN(4);
    } > SRAM2
    
    /* Debug sections (don't take up memory in target) */
    .comment 0 : { *(.comment) }
    .debug_info 0 : { *(.debug_info) }
    .debug_abbrev 0 : { *(.debug_abbrev) }
    .debug_line 0 : { *(.debug_line) }
    .debug_frame 0 : { *(.debug_frame) }
    .debug_str 0 : { *(.debug_str) }
    .debug_ranges 0 : { *(.debug_ranges) }
}

/* Provide symbols for runtime memory management */
_flash_start = ORIGIN(FLASH);
_flash_size = LENGTH(FLASH);
_ram_start = ORIGIN(RAM);
_ram_size = LENGTH(RAM);
_sram2_start = ORIGIN(SRAM2);
_sram2_size = LENGTH(SRAM2);

/* Calculate memory usage */
_flash_used = SIZEOF(.text) + SIZEOF(.rodata) + SIZEOF(.ARM.exidx) + SIZEOF(.data);
_ram_used = SIZEOF(.data) + SIZEOF(.bss) + SIZEOF(.stack) + SIZEOF(.heap);
_sram2_used = SIZEOF(.sram2_data);