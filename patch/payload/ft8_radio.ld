ENTRY(ft8_arm_api)

MEMORY
{
  HOLE (rwx) : ORIGIN = 0x6052C670, LENGTH = 10970
  /* Keep the existing image boundary. The RX stack starts at 0x606D0000. */
  TAIL (rwx) : ORIGIN = 0x606C2FC0, LENGTH = 0xD040
  TRACE_WATCHDOG (rx) : ORIGIN = 0x60481C9C, LENGTH = 0x434
  TRACE_RELEASE (rx) : ORIGIN = 0x604010EC, LENGTH = 0x108
  TRACE_START (rx) : ORIGIN = 0x6040FF3C, LENGTH = 0x1BC
  TRACE_SCAN (rx) : ORIGIN = 0x604104F8, LENGTH = 0x23C
  TRACE_LOG (rx) : ORIGIN = 0x60422320, LENGTH = 0x1C8
}

SECTIONS
{
  .trace_watchdog : { *(.trace_watchdog) } > TRACE_WATCHDOG
  .trace_release : { *(.trace_release) } > TRACE_RELEASE
  .trace_start : { *(.trace_start) } > TRACE_START
  .trace_scan : { *(.trace_scan) } > TRACE_SCAN
  .trace_log : { *(.trace_log) } > TRACE_LOG

  .stage1 : {
    KEEP(*(.ft8_live_api))
    KEEP(*(.ft8_custom_label))
    *(.ft8_live_text .ft8_live_rodata)
    *(.ft8_plugin_text .ft8_plugin_rodata .ft8_plugin_data)
    *(.ft8_vfp_text .ft8_vfp_data)
    *(.ft8_clock_text .ft8_clock_data .ft8_clock_rodata)
    *ft8_hw_fft*.o(.text* .rodata*)
    /* Read-only protocol tables do not consume the tail's code budget. */
    *(.rodata.kFT* .rodata.pulse_table .cw_tone_table)
    *(.text.ft8_my_call)
    *(.text.ft8_profile_bind)
    *(.ft8_profile_text)
    *(.ft8_recent_text)
    *(.text.ft8_rx_dequeue)
    . = ALIGN(4);
  } > HOLE

  .payload : {
    KEEP(*(.ft8_api))
    /* Slot zero is part of the packer's FUNC-tile redirection check. */
    . = ORIGIN(TAIL) + 0x80;
    KEEP(*(.ft8_vectors))
    *(.ft8_tx_hooks)
    KEEP(*(.ft8_hooks))
    *(.text.atanf .rodata.atanhi .rodata.atanlo)
    *(.text* .rodata* .data*)
    . = ALIGN(4);
  } > TAIL

  .unexpected_bss (NOLOAD) : { *(.bss*) *(COMMON) } > TAIL
  ASSERT(SIZEOF(.unexpected_bss) == 0, "FT8 BSS must be initialized in the image")
  /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment) *(.ARM.attributes) }
}
