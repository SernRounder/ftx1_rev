ENTRY(_ft8_main_timer)

_stock_timer_tick    = 0xffea5030;
_stock_beep          = 0xffea65fd;
_stock_playback_jobs = 0xfff576bd;
/* Start at the second BSR.W to skip only the playback-end GPIO poll. */
_stock_playback_other_jobs = 0xfff576c0;
_stock_e8            = 0xffed6966;
_stock_tx_power      = 0xffec89f4;
_stock_tx_allowed    = 0xffec7edc;
_stock_select_vfo    = 0xffec6639;
_stock_vfo_mode      = 0xffec670f;
stock_e8_return      = 0xffed60f0;
_stock_swr_prepare   = 0xffeff418;

/* sq9pd MAIN V01-13 dispatch & formatter targets */
_sq9pd_key_by_id_fb   = 0xfff0dc56;
_sq9pd_key_by_code_fb = 0xfff0c816;
_sq9pd_softkey_enable = 0xfff0e0b8;
_sq9pd_softkey_fmt_e9 = 0xfff0f6ca;
_sq9pd_softkey_fmt_fb = 0xfff0e2ad;

MEMORY
{
  /* Stock MAIN ends at 0xfff87dc2. Stay in its last 32 KiB erase block. */
  CODE (rx)    : ORIGIN = 0xfff87dc2, LENGTH = 0xfff88000 - 0xfff87dc2
  /* Unused C2 block inside stock MAIN V01-13 S3 flash range. */
  C2_CODE (rx) : ORIGIN = 0xfff68ba0, LENGTH = 0xfff69165 - 0xfff68ba0
}

SECTIONS
{
  .payload : {
    *(.text*)
    *(P P.*)
    *(.rodata*)
    *(C C.*)
  } > CODE
  .c2 : {
    *(.c2_text*)
    *(.c2_rodata*)
    . = ALIGN(4);
  } > C2_CODE
  .unexpected : { *(.data*) *(.bss*) *(COMMON) } > CODE
  ASSERT(SIZEOF(.unexpected) == 0, "MAIN payload has uninitialized storage")
  /DISCARD/ : { *(.comment) *(.note*) }
}
