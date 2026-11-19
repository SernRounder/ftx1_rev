.syntax unified
.arm
.section .ft8_hooks,"ax",%progbits

/* Replacement for the one FUNC-menu bitmap call that reads the payload
 * area. The stock 110x50 tile has 5488 white pixels in five runs, with
 * only its outer corner pixels transparent. Arguments are frame, y, x. */
.global func_menu_tile
.type func_menu_tile,%function
func_menu_tile:
    add r0,r0,r2,lsl #1
    mov r2,#1600
    mla r0,r1,r2,r0
    movw r3,#0xffff
    mov r1,#50
1:
    cmp r1,#49
    subhs r2,r1,#48
    movlo r2,#0
    cmp r1,#2
    rsbls r2,r1,#3
    add r12,r0,r2,lsl #1
    rsb r2,r2,#55
    lsl r2,r2,#1
2:
    strh r3,[r12],#2
    subs r2,r2,#1
    bne 2b
    add r0,r0,#1600
    subs r1,r1,#1
    bne 1b
    bx lr
.size func_menu_tile, .-func_menu_tile

/* Expand sq9pd's custom button label table (0x6041F3A8) for 0xEE=FT8, 0xEF=CW_DEC.
   Entry (Thumb caller via ldr pc): r0 = stock table, r4 = button id,
   r12 = r4 - 0xE0, lr = return address. Returns label pointer in r1. */
#ifdef FT8_HOOK_VECTORS
.section .ft8_custom_label,"ax",%progbits
#endif
.global ft8_custom_label
.type ft8_custom_label,%function
ft8_custom_label:
    cmp r12,#8
    ldrls r1,.Lcustom_table
    ldrls r1,[r1,r12,lsl #2]
    bxls lr
    cmp r4,#0xee
    adreq r1,.Lft8_label
    bxeq lr
    cmp r4,#0xef
    adreq r1,.Lcw_label
    bxeq lr
    ldr r1,[r0,r4,lsl #2]
    bx lr
.Lcustom_table:
    .word 0x6041f3cc
.Lft8_label:
    .asciz "FT8"
.Lcw_label:
    .asciz "CW_DEC"
    .align 2
.size ft8_custom_label, .-ft8_custom_label
