ENTRY(ft8_tick)

MEMORY
{
  STAGE1 (rx)  : ORIGIN = 0x6052C670, LENGTH = 10972  /* 镜像内 0xFF 空洞, 文件偏移 0x12c670 */
}

SECTIONS
{
  .text : {
    KEEP(*(.text.ft8_tick))
    *(.text*)
    *(.rodata*)
    . = ALIGN(4);
  } > STAGE1

  /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment) *(.ARM.attributes) }
}
