ENTRY(ft8_arm_api)

MEMORY
{
  /* Stock startup copies only up to 0x606D0000 (exclusive). */
  TAIL (rwx) : ORIGIN = 0x606C2FC0, LENGTH = 0xD040
}

SECTIONS
{
  .payload : {
    KEEP(*(.ft8_api))
    KEEP(*(.ft8_tx_hooks))
    *(.text*)
    *(.rodata*)
    *(.data*)
    . = ALIGN(4);
  } > TAIL

  .unexpected_bss (NOLOAD) : { *(.bss*) *(COMMON) } > TAIL
  ASSERT(SIZEOF(.unexpected_bss) == 0, "Receiver BSS must be initialized in the image")
  /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment) *(.ARM.attributes) }
}
