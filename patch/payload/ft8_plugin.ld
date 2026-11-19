ENTRY(ft8_queue_entry)

SECTIONS
{
  .plugin 0 : { *(.text* .rodata*) . = ALIGN(4); }
  .unsupported : { *(.data* .bss* .got* .plt* .dynamic* .dyn*) *(COMMON) }
  ASSERT(SIZEOF(.unsupported) == 0, "FT8 plugin must be self-contained PIC")
  /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment) *(.ARM.attributes) }
}
