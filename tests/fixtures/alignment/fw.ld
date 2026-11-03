/* Sections padded by explicit ALIGN statements, modelled on Trezor's
 * firmware.ld; see build.sh. */
MEMORY {
  FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 256K
  RAM (xrw)  : ORIGIN = 0x20000000, LENGTH = 64K
}
ENTRY(Reset_Handler)
SECTIONS {
  /* Embedded image, then padding to an 8 KB boundary. */
  .kernel : ALIGN(512) {
    kernel_start = .;
    KEEP(*(.kernel_blob));
    kernel_end = .;
    . = ALIGN(0x2000);
  } >FLASH
  /* A reservation directly above an ALIGN: the reservation fill is not
   * alignment padding. */
  .reserved : {
    LONG(0xdeadbeef);
    . = (. + 0x400);
    . = ALIGN(0x200);
  } >FLASH
  /* Code, then string literals without symbols, then padding. */
  .flash : {
    *(.text*)
    *(.rodata*)
    . = ALIGN(512);
  } >FLASH
  .data : {
    _sdata = .;
    *(.data*)
    . = ALIGN(512);
    _edata = .;
  } >RAM AT>FLASH
  .bss (NOLOAD) : { *(.bss*) *(COMMON) } >RAM
  .stack (NOLOAD) : ALIGN(8) { . = . + 0x800; _estack = .; } >RAM
}
