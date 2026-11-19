ENTRY(_softkey_menu_reg_hook)
stock_reg_last = 0xfff27b7a;
stock_timer_set = 0xffea517c;
stock_func_popup = 0xfff2ce56;

SECTIONS
{
    . = 0xfff68ba0;
    .payload : {
        KEEP(*(.text.softkey_hooks))
        *(P*)
        *(.text*)
        *(C*)
        *(.rodata*)
    }
    ASSERT(. <= 0xfff69165, "softkey_main payload exceeds C2 dead-code hole (1478 B)")

    /DISCARD/ : {
        *(.comment)
        *(.note*)
        *(.eh_frame*)
    }
}
