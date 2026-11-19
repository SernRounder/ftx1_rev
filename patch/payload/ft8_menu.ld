ENTRY(ft8_ui_worker)

MEMORY
{
  HOLE (rwx) : ORIGIN = 0x6052C670, LENGTH = 10970
}

SECTIONS
{
  .payload : {
    /* The live API table has a fixed location at the front of the hole. */
    KEEP(*(.ft8_live_api))
    KEEP(*(.ft8_hooks))
    /* The link runs with --gc-sections: zig whole-archives its compiler_rt, so
       KEEP(*(.text*)) would retain ~120 kB of it inside this 10 kB hole. The
       build script resolves every hook symbol afterwards and fails if the
       collector dropped one. */
    *(.text*)
    *(.rodata*)
    *(.data*)
    . = ALIGN(4);
  } > HOLE

  .unexpected_bss (NOLOAD) : { *(.bss*) *(COMMON) } > HOLE
  ASSERT(SIZEOF(.unexpected_bss) == 0, "Menu state must be initialized in the image")
  /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment) *(.ARM.attributes) }
}
